"""
app/utils.py
────────────
Shared helper functions used across multiple routers.
No route definitions here — pure utility logic only.
"""

import re
import secrets
import string
from datetime import datetime
import html

# ── Org Code Generator ──────────────────────────────────────────────────────

def generate_org_code(org_name: str) -> str:
    """
    Builds a unique org code from the first two letters of the org name.
    Example: 'Polytechnic University' → 'PO-X4Z9-2026'
    """
    prefix      = re.sub(r"\W+", "", org_name)[:2].upper() or "OR"
    random_part = "".join(
        secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4)
    )
    return f"{prefix}-{random_part}-2026"


# ── Session Packager ────────────────────────────────────────────────────────

def package_session(session) -> dict | None:
    """
    Converts a Supabase session object to a JSON-serialisable dict
    safe to send to the frontend.
    """
    if not session:
        return None
    return {
        "access_token":  session.access_token,
        "refresh_token": session.refresh_token,
        "expires_at":    session.expires_at,
    }



# ── Date Formatters ─────────────────────────────────────────────────────────

def format_date(iso_string: str) -> str:
    """'2024-01-10T06:30:00Z' → 'Jan 10, 2024'"""
    try:
        dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
        return dt.strftime("%b %-d, %Y")   # Linux/Mac
        # Windows → dt.strftime("%b %#d, %Y")
    except Exception:
        return "Unknown date"


def format_day_label(iso_string: str) -> str:
    """'2024-01-10T06:30:00Z' → 'Jan 10'  (used for chart x-axis labels)"""
    try:
        dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
        return dt.strftime("%b %-d")       # Linux/Mac
        # Windows → dt.strftime("%b %#d")
    except Exception:
        return ""

# ── prevent your Admin Dashboard from being hacked via XSS. ─────────────────────────────────────────────────────────
def sanitize_text(text: str) -> str:
    # 1. Strip leading/trailing whitespace
    # 2. Escape HTML characters to prevent XSS
    return html.escape(text.strip())
