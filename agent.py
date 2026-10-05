"""Orchestrator. A deterministic pipeline with AI steps inside it (not a free-roaming agent):
the safest design when a wrong action means a bad email to a real company.

  python agent.py setup              # one-time: creates tabs, dropdowns, config
  python agent.py run                # sync -> discover -> draft -> publish -> followups
  python agent.py <stage> [--limit N] [--dry-run]
"""
import argparse
import datetime as dt
import logging
import random
import re
import time

import config
import guardrails as g
from sheet import Store, now

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("agent")

ACTIVE = {"DRAFTED", "SENT", "REPLIED", "FOLLOWUP_DRAFTED"}
OPT_OUT = re.compile(r"\b(no thanks|not interested|unsubscribe|remove me|stop (emailing|contacting)|do not contact)\b", re.I)


def domain_of(lead):
    return (lead["Domain"] or (lead["Email"].split("@")[1] if "@" in lead["Email"] else "")).lower()


def facts_text(lead):
    """Statements only (strip the source URLs) so URL digits can't whitelist numbers."""
    return " ".join(line.split(" | ")[0] for line in lead["Research Facts"].splitlines())


def business_hours():
    n = dt.datetime.now()
    return n.weekday() < 5 and 9 <= n.hour < 17


# ---------------------------------------------------------------- discover
def stage_discover(store, cfg, limit):
    import discovery
    state = {"hunter_calls": 0, "hunter_max": int(cfg["MAX_HUNTER_CALLS_PER_RUN"])}
    dnc, n = store.dnc(), 0
    for lead in store.rows():
        st = lead["Status"].strip().upper()
        if not lead["Company"] or st not in ("", "NEW", "NEEDS_CONTACT"):
            continue
        if st == "NEEDS_CONTACT" and not lead["Email"]:
            continue  # humans: add an email, or set Status back to NEW to retry the search
        if n >= limit:
            break
        n += 1
        row, fields = lead["_row"], {}
        try:
            if lead["Email"]:
                email = lead["Email"].strip().lower()
                fields = {"Email": email, "Email Source": lead["Email Source"] or "team (manual)"}
            else:
                found = discovery.find_contact(lead, state)
                if not found:
                    store.update(row, {"Status": "NEEDS_CONTACT", "Guardrail Result":
                                       "No evidenced contact found. Add an email manually, or set Status to NEW to retry."})
                    store.log(lead["Company"], "no contact found")
                    continue
                email = found["email"]
                fields = {"Email": email, "Email Source": found["source"], "Domain": found["domain"],
                          "Contact Name": lead["Contact Name"] or found["name"],
                          "Contact Title": lead["Contact Title"] or found["title"]}
            problems = g.check_contact(email, dnc)
            if problems:
                fields.update({"Status": "BLOCKED", "Guardrail Result": "Contact blocked: " + "; ".join(problems)})
            else:
                fields.update({"Status": "CONTACT_READY", "Guardrail Result": ""})
            store.update(row, fields)
            store.log(lead["Company"], "contact " + fields["Status"], email)
        except Exception as e:  # one bad row must never stop the batch
            log.exception("discover failed: %s", lead["Company"])
            store.log(lead["Company"], "discover error", e)


# ---------------------------------------------------------------- draft
def stage_draft(store, cfg, limit):
    import llm
    ev, min_score, n = config.EVENT, int(cfg["MIN_JUDGE_SCORE"]), 0
    rows = store.rows()
    active = {domain_of(r) for r in rows if r["Status"] in ACTIVE and domain_of(r)}
    for lead in rows:
        if lead["Status"] != "CONTACT_READY":
            continue
        if n >= limit:
            break
        n += 1
        row = lead["_row"]
        try:
            if domain_of(lead) in active:
                store.update(row, {"Status": "BLOCKED", "Guardrail Result": "Another contact at this company was already emailed."})
                continue
            facts = llm.research_facts(lead)
            if not facts:
                store.update(row, {"Status": "BLOCKED", "Guardrail Result": "No verifiable company facts found; nothing safe to personalize with."})
                continue
            fact_cell = "\n".join(f"{f['statement']} | {f['url']}" for f in facts)
            allowed = config.allowed_text() + " " + " ".join(f["statement"] for f in facts)

            feedback, subject, body, verdict, problems = None, "", "", None, []
            for attempt in range(2):  # one automatic rewrite using the reviewers' feedback
                d = llm.write_email(lead, facts, feedback)
                subject, body = d.subject.strip(), d.body.strip() + "\n\n" + g.FOOTER
                problems = g.check_email(subject, body, lead, allowed, ev["website"])
                if not d.facts_used:
                    problems.append("email does not reference any researched fact")
                verdict = None
                if not problems:
                    verdict = llm.judge(lead, facts, subject, d.body.strip())
                    problems = llm.verdict_problems(verdict, min_score)
                if not problems:
                    break
                feedback = problems
            score = verdict.score if verdict else ""
            if problems:
                result, status = "BLOCKED: " + "; ".join(problems), "BLOCKED"
            else:
                result, status = f"PASS (judge {score}/10): {verdict.summary}", "READY_FOR_REVIEW"
            store.update(row, {"Subject": subject, "Body": body, "Research Facts": fact_cell,
                               "Guardrail Result": result, "Judge Score": score, "Status": status})
            store.log(lead["Company"], "draft " + status, result)
        except Exception as e:
            log.exception("draft failed: %s", lead["Company"])
            store.log(lead["Company"], "draft error", e)


# ---------------------------------------------------------------- publish
def stage_publish(store, cfg, dry):
    import mailer
    svc = None if dry else mailer.service()
    rows, dnc = store.rows(), store.dnc()
    today = dt.date.today().isoformat()
    done_today = sum(1 for r in rows if r["Drafted At"].startswith(today))
    cap, send_mode = int(cfg["DAILY_CAP"]), cfg["SEND_MODE"].lower() == "send"
    for lead in rows:
        appr, st, row = lead["Approval"].strip().lower(), lead["Status"], lead["_row"]
        if appr == "reject" and st not in ACTIVE:
            store.update(row, {"Status": "REJECTED"})
            continue
        if appr != "approve" or st not in ("READY_FOR_REVIEW", "BLOCKED"):
            continue
        if done_today >= cap:
            store.log("-", "daily cap reached", cap)
            break
        # Hard gates re-run on whatever is in the sheet NOW, including teammates' edits.
        others = {domain_of(r) for r in rows if r["Status"] in ACTIVE and r["_row"] != row}
        problems = g.check_contact(lead["Email"], dnc)
        problems += g.check_email(lead["Subject"], lead["Body"], lead,
                                  config.allowed_text() + " " + facts_text(lead), config.EVENT["website"])
        if domain_of(lead) in others:
            problems.append("company already contacted")
        if problems:
            store.update(row, {"Status": "BLOCKED", "Approval": "",
                               "Guardrail Result": "Approval refused: " + "; ".join(problems)})
            store.log(lead["Company"], "approval refused", problems)
            continue
        if dry:
            log.info("[dry-run] would draft for %s", lead["Company"])
            continue
        did, tid = mailer.create_draft(svc, lead["Email"], lead["Subject"], lead["Body"])
        fields = {"Status": "DRAFTED", "Draft ID": did, "Thread ID": tid, "Drafted At": now()}
        if send_mode and business_hours():
            mailer.send_draft(svc, did)
            fields.update({"Status": "SENT", "Sent At": now()})
            store.update(row, fields)
            store.log(lead["Company"], "SENT", lead["Email"])
            time.sleep(random.uniform(45, 120))  # human-like spacing
        else:
            store.update(row, fields)
            store.log(lead["Company"], "Gmail draft created", lead["Email"])
        done_today += 1


# ---------------------------------------------------------------- sync
def stage_sync(store, cfg):
    import mailer
    svc = mailer.service()
    for lead in store.rows():
        if lead["Status"] not in ("DRAFTED", "SENT", "FOLLOWUP_DRAFTED") or not lead["Thread ID"]:
            continue
        row, st = lead["_row"], lead["Status"]
        try:
            t = mailer.thread_state(svc, lead["Thread ID"])
            if t["replied"]:
                f = {"Status": "REPLIED", "Reply Snippet": t["reply_snippet"][:300]}
                if OPT_OUT.search(t["reply_snippet"]):
                    store.add_dnc(lead["Email"], "opted out by reply")
                    f["Reviewer Notes"] = "Auto-added to DoNotContact (opt-out wording in reply)"
                store.update(row, f)
                store.log(lead["Company"], "REPLY", t["reply_snippet"][:200])
            elif t["sent"] and st == "DRAFTED":
                store.update(row, {"Status": "SENT", "Sent At": t["sent_at"].isoformat(timespec="seconds")})
            elif t["sent"] and mailer.bounced(svc, lead["Email"]):
                store.add_dnc(lead["Email"], "bounced")
                store.update(row, {"Status": "BOUNCED"})
                store.log(lead["Company"], "BOUNCE", lead["Email"])
        except Exception as e:
            log.exception("sync failed: %s", lead["Company"])
            store.log(lead["Company"], "sync error", e)


# ---------------------------------------------------------------- follow-ups (never auto-sent)
def stage_followups(store, cfg, dry):
    import llm
    import mailer
    svc = None if dry else mailer.service()
    cutoff = dt.datetime.now() - dt.timedelta(days=int(cfg["FOLLOWUP_DAYS"]))
    for lead in store.rows():
        if lead["Status"] != "SENT" or lead["Followups"] or not lead["Sent At"]:
            continue
        if dt.datetime.fromisoformat(lead["Sent At"]) > cutoff:
            continue
        row = lead["_row"]
        try:
            fu = llm.write_followup(lead, lead["Subject"])
            body = fu.body.strip() + "\n\n" + g.FOOTER
            subject = lead["Subject"] if lead["Subject"].lower().startswith("re:") else "Re: " + lead["Subject"]
            problems = g.check_email(subject, body, lead, config.allowed_text(), config.EVENT["website"], "followup")
            if problems:
                store.update(row, {"Followups": "blocked", "Guardrail Result": "Follow-up blocked: " + "; ".join(problems)})
                continue
            if dry:
                continue
            t = mailer.thread_state(svc, lead["Thread ID"])
            mailer.create_draft(svc, lead["Email"], subject, body, lead["Thread ID"], t["last_msgid"])
            store.update(row, {"Followups": "1", "Status": "FOLLOWUP_DRAFTED"})
            store.log(lead["Company"], "follow-up drafted (review in Gmail)")
        except Exception as e:
            log.exception("followup failed: %s", lead["Company"])
            store.log(lead["Company"], "followup error", e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["setup", "discover", "draft", "publish", "sync", "followups", "run"])
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--dry-run", action="store_true", help="no Gmail changes")
    a = ap.parse_args()
    config.require_filled(need_event=a.command != "setup")
    store = Store()
    if a.command == "setup":
        store.setup()
        log.info("Sheet ready. Add rows to the Leads tab (Company, Tier, Focus; Domain optional).")
        return
    cfg = store.config()
    if cfg["PAUSE"].upper() == "TRUE":
        log.warning("PAUSE is TRUE in the Config tab; exiting.")
        return
    stages = {"sync": lambda: stage_sync(store, cfg),
              "discover": lambda: stage_discover(store, cfg, a.limit),
              "draft": lambda: stage_draft(store, cfg, a.limit),
              "publish": lambda: stage_publish(store, cfg, a.dry_run),
              "followups": lambda: stage_followups(store, cfg, a.dry_run)}
    order = ["sync", "discover", "draft", "publish", "followups"] if a.command == "run" else [a.command]
    for s in order:
        log.info("== %s ==", s)
        stages[s]()


if __name__ == "__main__":
    main()
