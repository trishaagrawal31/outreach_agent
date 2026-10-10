"""Deterministic guardrails. No AI involved, so they cannot be talked around.
They run on AI drafts AND on anything a teammate edits in the sheet."""
import re
from urllib.parse import urlparse

import dns.resolver

FOOTER = "If this isn't relevant, just reply 'no thanks' and I won't follow up."

FREEMAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com",
            "proton.me", "protonmail.com", "aol.com", "live.com", "msn.com"}
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
BANNED = ["hope this email finds you well", "revolutionary", "game-changing", "game changing",
          "synergy", "guarantee", "act now", "limited time", "click here", "dear sir",
          "to whom it may concern", "once in a lifetime", "huge opportunity", "i came across your"]
PLACEHOLDER_RE = re.compile(r"\[[^\]]*\]|\{[^}]*\}|<[^>]*>|YOUR_|TODO|lorem ipsum|XXX", re.I)
URL_RE = re.compile(r"https?://[^\s)>\]]+|www\.[^\s)>\]]+")
ALWAYS_OK_NUMBERS = {"15"}  # "15-minute call"


def check_contact(email: str, dnc: set) -> list:
    problems = []
    e = (email or "").strip().lower()
    if not EMAIL_RE.match(e):
        return ["invalid email syntax"]
    domain = e.split("@")[1]
    if domain in FREEMAIL:
        problems.append("free-mail address (not a company contact)")
    if e in dnc or domain in dnc:
        problems.append("on do-not-contact list")
    try:
        dns.resolver.resolve(domain, "MX", lifetime=5)
    except Exception:
        problems.append("domain has no MX record (cannot receive mail)")
    return problems


def _numbers(text: str) -> set:
    return {re.sub(r"[,.]+$", "", n).replace(",", "") for n in re.findall(r"\d[\d,.]*", text)}


def check_email(subject: str, body: str, lead: dict, allowed_text: str,
                website: str, kind: str = "initial") -> list:
    """kind = 'initial' or 'followup'. allowed_text = event facts + verified company facts."""
    p = []
    subject, body = (subject or "").strip(), (body or "").strip()
    if not subject:
        p.append("empty subject")
    if len(subject) > 70:
        p.append("subject longer than 70 chars")
    if FOOTER not in body:
        p.append("opt-out line missing")
    main = body.replace(FOOTER, "").strip()
    if "\n\n" not in main and "\r\n\r\n" not in main:
        p.append("email body is missing paragraph breaks")
    words = len(main.split())
    lo, hi = (60, 150) if kind == "initial" else (8, 70)
    if not lo <= words <= hi:
        p.append(f"body is {words} words (allowed {lo}-{hi})")

    if PLACEHOLDER_RE.search(subject + " " + main):
        p.append("unfilled placeholder / template text found")
    low = (subject + " " + main).lower()
    p += [f"banned phrase: '{b}'" for b in BANNED if b in low]
    if (subject + main).count("!") > 1:
        p.append("too many exclamation marks")

    shouting = [w for w in re.findall(r"\b[A-Z]{5,}\b", subject + " " + main)
                if w not in allowed_text.upper().split() and w not in lead.get("Company", "").upper()]
    if shouting:
        p.append(f"ALL-CAPS words: {shouting[:3]}")

    host = urlparse(website).netloc.lower()
    for u in URL_RE.findall(main):
        if host and host not in u.lower():
            p.append(f"link to non-approved domain: {u[:40]}")

    allowed_nums = _numbers(allowed_text) | ALWAYS_OK_NUMBERS
    stray = _numbers(subject + " " + main) - allowed_nums
    if stray:
        p.append(f"numbers not found in event/company facts: {sorted(stray)[:4]}")

    name = (lead.get("Contact Name") or "").strip()
    if name and name.split()[0].lower() not in main[:80].lower():
        p.append("greeting does not use the contact's first name")
    if kind == "initial":
        first_token = (lead.get("Company") or "").split()[0].lower() if lead.get("Company") else ""
        if first_token and first_token not in low:
            p.append("company name not mentioned")
    return p
