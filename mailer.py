"""Gmail via official API (OAuth). Draft, send, and inspect threads."""
import base64
import datetime as dt
import mimetypes
import os
from email.message import EmailMessage
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.compose",
          "https://www.googleapis.com/auth/gmail.readonly"]


def service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            creds = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES).run_local_server(port=0)
        with open("token.json", "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def create_draft(svc, to, subject, body, thread_id=None, in_reply_to=None, attachments=None):
    msg = EmailMessage()
    msg["To"], msg["Subject"] = to, subject
    if in_reply_to:
        msg["In-Reply-To"] = msg["References"] = in_reply_to
    msg.set_content(body)
    for attachment in attachments or []:
        path = Path(attachment)
        if not path.is_file():
            raise FileNotFoundError(f"Email attachment does not exist: {path}")
        content_type, _ = mimetypes.guess_type(path.name)
        maintype, subtype = (content_type or "application/octet-stream").split("/", 1)
        msg.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)
    payload = {"message": {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}}
    if thread_id:
        payload["message"]["threadId"] = thread_id
    d = svc.users().drafts().create(userId="me", body=payload).execute()
    return d["id"], d["message"]["threadId"]


def send_draft(svc, draft_id):
    return svc.users().drafts().send(userId="me", body={"id": draft_id}).execute()


def thread_state(svc, thread_id):
    t = svc.users().threads().get(userId="me", id=thread_id, format="metadata",
                                  metadataHeaders=["Message-ID"]).execute()
    msgs = t.get("messages", [])
    sent = [m for m in msgs if "SENT" in m.get("labelIds", [])]
    replies = [m for m in msgs if not {"SENT", "DRAFT"} & set(m.get("labelIds", []))]
    out = {"sent": bool(sent), "sent_at": None, "replied": bool(replies),
           "reply_snippet": replies[-1].get("snippet", "") if replies else "", "last_msgid": None}
    if sent:
        out["sent_at"] = dt.datetime.fromtimestamp(int(sent[0]["internalDate"]) / 1000)
        headers = sent[-1].get("payload", {}).get("headers", [])
        out["last_msgid"] = next((h["value"] for h in headers if h["name"].lower() == "message-id"), None)
    return out


def bounced(svc, email):
    """Bounce notices arrive as separate mails from mailer-daemon mentioning the address."""
    q = f'from:(mailer-daemon OR postmaster) "{email}" newer_than:30d'  # email already syntax-validated
    return bool(svc.users().messages().list(userId="me", q=q, maxResults=1).execute().get("messages"))
