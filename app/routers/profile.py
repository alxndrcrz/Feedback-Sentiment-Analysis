"""
app/routers/profile.py
──────────────────────
Profile management endpoints — works for both admin and user roles.

  GET    /api/profile              — fetch current user's profile
  PATCH  /api/profile/name         — update full name only
  POST   /api/profile/change-password — change password (requires current password)

SECURITY DECISIONS:
  - Email is READ-ONLY. Changing email requires re-verification; not supported here.
  - Role and org_code are READ-ONLY. Never exposed as editable.
  - Password change requires the CURRENT password first (re-authentication).
  - Full name goes through sanitize_text() to prevent XSS.
  - All endpoints require a valid session token via Authorization header.
  - No user can update another user's profile (ID comes from token, not request body).
"""

from fastapi import APIRouter, HTTPException, Header
from app.database import supabase
from app.utils    import sanitize_text

router = APIRouter(prefix="/api", tags=["Profile"])


# ── Session helper ────────────────────────────────────────────────────────────

def _get_uid(authorization: str) -> str:
    """Extracts and verifies user ID from Bearer token. Raises 401 if invalid."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        token    = authorization.replace("Bearer ", "").strip()
        user_res = supabase.auth.get_user(token)
        if not user_res.user:
            raise HTTPException(status_code=401, detail="Invalid or expired session.")
        return user_res.user.id
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Session verification failed.")


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/profile
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/profile", summary="Get current user's profile")
async def get_profile(authorization: str = Header(None)):
    uid = _get_uid(authorization)
    try:
        res = supabase.table("profiles").select("*").eq("id", uid).single().execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Profile not found.")

        profile = res.data
        # Never return sensitive fields to the frontend
        return {
            "status":    "success",
            "profile": {
                "id":        profile.get("id"),
                "full_name": profile.get("full_name", ""),
                "email":     profile.get("email", ""),      # Read-only display
                "role":      profile.get("role", ""),        # Read-only display
                "org_name":  profile.get("org_name", ""),    # Read-only display
                "org_code":  profile.get("org_code", ""),    # Read-only display
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"🔥 GET PROFILE ERROR: {e}")
        raise HTTPException(status_code=500, detail="Failed to load profile.")


# ══════════════════════════════════════════════════════════════════════════════
# PATCH /api/profile/name
# ══════════════════════════════════════════════════════════════════════════════

@router.patch("/profile/name", summary="Update full name only")
async def update_name(data: dict, authorization: str = Header(None)):
    """
    Only full_name is editable. Email, role, and org_code are immutable.
    Name is sanitized to prevent XSS before storage.
    """
    uid       = _get_uid(authorization)
    new_name  = data.get("full_name", "").strip()

    # Validate
    if not new_name:
        raise HTTPException(status_code=400, detail="Full name cannot be empty.")
    if len(new_name) < 2:
        raise HTTPException(status_code=400, detail="Name must be at least 2 characters.")
    if len(new_name) > 50:
        raise HTTPException(status_code=400, detail="Name cannot exceed 50 characters.")

    # Sanitize (XSS prevention)
    safe_name = sanitize_text(new_name)

    try:
        supabase.table("profiles") \
            .update({"full_name": safe_name}) \
            .eq("id", uid) \
            .execute()

        print(f"✅ NAME UPDATED: user={uid} new_name={safe_name}")
        return {"status": "success", "full_name": safe_name}

    except Exception as e:
        print(f"🔥 UPDATE NAME ERROR: {e}")
        raise HTTPException(status_code=500, detail="Failed to update name.")


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/profile/change-password
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/profile/change-password", summary="Change password (requires current password)")
async def change_password(data: dict, authorization: str = Header(None)):
    """
    Requires the user to supply their CURRENT password for re-authentication
    before setting a new one. This prevents session hijacking from leading
    to a password change.

    Steps:
      1. Verify session token (user must be logged in).
      2. Re-authenticate with current password (proves intent).
      3. Validate new password strength server-side.
      4. Update via Supabase Auth.
    """
    uid          = _get_uid(authorization)
    current_pass = data.get("current_password", "").strip()
    new_pass     = data.get("new_password",     "").strip()
    confirm_pass = data.get("confirm_password", "").strip()

    # ── Validate inputs ──
    if not current_pass or not new_pass or not confirm_pass:
        raise HTTPException(status_code=400, detail="All password fields are required.")
    if new_pass != confirm_pass:
        raise HTTPException(status_code=400, detail="New passwords do not match.")
    if len(new_pass) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    import re
    errors = []
    if not re.search(r"[A-Z]",               new_pass): errors.append("uppercase letter")
    if not re.search(r"[a-z]",               new_pass): errors.append("lowercase letter")
    if not re.search(r"[0-9]",               new_pass): errors.append("number")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", new_pass): errors.append("special character")
    if errors:
        raise HTTPException(status_code=400, detail=f"Password must include: {', '.join(errors)}.")

    if new_pass == current_pass:
        raise HTTPException(status_code=400, detail="New password must be different from current password.")

    # ── Re-authenticate with current password ──
    try:
        profile_res = supabase.table("profiles").select("email").eq("id", uid).single().execute()
        if not profile_res.data:
            raise HTTPException(status_code=404, detail="Profile not found.")
        email = profile_res.data["email"]

        # This will throw if current password is wrong
        supabase.auth.sign_in_with_password({"email": email, "password": current_pass})

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Current password is incorrect.")

    # ── Set new password ──
    try:
        supabase.auth.update_user({"password": new_pass})
        print(f"✅ PASSWORD CHANGED: user={uid}")
        return {"status": "success", "message": "Password updated successfully."}
    except Exception as e:
        print(f"🔥 CHANGE PASSWORD ERROR: {e}")
        raise HTTPException(status_code=500, detail="Failed to update password.")
