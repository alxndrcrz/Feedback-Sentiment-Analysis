"""
app/routers/insights.py
───────────────────────
All insight, acknowledge, and follow-up endpoints.
Follow-up text is now also analyzed for sentiment separately.
Original feedback score is NEVER changed — audit trail preserved.
"""

import os, json, re
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Header
from app.database import supabase
from app.utils import sanitize_text
from app.sentiment import analyze_sentiment

router = APIRouter(prefix="/api", tags=["Insights"])


# ── Gemini client ─────────────────────────────────────────────────────────────
def _gemini(prompt: str) -> str:
    try:
        from google import genai
        key = os.getenv("GEMINI_API_KEY", "")
        if not key:
            raise RuntimeError("No API key")
        client = genai.Client(api_key=key)
        res = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        return res.text.strip()
    except Exception as e:
        raise RuntimeError(f"Gemini unavailable: {e}")

def _clean_json(text: str) -> str:
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()

# ── Session guard ─────────────────────────────────────────────────────────────
def _get_uid(authorization: str) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        token = authorization.replace("Bearer ", "").strip()
        res   = supabase.auth.get_user(token)
        if not res.user:
            raise HTTPException(status_code=401, detail="Invalid session.")
        return res.user.id
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Session error.")

# ── Input sanitizer with length cap ──────────────────────────────────────────
def _safe_text(text: str, max_len: int = 300) -> str:
    """Strip, HTML-escape, and cap length. Applied to ALL user text inputs."""
    if not text:
        return ""
    cleaned = sanitize_text(text)   # html.escape() + strip()
    return cleaned[:max_len]


# ══════════════════════════════════════════════════════════════════════════════
# 1. AI NARRATIVE INSIGHTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/admin/ai-insights")
async def ai_insights(org_code: str, days: int = 30):
    if not org_code:
        raise HTTPException(status_code=400, detail="org_code required.")
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        result = (
            supabase.table("feedback_entries")
            .select("*, categories(name), departments(name), supervisors(name)")
            .eq("org_code", org_code)
            .gte("created_at", cutoff)
            .order("created_at", desc=True)
            .execute()
        )
        rows = result.data or []
        if not rows:
            return {"status": "success", "insights": None, "message": "Not enough data yet."}

        total = len(rows)
        pos   = sum(1 for r in rows if r.get("sentiment_label") == "Positive")
        neg   = sum(1 for r in rows if r.get("sentiment_label") == "Negative")
        neu   = sum(1 for r in rows if r.get("sentiment_label") == "Neutral")

        dept_map = {}
        for r in rows:
            d = (r.get("departments") or {}).get("name") or "Unassigned"
            s = r.get("sentiment_label", "Neutral")
            if d not in dept_map:
                dept_map[d] = {"pos": 0, "neg": 0, "neu": 0}
            dept_map[d][{"Positive":"pos","Negative":"neg","Neutral":"neu"}.get(s,"neu")] += 1

        dept_summary = "; ".join(
            f"{d}: {v['pos']} positive, {v['neg']} negative, {v['neu']} neutral"
            for d, v in dept_map.items()
        )
        neg_texts = [r.get("content","") for r in rows if r.get("sentiment_label")=="Negative"][:5]
        pos_texts = [r.get("content","") for r in rows if r.get("sentiment_label")=="Positive"][:3]
        sample    = "\n".join([f'- "{t}"' for t in (neg_texts + pos_texts) if t])

        prompt = f"""
You are an HR analytics AI. Analyze this employee feedback data and write a clear,
actionable 4-5 sentence executive summary for an HR administrator.

Data period: Last {days} days
Total: {total} | Positive: {pos} ({round(pos/total*100)}%) | Negative: {neg} ({round(neg/total*100)}%) | Neutral: {neu} ({round(neu/total*100)}%)
Department breakdown: {dept_summary}
Sample feedback:
{sample}

Structure:
1. Overall sentiment health (1 sentence)
2. Which department needs most attention and why (1 sentence)
3. What employees are most concerned about (1 sentence)
4. What is going well (1 sentence)
5. One specific recommended action (1 sentence)

Be direct, specific, professional. Use actual department names and numbers.
Write as flowing paragraphs — no bullet points or headers.
""".strip()

        try:
            narrative = _gemini(prompt)
            return {
                "status": "success", "insights": narrative,
                "stats":  {"total": total, "positive": pos, "negative": neg, "neutral": neu},
                "engine": "Gemini"
            }
        except Exception:
            top_dept = max(dept_map.items(), key=lambda x: x[1]["neg"], default=(None, None))
            fallback = (
                f"Over the last {days} days, your organization received {total} feedback entries. "
                f"{round(pos/total*100)}% were positive, {round(neg/total*100)}% were negative, "
                f"and {round(neu/total*100)}% were neutral. "
                f"{f'The department with the most negative feedback is {top_dept[0]}.' if top_dept[0] else ''} "
                f"Consider reviewing recent entries to identify recurring concerns."
            )
            return {
                "status": "success", "insights": fallback,
                "stats":  {"total": total, "positive": pos, "negative": neg, "neutral": neu},
                "engine": "fallback"
            }
    except Exception as e:
        print(f"🔥 AI-INSIGHTS ERROR: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate insights.")


# ══════════════════════════════════════════════════════════════════════════════
# 2. KEYWORD THEMES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/admin/keyword-themes")
async def keyword_themes(org_code: str, days: int = 30):
    if not org_code:
        raise HTTPException(status_code=400, detail="org_code required.")
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        result = (
            supabase.table("feedback_entries")
            .select("content, sentiment_label")
            .eq("org_code", org_code)
            .gte("created_at", cutoff)
            .execute()
        )
        rows = result.data or []
        if len(rows) < 3:
            return {"status": "success", "themes": [], "message": "Not enough data."}

        combined = "\n".join(
            [f'[{r.get("sentiment_label","Neutral")}] {r.get("content","")}' for r in rows[:40]]
        )
        prompt = f"""
Analyze these {len(rows)} employee feedback entries and extract the top 8 recurring themes.

Feedback entries:
{combined}

Return ONLY a valid JSON array (no markdown, no explanation):
[
  {{
    "theme": "short theme name (2-4 words)",
    "count": estimated_number_of_entries_about_this,
    "sentiment": "Positive" | "Negative" | "Mixed",
    "example": "short quote from the feedback that best represents this theme"
  }}
]
Rules: workplace-relevant themes only, order by count descending, count >= 2, theme names concise.
""".strip()

        try:
            raw    = _gemini(prompt)
            themes = json.loads(_clean_json(raw))
            return {"status": "success", "themes": themes, "engine": "Gemini"}
        except Exception:
            from collections import Counter
            stopwords = {"the","a","an","is","it","i","my","was","to","and","of","in","for",
                        "that","this","with","have","has","been","very","so","we","our","are","be"}
            words = []
            for r in rows:
                words.extend([
                    w.lower() for w in re.findall(r'\b[a-z]{4,}\b', r.get("content","").lower())
                    if w not in stopwords
                ])
            top = Counter(words).most_common(8)
            return {
                "status": "success",
                "themes": [{"theme": w, "count": c, "sentiment": "Mixed", "example": ""} for w, c in top],
                "engine": "fallback"
            }
    except Exception as e:
        print(f"🔥 KEYWORD-THEMES ERROR: {e}")
        raise HTTPException(status_code=500, detail="Failed to extract themes.")


# ══════════════════════════════════════════════════════════════════════════════
# 3. SUPERVISOR SCORES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/admin/supervisor-scores")
async def supervisor_scores(org_code: str, days: int = 30):
    if not org_code:
        raise HTTPException(status_code=400, detail="org_code required.")
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        result = (
            supabase.table("feedback_entries")
            .select("sentiment_label, supervisors(name), departments(name)")
            .eq("org_code", org_code)
            .gte("created_at", cutoff)
            .not_.is_("supervisor_id", "null")
            .execute()
        )
        rows    = result.data or []
        sup_map = {}
        for r in rows:
            sup  = (r.get("supervisors") or {}).get("name")
            dept = (r.get("departments") or {}).get("name") or "—"
            sent = r.get("sentiment_label", "Neutral")
            if not sup:
                continue
            if sup not in sup_map:
                sup_map[sup] = {"pos": 0, "neg": 0, "neu": 0, "dept": dept}
            sup_map[sup][{"Positive":"pos","Negative":"neg","Neutral":"neu"}.get(sent,"neu")] += 1

        scores = []
        for sup, v in sup_map.items():
            total = v["pos"] + v["neg"] + v["neu"]
            if total == 0:
                continue
            score = round((v["pos"] - v["neg"]) / total, 2)
            scores.append({
                "supervisor": sup, "department": v["dept"],
                "score":      score, "total": total,
                "positive":   v["pos"], "negative": v["neg"], "neutral": v["neu"],
                "status":     "good" if score > 0.3 else "warning" if score > -0.1 else "critical"
            })
        scores.sort(key=lambda x: x["score"], reverse=True)
        return {"status": "success", "supervisors": scores}
    except Exception as e:
        print(f"🔥 SUPERVISOR-SCORES ERROR: {e}")
        raise HTTPException(status_code=500, detail="Failed to load supervisor scores.")


# ══════════════════════════════════════════════════════════════════════════════
# 4. ACKNOWLEDGE FEEDBACK
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/admin/acknowledge")
async def acknowledge_feedback(data: dict, authorization: str = Header(None)):
    """
    Admin marks feedback as acknowledged with an action note.
    Note is sanitized (XSS prevention) and capped at 300 characters.
    """
    uid         = _get_uid(authorization)
    feedback_id = data.get("feedback_id")

    # Sanitize + cap the admin note — prevents XSS and oversized payloads
    note = _safe_text(data.get("note", ""), max_len=300)

    if not feedback_id:
        raise HTTPException(status_code=400, detail="feedback_id required.")

    try:
        supabase.table("feedback_entries").update({
            "acknowledged":    True,
            "admin_note":      note,
            "acknowledged_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", feedback_id).execute()

        print(f"✅ ACKNOWLEDGED: feedback={feedback_id} by admin={uid}")
        return {"status": "success", "message": "Feedback acknowledged."}
    except Exception as e:
        print(f"🔥 ACKNOWLEDGE ERROR: {e}")
        raise HTTPException(status_code=500, detail="Failed to acknowledge feedback.")


# ══════════════════════════════════════════════════════════════════════════════
# 5. EMPLOYEE FOLLOW-UP  (with sentiment analysis)
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/feedback/followup")
async def add_followup(data: dict, authorization: str = Header(None)):
    """
    Employee adds ONE follow-up note to an acknowledged feedback entry.

    Security controls applied here:
    - Session token required (no anonymous follow-ups)
    - Only original submitter can follow up (user_id check)
    - Only possible on acknowledged entries
    - One follow-up per entry maximum
    - Text sanitized with html.escape() to prevent XSS
    - Capped at 300 characters to prevent oversized payloads
    - SQL injection prevented by Supabase parameterized queries

    Sentiment analysis:
    - Follow-up is analyzed separately (Gemini → VADER fallback)
    - Original sentiment and score are NEVER modified
    - If follow-up is Positive, it signals the issue was resolved
    - Admins see: Original sentiment + Follow-up sentiment side by side
    - This is more informative than changing the original score
    """
    uid         = _get_uid(authorization)
    feedback_id = data.get("feedback_id")

    # Sanitize + cap follow-up text
    text = _safe_text(data.get("text", ""), max_len=300)

    if not feedback_id:
        raise HTTPException(status_code=400, detail="feedback_id required.")
    if not text:
        raise HTTPException(status_code=400, detail="Follow-up text cannot be empty.")

    try:
        res   = supabase.table("feedback_entries").select(
            "user_id, is_anonymous, acknowledged, followup_text"
        ).eq("id", feedback_id).single().execute()
        entry = res.data

        if not entry:
            raise HTTPException(status_code=404, detail="Feedback not found.")
        if entry.get("is_anonymous"):
            raise HTTPException(status_code=403, detail="Anonymous feedback cannot have follow-ups.")
        if entry.get("user_id") != uid:
            raise HTTPException(status_code=403, detail="You can only follow up on your own feedback.")
        if not entry.get("acknowledged"):
            raise HTTPException(status_code=400, detail="You can only follow up on acknowledged feedback.")
        if entry.get("followup_text"):
            raise HTTPException(status_code=400, detail="A follow-up has already been submitted for this entry.")

        # Analyze follow-up sentiment separately
        followup_label, followup_score, followup_engine = analyze_sentiment(text)
        print(
            f"🤖 FOLLOW-UP NLP: {followup_engine} | {followup_label} ({followup_score})\n"
            f"   TEXT: {text[:80]}"
        )

        supabase.table("feedback_entries").update({
            "followup_text":            text,
            "followup_at":              datetime.now(timezone.utc).isoformat(),
            "followup_sentiment":       followup_label,
            "followup_sentiment_score": followup_score,
        }).eq("id", feedback_id).execute()

        print(f"✅ FOLLOW-UP SAVED: feedback={feedback_id} by user={uid} | sentiment={followup_label}")
        return {
            "status":             "success",
            "message":            "Follow-up submitted.",
            "followup_sentiment": followup_label,
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"🔥 FOLLOW-UP ERROR: {e}")
        raise HTTPException(status_code=500, detail="Failed to submit follow-up.")


@router.get("/feedback/followup/{feedback_id}")
async def get_followup(feedback_id: int, authorization: str = Header(None)):
    uid = _get_uid(authorization)
    try:
        res   = supabase.table("feedback_entries").select(
            "acknowledged, admin_note, acknowledged_at, followup_text, followup_at, "
            "followup_sentiment, followup_sentiment_score, user_id, is_anonymous"
        ).eq("id", feedback_id).single().execute()
        entry = res.data
        if not entry:
            raise HTTPException(status_code=404, detail="Not found.")
        if entry.get("user_id") != uid and not entry.get("is_anonymous"):
            raise HTTPException(status_code=403, detail="Access denied.")
        return {
            "status":                   "success",
            "acknowledged":             entry.get("acknowledged", False),
            "admin_note":               entry.get("admin_note", ""),
            "acknowledged_at":          entry.get("acknowledged_at"),
            "followup_text":            entry.get("followup_text", ""),
            "followup_at":              entry.get("followup_at"),
            "followup_sentiment":       entry.get("followup_sentiment"),
            "followup_sentiment_score": entry.get("followup_sentiment_score"),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to fetch follow-up.")