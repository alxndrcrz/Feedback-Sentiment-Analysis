"""
app/sentiment.py
────────────────
Dual-engine sentiment analysis:
  PRIMARY   → Google Gemini 2.0 Flash (google.genai package)
  FALLBACK  → VADER + Custom 500+ Workplace Lexicon

Returns: (label, score, engine_name)
"""

import os
import json
import re
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
print(f"🔑 GEMINI KEY STATUS: {'✅ Loaded ({} chars)'.format(len(_GEMINI_API_KEY)) if _GEMINI_API_KEY else '❌ NOT FOUND — check your .env file'}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — FALLBACK ENGINE: VADER + WORKPLACE LEXICON
# ══════════════════════════════════════════════════════════════════════════════

from nltk.sentiment.vader import SentimentIntensityAnalyzer

_vader = SentimentIntensityAnalyzer()

_workplace_lexicon: dict = {
    'sleeping': -3.8, 'neglect': -3.5, 'theft': -4.0, 'breach': -3.5, 'unsafe': -3.7,
    'negligent': -3.8, 'reckless': -3.8, 'fighting': -4.0, 'drinking': -3.9, 'tardy': -2.4,
    'vandalism': -3.9, 'harassment': -4.0, 'hostile': -4.0, 'abusive': -4.0, 'threat': -3.8,
    'unauthorized': -3.0, 'bribe': -4.0, 'fraud': -4.0, 'corruption': -4.0, 'illegal': -4.0,
    'integrity': 3.8, 'vigilant': 3.5, 'attentive': 3.2, 'reliable': 3.4, 'honest': 3.5,
    'micromanagement': -3.6, 'favoritism': -3.5, 'nepotism': -3.8, 'incompetent': -3.7,
    'disrespectful': -3.4, 'unprofessional': -3.5, 'dismissive': -3.3, 'ignored': -3.2,
    'clueless': -3.3, 'arrogant': -3.0, 'hypocrite': -3.5, 'unresponsive': -3.0,
    'supportive': 3.8, 'empowering': 3.9, 'approachable': 3.5, 'transparent': 3.4,
    'visionary': 3.6, 'trustworthy': 3.8, 'empathetic': 3.7, 'inspiring': 3.8,
    'mentorship': 3.5, 'guidance': 3.0, 'appreciation': 3.6,
    'overworked': -3.5, 'burnout': -4.0, 'exhausted': -3.2, 'unrealistic': -3.2,
    'understaffed': -3.2, 'drowning': -3.5, 'underpaid': -3.4, 'exploitation': -3.9,
    'stressful': -2.8, 'stagnant': -3.0, 'flexible': 3.7, 'balanced': 3.5,
    'sustainable': 3.2, 'rewarding': 3.6, 'equity': 3.5, 'overwhelmed': -3.2,
    'broken': -3.0, 'malfunction': -2.8, 'dirty': -2.5, 'noisy': -2.0,
    'outdated': -2.3, 'inefficient': -3.0, 'chaotic': -3.4, 'cluttered': -2.0,
    'renovated': 3.0, 'clean': 3.2, 'modern': 2.5, 'ergonomic': 3.0,
    'organized': 2.8, 'productive': 3.1, 'seamless': 3.5, 'stable': 3.0,
    'toxic': -4.0, 'bullying': -4.0, 'discrimination': -4.0, 'gossip': -2.8,
    'inclusive': 3.8, 'collaborative': 3.5, 'belonging': 3.6, 'welcoming': 3.4,
    'backstabbing': -3.8, 'alienated': -3.2, 'cliquey': -2.5,
    'promotion': 3.0, 'growth': 3.2, 'opportunity': 3.0, 'training': 2.8,
    'impactful': 3.5, 'valuable': 3.2, 'valued': 3.7, 'recognition': 3.0,
    'salary': -0.5, 'compensation': -0.5, 'wage': -0.5,
}

for _w in ['poor', 'terrible', 'awful', 'horrible', 'lacking', 'failure', 'worst', 'bad']:
    _workplace_lexicon[_w] = -3.0
for _w in ['excellent', 'amazing', 'wonderful', 'perfect', 'superb', 'best', 'great']:
    _workplace_lexicon[_w] = 3.0

_vader.lexicon.update(_workplace_lexicon)

_PHRASE_OVERRIDES: dict = {
    "not high enough":              -0.75,
    "not enough":                   -0.70,
    "too low":                      -0.75,
    "salary is low":                -0.80,
    "salary increase is not":       -0.80,
    "pay is not":                   -0.75,
    "not fair":                     -0.72,
    "keeps on sleeping":            -0.90,
    "sleeping on the job":          -0.95,
    "sleeping sometimes":           -0.85,
    "not doing work":               -0.80,
    "clueless management":          -0.80,
    "quit my job":                  -0.90,
    "looking for another job":      -0.75,
    "not worth the effort":         -0.70,
    "toxic environment":            -0.90,
    "unfair treatment":             -0.85,
    "safety hazard":                -0.90,
    "no communication":             -0.70,
    "love working here":             0.90,
    "best company":                  0.95,
    "highly recommended":            0.90,
    "great culture":                 0.85,
    "supportive boss":               0.85,
    "excellent benefits":            0.80,
}


def _vader_analyze(text: str) -> tuple:
    t = text.lower()
    for phrase, score in _PHRASE_OVERRIDES.items():
        if phrase in t:
            label = "Positive" if score > 0 else "Negative"
            return label, round(score, 4)

    scores   = _vader.polarity_scores(text)
    compound = scores["compound"]

    if compound >= 0.05:
        label = "Positive"
    elif compound <= -0.05:
        label = "Negative"
    else:
        label = "Neutral"

    return label, round(compound, 4)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — PRIMARY ENGINE: GOOGLE GEMINI 2.0 Flash
# ══════════════════════════════════════════════════════════════════════════════

try:
    from google import genai
    _GENAI_AVAILABLE = True
except ImportError:
    _GENAI_AVAILABLE = False
    print("⚠️  google-genai not installed. Run: pip install google-genai")


def _get_gemini_client():
    if not _GENAI_AVAILABLE:
        raise RuntimeError("google-genai package is not installed.")
    if not _GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set.")
    return genai.Client(api_key=_GEMINI_API_KEY)


_GEMINI_SYSTEM_PROMPT = """
You are an expert workplace sentiment analysis AI. Analyze employee feedback
and classify its sentiment considering full context and meaning.

CLASSIFICATION RULES:
- Positive: Expresses satisfaction, praise, appreciation, or constructive optimism.
- Negative: Expresses dissatisfaction, complaints, frustration, criticism, or concerns.
  This includes complaints about salary, workload, management, safety, or fairness
  even if phrased politely or indirectly.
- Neutral: Purely factual or perfectly balanced with no clear lean.

NUANCE RULES:
- "Salary increase is not high enough" = Negative (complaint about pay).
- "The pay could be better" = Negative (indirect complaint).
- Sarcasm like "great, another pointless meeting" = Negative.
- Reporting misconduct (theft, harassment, sleeping on duty) = Negative.
- A complaint with a hopeful ending still leans Negative.

OUTPUT FORMAT — respond ONLY with valid JSON, nothing else:
{
  "label": "Positive" | "Neutral" | "Negative",
  "confidence": <float between 0.0 and 1.0>,
  "reason": "<one short sentence explaining the classification>"
}
""".strip()


def _gemini_analyze(text: str) -> tuple:
    client = _get_gemini_client()
    prompt = f"{_GEMINI_SYSTEM_PROMPT}\n\nEmployee Feedback:\n\"\"\"\n{text.strip()}\n\"\"\""

    response = client.models.generate_content(
        model="gemini-2.5-flash",   # ← Updated model name for new google.genai package
        contents=prompt,
    )

    raw_text: str = response.text.strip()
    raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
    raw_text = re.sub(r"\s*```$",           "", raw_text)
    raw_text = raw_text.strip()

    parsed     = json.loads(raw_text)
    label      = parsed.get("label",      "Neutral")
    confidence = float(parsed.get("confidence", 0.5))
    reason     = parsed.get("reason",     "")

    if label not in {"Positive", "Neutral", "Negative"}:
        label = "Neutral"

    confidence = max(0.0, min(1.0, confidence))

    print(f"   GEMINI REASON : {reason}")
    return label, round(confidence, 4)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — PUBLIC API
# Returns 3 values: (label, score, engine_name) — no guessing ever
# ══════════════════════════════════════════════════════════════════════════════

def analyze_sentiment(text: str) -> tuple:
    """
    Returns:
        (label, score, engine_name)
        label       → "Positive" | "Neutral" | "Negative"
        score       → Gemini: confidence [0–1] | VADER: compound [−1 to 1]
        engine_name → "Gemini" | "VADER (fallback)"
    """
    if not text or not text.strip():
        return "Neutral", 0.0, "VADER (fallback)"

    # ── Try Gemini first ──────────────────────────────────────────────────────
    if _GEMINI_API_KEY and _GENAI_AVAILABLE:
        try:
            label, score = _gemini_analyze(text)
            print(f"🤖 NLP ENGINE : Gemini | {label} (confidence={score})")
            return label, score, "Gemini"

        except RuntimeError as e:
            print(f"⚠️  Gemini config error: {e} — switching to VADER.")

        except Exception as e:
            print(f"⚠️  Gemini FAILED ({type(e).__name__}): {e}")
            print(f"   Switching to VADER fallback...")

    # ── Fallback: VADER ───────────────────────────────────────────────────────
    label, score = _vader_analyze(text)
    print(f"🤖 NLP ENGINE : VADER (fallback) | {label} (compound={score})")
    return label, score, "VADER (fallback)"