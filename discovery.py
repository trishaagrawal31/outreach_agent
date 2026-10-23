"""Contact discovery. Core rule: an email is only accepted if there is EVIDENCE for it:
  (a) it literally appears on a public web page we fetched, or
  (b) Hunter.io returns it as verified / high-confidence, or
  (c) a teammate typed it into the sheet.
The AI may only CHOOSE among evidenced candidates. It can never invent an address."""
import logging
import re

import requests

import config
import llm
from web import fetch

log = logging.getLogger("discovery")
EMAIL_FIND = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
JUNK_SUFFIX = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")


def _clean_domain(d: str) -> str:
    return d.lower().strip().replace("https://", "").replace("http://", "").removeprefix("www.").strip("/")


def _hunter(domain, state):
    if not config.HUNTER_API_KEY or state.get("hunter_off") or state["hunter_calls"] >= state["hunter_max"]:
        return []
    state["hunter_calls"] += 1
    r = requests.get("https://api.hunter.io/v2/domain-search", timeout=15, params={
        "domain": domain, "limit": 5, "department": "hr,marketing,communication",
        "api_key": config.HUNTER_API_KEY})
    if r.status_code in (401, 402, 403, 429):
        log.warning("Hunter unavailable (HTTP %s); disabling for this run", r.status_code)
        state["hunter_off"] = True
        return []
    r.raise_for_status()
    out = []
    for e in r.json().get("data", {}).get("emails", []):
        conf = e.get("confidence") or 0
        valid = (e.get("verification") or {}).get("status") == "valid"
        if valid or conf >= 90:
            name = f"{e.get('first_name') or ''} {e.get('last_name') or ''}".strip()
            out.append({"email": e["value"].lower(), "name": name, "title": e.get("position") or "",
                        "source": f"hunter.io (confidence {conf})"})
    return out


def find_contact(lead, state):
    """Returns {'email','name','title','source','domain'} or None."""
    company = lead["Company"]
    domain = _clean_domain(lead.get("Domain", "")) or llm.find_domain(company)
    if not domain:
        log.info("%s: could not verify a website domain", company)
        return None

    cands = {}
    text, pages = llm.grounded_pages(
        f"Find public contact details (email addresses) for the university relations, campus recruiting, "
        f"sponsorship, community or partnerships team at {company} ({domain}). Include names and job titles "
        f"of relevant people if they are public.", fallback_domain=domain)
    for url in (f"https://{domain}/contact", f"https://{domain}/"):
        pages.append(fetch(url))
    for url, html in pages:
        for em in EMAIL_FIND.findall(html):
            em = em.lower().strip(".")
            d = em.split("@")[1]
            if em.endswith(JUNK_SUFFIX) or not (d == domain or d.endswith("." + domain)):
                continue
            cands.setdefault(em, {"email": em, "name": "", "title": "", "source": url})

    for h in _hunter(domain, state):
        cands[h["email"]] = {**cands.get(h["email"], {}), **h}  # Hunter adds name/title

    candidates = list(cands.values())[:12]
    if not candidates:
        return None
    choice = llm.choose_contact(company, candidates)
    if choice.index is None or not 0 <= choice.index < len(candidates):
        log.info("%s: no suitable candidate (%s)", company, choice.reason)
        return None
    c = candidates[choice.index]
    c["domain"] = domain
    return c
