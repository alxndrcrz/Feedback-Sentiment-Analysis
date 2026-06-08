"""
app/routers/analytics.py
────────────────────────
Admin analytics endpoints:

  GET /api/admin/feedback-history    — full feedback list with filters
  GET /api/admin/sentiment-summary   — stats + breakdown + filtered list
  GET /api/admin/trends              — raw feedback for client-side charting
"""

from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException
from app.database import supabase

router = APIRouter(prefix="/api/admin", tags=["Admin Analytics"])


# ── Shared helper ─────────────────────────────────────────────────────────────

def _resolve_user_name(user_id, is_anonymous: bool) -> str:
    if is_anonymous or not user_id:
        return "Anonymous"
    try:
        res = (
            supabase.table("profiles")
            .select("full_name")
            .eq("id", user_id)
            .single()
            .execute()
        )
        return (res.data or {}).get("full_name", "Unknown")
    except Exception:
        return "Unknown"


def _normalise_row(row: dict, include_user_name: bool = True) -> dict:
    """
    Converts a raw feedback_entries row into the shape the frontend expects.
    Now includes acknowledged, admin_note, followup_text fields.
    """
    user_name = (
        _resolve_user_name(row.get("user_id"), row.get("is_anonymous", False))
        if include_user_name
        else ("Anonymous" if row.get("is_anonymous") else "User")
    )

    def _joined(key):
        val = row.get(key)
        if isinstance(val, dict):
            return val.get("name") or "—"
        return val or "—"

    sentiment  = row.get("sentiment_label") or row.get("sentiment") or "Neutral"
    raw_score  = row.get("sentiment_score") or row.get("confidence") or 0
    if isinstance(raw_score, float) and -1.0 <= raw_score <= 1.0:
        confidence = int(((raw_score + 1) / 2) * 100)
    else:
        confidence = int(raw_score) if raw_score else 55

    return {
        "id":            row.get("id"),
        "feedback_text": row.get("content") or row.get("feedback_text") or "",
        "sentiment":     sentiment,
        "confidence":    confidence,
        "category":      _joined("categories")  if row.get("categories")  else row.get("category",  "—"),
        "department":    _joined("departments") if row.get("departments") else row.get("department", "—"),
        "supervisor":    _joined("supervisors") if row.get("supervisors") else row.get("supervisor", "—"),
        "is_anonymous":  row.get("is_anonymous", False),
        "created_at":    row.get("created_at", ""),
        "user_name":     user_name,
        # ── Acknowledge + follow-up fields ──────────────────────────
        "acknowledged":             row.get("acknowledged", False),
        "admin_note":               row.get("admin_note", ""),
        "acknowledged_at":          row.get("acknowledged_at"),
        "followup_text":            row.get("followup_text", ""),
        "followup_at":              row.get("followup_at"),
        "followup_sentiment":       row.get("followup_sentiment", ""),
        "followup_sentiment_score": row.get("followup_sentiment_score"),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 1. FEEDBACK HISTORY
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/feedback-history")
async def feedback_history(org_code: str):
    if not org_code:
        raise HTTPException(status_code=400, detail="org_code is required.")
    try:
        result = (
            supabase.table("feedback_entries")
            .select("*, categories(name), departments(name), supervisors(name)")
            .eq("org_code", org_code)
            .order("created_at", desc=True)
            .execute()
        )
        rows     = result.data or []
        feedback = [_normalise_row(r) for r in rows]
        print(f"✅ FEEDBACK-HISTORY: org={org_code} | count={len(feedback)}")
        return {"status": "success", "count": len(feedback), "feedback": feedback}
    except HTTPException:
        raise
    except Exception as e:
        print(f"🔥 FEEDBACK-HISTORY ERROR: {e}")
        raise HTTPException(status_code=500, detail="Failed to load feedback history.")


# ══════════════════════════════════════════════════════════════════════════════
# 2. SENTIMENT SUMMARY
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/sentiment-summary")
async def sentiment_summary(org_code: str, days: int = 0):
    if not org_code:
        raise HTTPException(status_code=400, detail="org_code is required.")
    try:
        query = (
            supabase.table("feedback_entries")
            .select("*, categories(name), departments(name), supervisors(name)")
            .eq("org_code", org_code)
            .order("created_at", desc=True)
        )
        if days and days > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            query  = query.gte("created_at", cutoff)

        rows     = query.execute().data or []
        feedback = [_normalise_row(r) for r in rows]
        total    = len(feedback)

        print(f"✅ SENTIMENT-SUMMARY: org={org_code} | days={days} | total={total}")
        return {
            "status": "success",
            "stats": {
                "total":    total,
                "positive": sum(1 for f in feedback if f["sentiment"] == "Positive"),
                "neutral":  sum(1 for f in feedback if f["sentiment"] == "Neutral"),
                "negative": sum(1 for f in feedback if f["sentiment"] == "Negative"),
            },
            "feedback": feedback,
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"🔥 SENTIMENT-SUMMARY ERROR: {e}")
        raise HTTPException(status_code=500, detail="Failed to load sentiment summary.")


# ══════════════════════════════════════════════════════════════════════════════
# 3. TRENDS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/trends")
async def trends(org_code: str):
    if not org_code:
        raise HTTPException(status_code=400, detail="org_code is required.")
    try:
        result = (
            supabase.table("feedback_entries")
            .select("*, categories(name), departments(name), supervisors(name)")
            .eq("org_code", org_code)
            .order("created_at", desc=True)
            .execute()
        )
        rows     = result.data or []
        feedback = [_normalise_row(r, include_user_name=False) for r in rows]
        print(f"✅ TRENDS: org={org_code} | count={len(feedback)}")
        return {"status": "success", "count": len(feedback), "feedback": feedback}
    except HTTPException:
        raise
    except Exception as e:
        print(f"🔥 TRENDS ERROR: {e}")
        raise HTTPException(status_code=500, detail="Failed to load trend data.")