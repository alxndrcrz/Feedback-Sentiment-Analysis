"""
app/routers/password.py
───────────────────────
Handles the 3-step forgot-password flow:
  POST /api/forgot-password      — Step 1: send 6-digit reset code
  POST /api/verify-reset-code    — Step 2: verify the code
  POST /api/update-password      — Step 3: set new password
"""

from fastapi import APIRouter, HTTPException

from app.database import supabase
from app.utils    import package_session

router = APIRouter(prefix="/api", tags=["Password Recovery"])


# ── Step 1: Send Reset Code ──────────────────────────────────────────────────

@router.post("/forgot-password", summary="Send 6-digit password reset code")
async def forgot_password(data: dict):
    email = data.get("email", "").lower().strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required.")

    try:
        # Check if user exists (keep this internal for your logic)
        user_query = supabase.table("profiles").select("id").eq("email", email).execute()

        # ONLY send the email if the user exists
        if user_query.data:
            supabase.auth.reset_password_for_email(email)
            print(f"📩 FORGOT PASSWORD: Reset code sent → {email}")
        else:
            # We don't throw a 404 here anymore to prevent enumeration
            print(f"ℹ️ FORGOT PASSWORD: Email {email} not found, but we stay silent.")

        # ALWAYS return this message to the frontend
        return {
            "status": "success", 
            "message": "If an account exists with this email, a reset code has been sent."
        }

    except Exception as e:
        # Keep internal errors hidden from the user
        print(f"🔥 FORGOT PASSWORD ERROR: {e}")
        return {"status": "success", "message": "If an account exists with this email, a reset code has been sent."}


# ── Step 2: Verify Reset Code ────────────────────────────────────────────────

@router.post("/verify-reset-code", summary="Verify the 6-digit password reset OTP")
async def verify_reset_code(data: dict):
    email = data.get("email", "").lower().strip()
    token = data.get("token", "").strip()

    if not email or not token:
        raise HTTPException(status_code=400, detail="Email and code are required.")

    try:
        # type must be "recovery" for password-reset OTPs
        auth_res = supabase.auth.verify_otp(
            {"email": email, "token": token, "type": "recovery"}
        )
        print(f"✅ RESET CODE VERIFIED: {email}")
        return {"status": "success", "session": package_session(auth_res.session)}

    except Exception as e:
        print(f"🔥 RESET CODE ERROR: {e}")
        raise HTTPException(status_code=400, detail="Invalid or expired reset code.")


# ── Step 3: Update Password ──────────────────────────────────────────────────

@router.post("/update-password", summary="Set a new password after OTP is verified")
async def update_password(data: dict):
    """
    Requires the user to be in an active recovery session set by /verify-reset-code.
    The Supabase client library holds the session from the previous call.

    NOTE: For a fully stateless production setup, pass the access_token from
    /verify-reset-code as a Bearer token and initialise a new Supabase client
    with it here so each request is independently authenticated.
    """
    new_password = data.get("password", "")
    if not new_password or len(new_password) < 8:
        raise HTTPException(
            status_code=400, detail="Password must be at least 8 characters."
        )

    try:
        supabase.auth.update_user({"password": new_password})
        print("✅ PASSWORD UPDATED")
        return {"status": "success", "message": "Password updated successfully."}

    except Exception as e:
        print(f"🔥 UPDATE PASSWORD ERROR: {e}")
        raise HTTPException(
            status_code=400,
            detail="Password update failed. Your reset session may have expired.",
        )
