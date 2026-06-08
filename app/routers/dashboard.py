"""
app/routers/dashboard.py
────────────────────────
GET /api/admin/dashboard-all — stats, recent feedback, 7-day trend
"""

from collections import defaultdict
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from app.database import supabase

router = APIRouter(prefix="/api", tags=["Admin Dashboard"])


@router.get("/admin/dashboard-all")
async def dashboard_all(org_code: str):
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
        rows = result.data or []

        # ── Stats ─────────────────────────────────────────────────────────────
        total = len(rows)
        pos   = sum(1 for r in rows if r.get("sentiment_label") == "Positive")
        neg   = sum(1 for r in rows if r.get("sentiment_label") == "Negative")
        neu   = sum(1 for r in rows if r.get("sentiment_label") == "Neutral")

        # ── Recent feedback (last 10) ─────────────────────────────────────────
        recent = []
        for item in rows[:10]:
            display_name = "Anonymous"
            if not item.get("is_anonymous") and item.get("user_id"):
                try:
                    user_res = (
                        supabase.table("profiles")
                        .select("full_name")
                        .eq("id", item["user_id"])
                        .single()
                        .execute()
                    )
                    display_name = (user_res.data or {}).get("full_name", "User")
                except Exception:
                    display_name = "User"

            recent.append({
                # id is needed by the Acknowledge button on the dashboard
                "id":           item.get("id"),
                "text":         item.get("content", ""),
                "sentiment":    item.get("sentiment_label", "Neutral"),
                "confidence":   int(((item.get("sentiment_score", 0) + 1) / 2) * 100),
                "category":     (item.get("categories")  or {}).get("name") or "General",
                "department":   (item.get("departments") or {}).get("name") or "—",
                "supervisor":   (item.get("supervisors") or {}).get("name") or "—",
                "date":         item.get("created_at", "")[:10],
                "user_name":    display_name,
                # ── New fields ────────────────────────────────────────────────
                "acknowledged":             item.get("acknowledged", False),
                "admin_note":               item.get("admin_note", ""),
                "followup_text":            item.get("followup_text", ""),
                "followup_sentiment":       item.get("followup_sentiment", ""),
                "followup_sentiment_score": item.get("followup_sentiment_score"),
            })

        # ── 7-day trend ────────────────────────────────────────────────────────
        day_map = {}
        for i in range(6, -1, -1):
            d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            day_map[d] = {"Positive": 0, "Neutral": 0, "Negative": 0}

        for r in rows:
            day = r.get("created_at", "")[:10]
            if day in day_map:
                day_map[day][r.get("sentiment_label", "Neutral")] += 1

        sorted_days = sorted(day_map.keys())

        return {
            "status": "success",
            "stats":  {"total": total, "positive": pos, "negative": neg, "neutral": neu},
            "recent": recent,
            "trends": {
                "labels":   sorted_days,
                "positive": [day_map[d]["Positive"] for d in sorted_days],
                "neutral":  [day_map[d]["Neutral"]  for d in sorted_days],
                "negative": [day_map[d]["Negative"] for d in sorted_days],
            }
        }

    except Exception as e:
        print(f"🔥 DASHBOARD ERROR: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error.")