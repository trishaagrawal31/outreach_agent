"""Google Sheet = shared database + review UI for the whole team.
All writes use RAW mode, so AI or scraped text can never execute as a spreadsheet formula."""
import datetime as dt

import gspread
from gspread.utils import rowcol_to_a1

import config

COLS = ["Company", "Tier", "Focus", "Domain", "Contact Name", "Contact Title", "Email", "Email Source",
        "Status", "Approval", "Subject", "Body", "Guardrail Result", "Judge Score", "Research Facts",
        "Reviewer Notes", "Reply Snippet", "Draft ID", "Thread ID", "Drafted At", "Sent At",
        "Followups", "Updated At"]
STATUSES = ["NEW", "NEEDS_CONTACT", "CONTACT_READY", "READY_FOR_REVIEW", "BLOCKED", "REJECTED",
            "DRAFTED", "SENT", "FOLLOWUP_DRAFTED", "REPLIED", "BOUNCED"]
TABS = {"Config": ["Key", "Value"],
        "DoNotContact": ["Email or domain", "Reason", "Added"],
        "Log": ["Time", "Company", "Event", "Detail"]}


def now():
    return dt.datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self):
        self.sh = gspread.service_account(filename=config.SA_FILE).open_by_key(config.SHEET_ID)
        self.ws = self._tab("Leads", COLS)
        self.tabs = {n: self._tab(n, h) for n, h in TABS.items()}
        self.header = self.ws.row_values(1)

    def _tab(self, name, header):
        try:
            return self.sh.worksheet(name)
        except gspread.WorksheetNotFound:
            ws = self.sh.add_worksheet(title=name, rows=1000, cols=max(len(header), 6))
            ws.update(values=[header], range_name="A1")
            ws.freeze(rows=1)
            return ws

    def setup(self):
        cfg = self.tabs["Config"]
        if len(cfg.get_all_values()) <= 1:
            cfg.update(values=[[k, v] for k, v in config.DEFAULTS.items()], range_name="A2")

        def dropdown(col_name, values, strict):
            c = self.header.index(col_name)
            return {"setDataValidation": {
                "range": {"sheetId": self.ws.id, "startRowIndex": 1, "startColumnIndex": c, "endColumnIndex": c + 1},
                "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": v} for v in values]},
                         "showCustomUi": True, "strict": strict}}}

        self.sh.batch_update({"requests": [dropdown("Approval", ["Approve", "Reject"], True),
                                           dropdown("Status", STATUSES, False)]})

    def rows(self):
        vals = self.ws.get_all_values()
        header, out = vals[0], []
        for i, r in enumerate(vals[1:], start=2):
            d = {h: (r[j] if j < len(r) else "") for j, h in enumerate(header)}
            for c in COLS:
                d.setdefault(c, "")
            d["_row"] = i
            out.append(d)
        return out

    def update(self, row, fields):
        fields = {**fields, "Updated At": now()}
        data = [{"range": rowcol_to_a1(row, self.header.index(k) + 1), "values": [[str(v)]]}
                for k, v in fields.items() if k in self.header]
        self.ws.batch_update(data, value_input_option="RAW")

    def config(self):
        cfg = dict(config.DEFAULTS)
        for r in self.tabs["Config"].get_all_values()[1:]:
            if len(r) >= 2 and r[0]:
                cfg[r[0].strip()] = r[1].strip()
        return cfg

    def dnc(self):
        return {r[0].strip().lower() for r in self.tabs["DoNotContact"].get_all_values()[1:] if r and r[0]}

    def add_dnc(self, value, reason):
        self.tabs["DoNotContact"].append_row([value.lower(), reason, now()], value_input_option="RAW")

    def log(self, company, event, detail=""):
        self.tabs["Log"].append_row([now(), company, event, str(detail)[:500]], value_input_option="RAW")
