"""
app/routers/feedback.py
───────────────────────
  POST /api/submit-feedback   — submit + AI sentiment analysis
  GET  /api/my-feedback       — user's history + stats (includes ack + followup)

  Delete endpoint intentionally absent — immutable records by design.
"""

from fastapi import APIRouter, HTTPException, Header
from app.database  import supabase
from app.schemas   import FeedbackData
from app.sentiment import analyze_sentiment

router = APIRouter(prefix="/api", tags=["Feedback"])


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/submit-feedback
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/submit-feedback")
async def submit_feedback(data: FeedbackData):
    if not data.feedback_text.strip():
        raise HTTPException(status_code=400, detail="Feedback text cannot be empty.")
    try:
        label, score, engine_used = analyze_sentiment(data.feedback_text)
        print(f"🤖 NLP ENGINE : {engine_used}\n   TEXT   : {data.feedback_text[:80]}\n   RESULT : {label} ({score})")

        payload = {
            "content":         data.feedback_text,
            "sentiment_label": label,
            "sentiment_score": score,
            "category_id":     data.category_id,
            "department_id":   data.department_id,
            "supervisor_id":   data.supervisor_id,
            "org_code":        data.org_code,
            "is_anonymous":    data.is_anonymous,
            "acknowledged":    False,
        }
        if not data.is_anonymous and data.user_id:
            payload["user_id"] = data.user_id
        else:
            payload["user_id"] = None

        supabase.table("feedback_entries").insert(payload).execute()
        print(f"✅ FEEDBACK SAVED | label={label} | engine={engine_used}")
        return {"status": "success", "sentiment": label, "score": score, "nlp_engine": engine_used}

    except HTTPException:
        raise
    except Exception as e:
        print(f"🔥 FEEDBACK ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/my-feedback
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/my-feedback")
async def get_my_feedback(user_id: str = None, authorization: str = Header(None)):
    resolved_uid = None

    if authorization:
        try:
            token    = authorization.replace("Bearer ", "").strip()
            user_res = supabase.auth.get_user(token)
            if user_res.user:
                resolved_uid = user_res.user.id
        except Exception:
            pass

    if not resolved_uid and user_id:
        resolved_uid = user_id

    if not resolved_uid:
        raise HTTPException(status_code=401, detail="Authentication required.")

    try:
        result = (
            supabase.table("feedback_entries")
            .select("*, categories(name), departments(name), supervisors(name)")
            .eq("user_id", resolved_uid)
            .order("created_at", desc=True)
            .execute()
        )
        rows = result.data or []

        stats = {
            "total":    len(rows),
            "positive": sum(1 for r in rows if r.get("sentiment_label") == "Positive"),
            "neutral":  sum(1 for r in rows if r.get("sentiment_label") == "Neutral"),
            "negative": sum(1 for r in rows if r.get("sentiment_label") == "Negative"),
        }

        feedback_list = []
        for row in rows:
            feedback_list.append({
                "id":            row.get("id"),
                "feedback_text": row.get("content") or "",
                "sentiment":     row.get("sentiment_label", "Neutral"),
                "score":         row.get("sentiment_score", 0) or 0,
                "is_anonymous":  row.get("is_anonymous", False),
                "created_at":    row.get("created_at", ""),
                "category":  (row.get("categories")  or {}).get("name") or "General",
                "department":(row.get("departments") or {}).get("name") or "—",
                "supervisor":(row.get("supervisors") or {}).get("name") or "—",
                # ── Acknowledge + follow-up fields ──────────────────────────
                "acknowledged":             row.get("acknowledged", False),
                "admin_note":               row.get("admin_note", ""),
                "acknowledged_at":          row.get("acknowledged_at"),
                "followup_text":            row.get("followup_text", ""),
                "followup_at":              row.get("followup_at"),
                "followup_sentiment":       row.get("followup_sentiment", ""),
                "followup_sentiment_score": row.get("followup_sentiment_score"),
            })

        return {"status": "success", "stats": stats, "feedback": feedback_list}

    except HTTPException:
        raise
    except Exception as e:
        print(f"🔥 MY-FEEDBACK ERROR: {e}")
        raise HTTPException(status_code=500, detail="Failed to load feedback history.")