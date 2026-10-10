"""Central config. Fill in EVENT once: it is the ONLY source of event facts the AI may state."""
import json
import os

SHEET_ID = os.getenv("SHEET_ID", "")
SA_FILE = os.getenv("GOOGLE_SA_FILE", "service_account.json")   # Google service account key
HUNTER_API_KEY = os.getenv("HUNTER_API_KEY", "")                 # optional
WRITER_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")      # check AI Studio for current names
JUDGE_MODEL = os.getenv("GEMINI_JUDGE_MODEL", "gemini-2.5-flash")  # use a model with available free-tier quota

EVENT = {
    "org": "RIT Hackathon",
    "sender_name": "AIRC",
    "sender_title": "Lead Organizer",
    "dates": ", January 20-22 (2027)",
    "attendees": "200 student developers",
    "pitch": "Inter-university hackathon with a focus on AI and emerging technologies.",
    "website": "https://rit-hackathon.example.com",
}

# Defaults for the Config tab in the sheet (teammates can change them there, no redeploy).
DEFAULTS = {
    "PAUSE": "FALSE",               # TRUE = kill switch, every command exits immediately
    "SEND_MODE": "draft",           # draft = Gmail drafts only (recommended). send = auto-send APPROVED rows
    "DAILY_CAP": "15",              # max drafts/sends per day
    "MIN_JUDGE_SCORE": "8",         # AI reviewer must score >= this (1-10)
    "FOLLOWUP_DAYS": "7",
    "MAX_HUNTER_CALLS_PER_RUN": "5",
}


def allowed_text() -> str:
    return json.dumps(EVENT)


def require_filled(need_event: bool = True):
    if not SHEET_ID:
        raise SystemExit("Set SHEET_ID (the long id in your Google Sheet URL).")
    if need_event and "YOUR_" in json.dumps(EVENT):
        raise SystemExit("Fill in EVENT in config.py first (remove every YOUR_ placeholder).")
