# Hackathon Sponsor Outreach Agent (v2)

Google Sheet = shared database + review UI. Python = pipeline. Gemini = research/writing/review. Gmail = delivery.

```
Sheet row (Company, Focus)
  -> discover   find + verify a contact (public pages / Hunter / teammates)
  -> draft      grounded research -> write -> deterministic checks -> AI judge (1 auto-rewrite)
  -> [HUMAN]    teammate reads in the sheet, edits freely, sets Approval = Approve
  -> publish    re-runs hard checks on the CURRENT text, then creates a Gmail DRAFT (you press send)
  -> sync       detects sent / replied / bounced; opt-outs go to DoNotContact automatically
  -> followups  day 7: Gmail DRAFT only (never auto-sent)
```

## One-time setup (about 30 min)
1. `pip install -r requirements.txt` (Python 3.10+)
2. **Gemini**: key from https://aistudio.google.com -> `export GEMINI_API_KEY=...`
3. **Google Cloud project** (free): enable *Google Sheets API*, *Google Drive API* and *Gmail API*.
   - Service account -> download JSON key as `service_account.json`.
   - OAuth client (type *Desktop app*) -> download as `credentials.json` (Gmail; first run opens a browser).
   - OAuth consent screen: add yourself (and teammates who run it) as test users.
4. Create a blank Google Sheet, **share it (Editor) with the service account's email**, then
   `export SHEET_ID=<id from the sheet URL>`
5. Edit `EVENT` in `config.py`. The AI may state only what is in there. The agent refuses to run until every `YOUR_` placeholder is gone.
6. Optional: `export HUNTER_API_KEY=...` (free plan is small; see notes).
7. `python agent.py setup`, then add rows to the **Leads** tab: Company, Focus (Domain optional but makes discovery more reliable).

## Daily use
`python agent.py run` (or schedule it: cron / GitHub Actions / a teammate's laptop).
Team: review rows with Status `READY_FOR_REVIEW`, fix the Body if needed, set **Approval** to Approve or Reject. Then `python agent.py publish` (or the next `run`) creates Gmail drafts.

Start with `python agent.py run --limit 3` and your own address as a test lead.

## Guardrails (layered)
| Layer | What it blocks |
|---|---|
| Contact | Invalid syntax, free-mail, no MX, DoNotContact list, same company already contacted, any address without evidence |
| Facts | Email may only use researched facts (each tied to a fetched source URL) and `EVENT` data |
| Deterministic | Placeholders, wrong/missing first name, length, banned phrases, shouting, off-domain links, **any number not in the facts**, missing opt-out line |
| AI judge | Separate stronger model; unsupported claims, generic text, tone, risky promises; score must be >= MIN_JUDGE_SCORE |
| Human | Nothing reaches Gmail without Approval; approval is cleared if hard checks fail on the edited text |
| Operational | DAILY_CAP, PAUSE kill switch (Config tab), SEND_MODE=draft default, auto opt-out + bounce handling, follow-ups never auto-sent, full Log tab |

## Notes
- Hunter and Apollo free tiers are small and change; verify limits and API access on their pricing pages. Hunter's free plan was ~50 credits/month in recent listings.
- Business emails of individuals can still be personal data. Prefer role addresses (sponsorship@, university@), follow your university's solicitation policy and local privacy law.
- Models: `GEMINI_MODEL` / `GEMINI_JUDGE_MODEL` env vars; check AI Studio for names available on your free tier.
- Untested against live APIs. Run the 3-lead test first.
