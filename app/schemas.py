"""
app/schemas.py
──────────────
All Pydantic request/response models in one place.
Import the model you need in each router — never redefine them elsewhere.
"""

from pydantic import BaseModel, EmailStr
from typing import Optional
from pydantic import Field

# ── Auth ────────────────────────────────────────────────────────────────────

class AdminRegisterData(BaseModel):
    email:    EmailStr
    password: str
    org_name: str


class LoginData(BaseModel):
    email:    EmailStr
    password: str


# ── Feedback ────────────────────────────────────────────────────────────────

class FeedbackData(BaseModel):
    # --- User Identity ---
    user_id: Optional[str] = None
    org_code: str = Field(..., min_length=5, max_length=20)
    
    # --- category IDs ---
    category_id: int 
    department_id: Optional[int] = None
    supervisor_id: Optional[int] = None
    
    # --- The Feedback Content --- Enforces the 500-character limit for security
    feedback_text: str = Field(..., min_length=1, max_length=500) 
    
    is_anonymous: bool = False