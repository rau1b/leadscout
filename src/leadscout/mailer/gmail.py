"""Gmail API (free): send from your Gmail account and read replies.

One-time setup (no card needed):
1. console.cloud.google.com > new project > enable "Gmail API".
2. OAuth consent screen: External, add your Gmail as a test user.
3. Credentials > Create OAuth client ID > Desktop app > download JSON to data/gmail_credentials.json.
4. Run `leadscout gmail-login`.
"""

import base64
import re
from email.message import EmailMessage
from email.utils import parseaddr

from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from leadscout.config import data_dir

SCOPES = ["https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.readonly"]
API = "https://gmail.googleapis.com/gmail/v1/users/me"
# A reply that starts with "no", or asks to stop. ("No problem, send it" is a yes, so only a leading
# "no" followed by punctuation or the end counts.)
NO_WORDS = re.compile(
    r"^\s*(no|nope|nahi|nahin)\s*([.!,]|$|thanks|thank)|not interested|unsubscribe|remove me|stop (emailing|sending|messaging)|don'?t (email|contact|message)",
    re.I,
)


def _token_path():
    return data_dir() / "gmail_token.json"


def login() -> str:
    creds_file = data_dir() / "gmail_credentials.json"
    if not creds_file.exists():
        raise FileNotFoundError(f"Put your OAuth client file at {creds_file} first (see `leadscout gmail-login --help`).")
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
    creds = flow.run_local_server(port=0)
    _token_path().write_text(creds.to_json(), encoding="utf-8")
    return Gmail().profile_email()


class Gmail:
    def __init__(self):
        if not _token_path().exists():
            raise RuntimeError("Not logged in to Gmail. Run `leadscout gmail-login` first.")
        creds = Credentials.from_authorized_user_file(str(_token_path()), SCOPES)
        if not creds.valid and creds.refresh_token:
            creds.refresh(Request())
            _token_path().write_text(creds.to_json(), encoding="utf-8")
        self.s = AuthorizedSession(creds)

    def profile_email(self) -> str:
        return self.s.get(f"{API}/profile").json()["emailAddress"]

    def send(self, to: str, subject: str, body: str, sender: str, thread_id: str | None = None, in_reply_to: str | None = None) -> dict:
        msg = EmailMessage()
        msg["To"] = to
        msg["From"] = sender
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        msg.set_content(body)
        payload = {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}
        if thread_id:
            payload["threadId"] = thread_id
        resp = self.s.post(f"{API}/messages/send", json=payload)
        resp.raise_for_status()
        return resp.json()  # {"id", "threadId"}

    def message_id_header(self, gmail_id: str) -> str | None:
        r = self.s.get(f"{API}/messages/{gmail_id}", params={"format": "metadata", "metadataHeaders": "Message-ID"})
        for h in r.json().get("payload", {}).get("headers", []):
            if h["name"].lower() == "message-id":
                return h["value"]
        return None

    def incoming(self, thread_id: str, my_address: str) -> list[dict]:
        """Messages in a thread that were not sent by us, with their plain-text body (quoted history removed)."""
        r = self.s.get(f"{API}/threads/{thread_id}", params={"format": "full"})
        if r.status_code != 200:
            return []
        out = []
        for m in r.json().get("messages", []):
            payload = m.get("payload", {})
            headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
            sender = parseaddr(headers.get("from", ""))[1].lower()
            if sender == my_address.lower():
                continue
            bounced = "mailer-daemon" in sender or "postmaster" in sender or "delivery status" in headers.get("subject", "").lower()
            body = strip_quoted(plain_text(payload) or m.get("snippet", ""))
            out.append({
                "id": m["id"],
                "from": headers.get("from", sender),
                "subject": headers.get("subject", ""),
                "body": body,
                "received_ms": int(m.get("internalDate", 0)),
                "kind": "bounced" if bounced else ("opted_out" if NO_WORDS.search(body[:200]) else "replied"),
            })
        return out

    def thread_status(self, thread_id: str, my_address: str) -> str | None:
        """'bounced', 'opted_out', 'replied' or None if nobody answered yet."""
        r = self.s.get(f"{API}/threads/{thread_id}", params={"format": "metadata", "metadataHeaders": ["From", "Subject"]})
        if r.status_code != 200:
            return None
        result = None
        for m in r.json().get("messages", []):
            headers = {h["name"].lower(): h["value"] for h in m.get("payload", {}).get("headers", [])}
            sender = parseaddr(headers.get("from", ""))[1].lower()
            if sender == my_address.lower():
                continue
            if "mailer-daemon" in sender or "postmaster" in sender or "delivery status" in headers.get("subject", "").lower():
                return "bounced"
            snippet = m.get("snippet", "")
            result = "opted_out" if NO_WORDS.search(snippet[:200]) else "replied"
        return result


def plain_text(payload: dict) -> str:
    """The first text/plain part of a Gmail message payload, decoded."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"] + "===").decode("utf-8", "replace")
    for part in payload.get("parts", []) or []:
        text = plain_text(part)
        if text:
            return text
    return ""


QUOTE_START = re.compile(r"^(On .+wrote:|-----Original Message-----|From: .+)$", re.I)


def strip_quoted(text: str) -> str:
    """Keep only what the person wrote, not the quoted email below it."""
    lines = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if QUOTE_START.match(line.strip()):
            break
        if line.lstrip().startswith(">"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()[:4000]
