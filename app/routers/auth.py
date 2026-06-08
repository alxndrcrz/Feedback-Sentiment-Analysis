"""
app/routers/auth.py
───────────────────
Same as before with added:
  - Login rate limiting: 5 attempts → 15-minute lockout per IP/email
  - OTP attempt limiting: 3 wrong attempts → must request new code
"""

from fastapi import APIRouter, HTTPException, Request
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from app.database import supabase
from app.schemas  import AdminRegisterData, LoginData
from app.utils    import generate_org_code, package_session

router = APIRouter(prefix="/api", tags=["Auth"])


# ══════════════════════════════════════════════════════════════════════════════
# RATE LIMITING  (in-memory — sufficient for dev/single-server)
# Production: replace with Redis-backed limiter
# ══════════════════════════════════════════════════════════════════════════════

# Login: 5 attempts per email within 15 minutes → lockout
_login_attempts: dict = defaultdict(list)   # email → [datetime, ...]
LOGIN_MAX_ATTEMPTS  = 5
LOGIN_WINDOW_MINS   = 15
LOGIN_LOCKOUT_MINS  = 15

# OTP verify: 3 wrong attempts → must request new code
_otp_attempts: dict = defaultdict(int)      # email → attempt count
OTP_MAX_ATTEMPTS = 3


def _check_login_rate(email: str):
    """Raises 429 if the email has exceeded the login attempt limit."""
    now    = datetime.now(timezone.utc)
    window = now - timedelta(minutes=LOGIN_WINDOW_MINS)

    # Keep only attempts within the window
    _login_attempts[email] = [t for t in _login_attempts[email] if t > window]

    if len(_login_attempts[email]) >= LOGIN_MAX_ATTEMPTS:
        # Find when the oldest attempt in window will expire
        oldest  = _login_attempts[email][0]
        unlock  = oldest + timedelta(minutes=LOGIN_LOCKOUT_MINS)
        mins_left = max(1, int((unlock - now).total_seconds() / 60))
        raise HTTPException(
            status_code=429,
            detail=f"Too many login attempts. Account temporarily locked. Try again in {mins_left} minute(s)."
        )


def _record_login_failure(email: str):
    _login_attempts[email].append(datetime.now(timezone.utc))


def _clear_login_attempts(email: str):
    _login_attempts.pop(email, None)


def _check_otp_attempts(email: str):
    """Raises 429 if OTP has been attempted too many times."""
    if _otp_attempts.get(email, 0) >= OTP_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail=f"Too many incorrect OTP attempts. Please request a new code."
        )


def _record_otp_failure(email: str):
    _otp_attempts[email] = _otp_attempts.get(email, 0) + 1


def _clear_otp_attempts(email: str):
    _otp_attempts.pop(email, None)


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN REGISTRATION
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/register/admin")
async def register_admin(data: AdminRegisterData):
    try:
        res = supabase.auth.sign_up({
            "email":    data.email.lower().strip(),
            "password": data.password,
        })
        if res.user is None:
            raise HTTPException(status_code=400, detail="Registration failed. This email may already be registered.")
        print(f"✅ ADMIN SIGNUP: OTP sent → {data.email}")
        return {"status": "success", "message": "Verification code sent to your email."}
    except HTTPException:
        raise
    except Exception as e:
        msg = str(e).lower()
        if "already registered" in msg:
            raise HTTPException(status_code=400, detail="This email is already registered. Please log in instead.")
        raise HTTPException(status_code=400, detail="Registration failed. Please try again.")


# ══════════════════════════════════════════════════════════════════════════════
# USER REGISTRATION
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/register/user")
async def register_user(data: dict):
    email    = data.get("email", "").lower().strip()
    password = data.get("password", "")
    org_code = data.get("org_code", "").strip().upper()

    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password are required.")
    if not org_code:
        raise HTTPException(status_code=400, detail="Organization code is required.")

    try:
        org_check = supabase.table("organizations").select("org_code").eq("org_code", org_code).execute()
        if not org_check.data:
            raise HTTPException(status_code=400, detail="Invalid organization code. Please check with your admin.")

        res = supabase.auth.sign_up({"email": email, "password": password})
        if res.user is None:
            raise HTTPException(status_code=400, detail="Registration failed. This email may already be registered.")

        print(f"✅ USER SIGNUP: OTP sent → {email} (org: {org_code})")
        return {"status": "success", "message": "Verification code sent to your email."}
    except HTTPException:
        raise
    except Exception as e:
        msg = str(e).lower()
        if "already registered" in msg:
            raise HTTPException(status_code=400, detail="This email is already registered. Please log in instead.")
        raise HTTPException(status_code=400, detail="Registration failed. Please check your details and try again.")


# ══════════════════════════════════════════════════════════════════════════════
# OTP VERIFICATION
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/verify-otp")
async def verify_otp(data: dict):
    email     = data.get("email", "").lower().strip()
    token     = data.get("token", "").strip()
    role      = data.get("role", "user")
    full_name = (data.get("full_name") or "New User").strip()

    if not email or not token:
        raise HTTPException(status_code=400, detail="Email and OTP code are required.")

    # Check OTP attempt limit
    _check_otp_attempts(email)

    try:
        auth_res = supabase.auth.verify_otp({"email": email, "token": token, "type": "signup"})
    except Exception as e:
        _record_otp_failure(email)
        remaining = OTP_MAX_ATTEMPTS - _otp_attempts.get(email, 0)
        if remaining <= 0:
            raise HTTPException(status_code=429, detail="Too many incorrect OTP attempts. Please request a new code.")
        raise HTTPException(
            status_code=400,
            detail=f"Invalid or expired OTP. {remaining} attempt(s) remaining."
        )

    if not auth_res.user:
        _record_otp_failure(email)
        raise HTTPException(status_code=400, detail="Verification failed. Please request a new code.")

    # Success — clear attempt counter
    _clear_otp_attempts(email)

    uid          = auth_res.user.id
    session_data = package_session(auth_res.session)

    # Return early if profile already exists
    existing = supabase.table("profiles").select("*").eq("id", uid).execute()
    if existing.data:
        profile = existing.data[0]
        return {"status": "success", "session": session_data, "org_code": profile.get("org_code"), "user": profile}

    # Create profile
    final_org_code = None

    if role == "admin":
        org_name       = (data.get("org_name") or "My Organization").strip()
        final_org_code = generate_org_code(org_name)
        supabase.table("organizations").insert({"org_name": org_name, "org_code": final_org_code, "admin_id": uid}).execute()
        supabase.table("profiles").insert({
            "id": uid, "email": email, "full_name": full_name,
            "role": "admin", "org_code": final_org_code, "org_name": org_name,
        }).execute()
        print(f"✅ ADMIN CREATED: {email} | org_code={final_org_code}")

        try:
            supabase.table("departments").insert([
                {"name": "IT Department",     "org_code": final_org_code, "is_default": True},
                {"name": "Human Resources",   "org_code": final_org_code, "is_default": True},
                {"name": "Sales & Marketing", "org_code": final_org_code, "is_default": True},
            ]).execute()
            supabase.table("categories").insert([
                {"name": "Work Environment", "org_code": final_org_code, "is_default": True},
                {"name": "Management",       "org_code": final_org_code, "is_default": True},
                {"name": "Tools & Equipment","org_code": final_org_code, "is_default": True},
            ]).execute()
        except Exception as e:
            print(f"⚠️ SEEDING WARNING: {e}")

    else:
        final_org_code = data.get("org_code", "").strip().upper()
        if not final_org_code:
            raise HTTPException(status_code=400, detail="Organization code is missing.")
        org_row = supabase.table("organizations").select("org_name").eq("org_code", final_org_code).execute()
        if not org_row.data:
            raise HTTPException(status_code=400, detail="This organization code does not exist.")
        org_name = org_row.data[0]["org_name"]
        supabase.table("profiles").insert({
            "id": uid, "email": email, "full_name": full_name,
            "role": "user", "org_code": final_org_code, "org_name": org_name,
        }).execute()
        print(f"✅ USER CREATED: {email} joined {org_name} ({final_org_code})")

    try:
        new_profile  = supabase.table("profiles").select("*").eq("id", uid).single().execute()
        profile_data = new_profile.data
    except Exception:
        profile_data = {
            "id": uid, "email": email, "full_name": full_name,
            "role": role, "org_code": final_org_code,
            "org_name": org_name if role == "admin" else data.get("org_name")
        }

    return {"status": "success", "session": session_data, "org_code": final_org_code, "user": profile_data}


# ══════════════════════════════════════════════════════════════════════════════
# LOGIN  (with rate limiting)
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/login")
async def login(data: LoginData):
    email = data.email.lower().strip()

    # Check rate limit BEFORE attempting auth
    _check_login_rate(email)

    try:
        auth_res = supabase.auth.sign_in_with_password({"email": email, "password": data.password})
        profile  = supabase.table("profiles").select("*").eq("id", auth_res.user.id).single().execute()

        if not profile.data:
            raise HTTPException(status_code=404, detail="Account profile not found. Please register first.")

        # Success — clear any recorded failures
        _clear_login_attempts(email)
        print(f"✅ LOGIN: {email} | role={profile.data.get('role')}")

        return {"status": "success", "session": package_session(auth_res.session), "user": profile.data}

    except HTTPException:
        raise
    except Exception as e:
        # Record the failure for rate limiting
        _record_login_failure(email)

        # Tell the user how many attempts remain
        attempts_used = len(_login_attempts.get(email, []))
        remaining     = LOGIN_MAX_ATTEMPTS - attempts_used

        if remaining <= 0:
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed attempts. Account locked for {LOGIN_LOCKOUT_MINS} minutes."
            )

        print(f"🔥 LOGIN FAILED: {email} | attempts={attempts_used}")
        raise HTTPException(
            status_code=401,
            detail=f"Invalid email or password. {remaining} attempt(s) remaining before lockout."
        )


# ══════════════════════════════════════════════════════════════════════════════
# RESEND OTP
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/resend-otp")
async def resend_otp(data: dict):
    email = data.get("email", "").lower().strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required.")
    try:
        # Reset OTP attempt counter when a new code is requested
        _clear_otp_attempts(email)
        supabase.auth.resend({"type": "signup", "email": email})
        print(f"✅ RESEND OTP → {email}")
        return {"status": "success", "message": "New code sent to your email."}
    except Exception as e:
        msg = str(e).lower()
        if "rate limit" in msg:
            raise HTTPException(status_code=429, detail="Please wait before requesting another code.")
        raise HTTPException(status_code=400, detail="Could not resend code. Please try again.")


# ══════════════════════════════════════════════════════════════════════════════
# LOGOUT
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/logout")
async def logout():
    return {"status": "success", "message": "Logged out successfully."}


# ══════════════════════════════════════════════════════════════════════════════
# ORG SETUP + SUPERVISORS (used by feedback form)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/org-setup/{org_code}")
async def get_org_setup(org_code: str):
    try:
        depts = supabase.table("departments").select("id, name").eq("org_code", org_code).execute()
        cats  = supabase.table("categories").select("id, name").eq("org_code", org_code).execute()
        return {"departments": depts.data, "categories": cats.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to load organization data.")


@router.get("/supervisors/{dept_id}")
async def get_supervisors_by_dept(dept_id: int):
    try:
        res = supabase.table("supervisors").select("id, name").eq("department_id", dept_id).execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to load supervisors.")