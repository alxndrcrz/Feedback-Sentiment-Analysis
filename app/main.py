"""
main.py
───────
Application entry point.

Run with:
    python -m uvicorn app.main:app --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth, password, feedback, dashboard, analytics, profile, insights

app = FastAPI(
    title="Feedback Sentiment System API",
    version="2.2",
    description="Backend API for the FeedbackSense employee feedback platform.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(password.router)
app.include_router(feedback.router)
app.include_router(dashboard.router)
app.include_router(analytics.router)
app.include_router(profile.router)
app.include_router(insights.router)


@app.on_event("startup")
async def startup_event():
    from app.database import supabase
    try:
        supabase.table("profiles").select("id", count="exact").limit(1).execute()
        print("✅ Supabase connected.")
    except Exception as e:
        print(f"⚠️  Supabase connection warning: {e}")


@app.get("/api/test-connection", tags=["Health"])
async def test_connection():
    from app.database import supabase
    try:
        supabase.table("profiles").select("id", count="exact").limit(1).execute()
        return {"status": "connected", "message": "Supabase is reachable."}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.get("/", tags=["Health"])
async def root():
    return {
        "message": "FeedbackSense API is running.",
        "version": "2.2",
        "docs":    "http://127.0.0.1:8000/docs",
    }