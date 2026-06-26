import os
import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
]


class GmailAgent:
    def __init__(self):
        self.service = None  # lazy auth on first use

    def _ensure_auth(self):
        if self.service is None:
            self.service = self._authenticate()

    def _authenticate(self):
        creds = None
        token_path = os.environ.get("GMAIL_TOKEN_PATH", "gmail_token.json")
        creds_path = os.environ.get("GMAIL_CREDENTIALS_PATH", "gmail_credentials.json")

        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    raise ConnectionError(
                        f"Gmail token refresh failed (network issue?): {e}"
                    ) from None
            else:
                if not os.path.exists(creds_path):
                    raise FileNotFoundError(
                        f"Gmail credentials not found at '{creds_path}'.\n"
                        "Setup: console.cloud.google.com → APIs & Services → Credentials "
                        "→ Create OAuth 2.0 Client ID (Desktop) → download as gmail_credentials.json"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(token_path, "w") as f:
                f.write(creds.to_json())

        return build("gmail", "v1", credentials=creds)

    def search_threads(self, query, max_results=20):
        self._ensure_auth()
        result = self.service.users().threads().list(
            userId="me", q=query, maxResults=max_results
        ).execute()
        return result.get("threads", [])

    def get_thread_snippet(self, thread_id):
        thread = self.service.users().threads().get(
            userId="me", id=thread_id, format="metadata",
            metadataHeaders=["From", "Subject", "Date"]
        ).execute()
        messages = thread.get("messages", [])
        if not messages:
            return {}
        headers = {h["name"]: h["value"] for h in messages[0].get("payload", {}).get("headers", [])}
        return {
            "thread_id": thread_id,
            "from": headers.get("From", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "snippet": messages[0].get("snippet", ""),
            "message_count": len(messages),
        }

    def check_for_reply(self, company, applied_after_date):
        """Search inbox for any email from/about a company after a date (YYYY-MM-DD)."""
        company_domain = company.lower().replace(" ", "").replace(",", "").replace(".", "")[:20]
        query = f'after:{applied_after_date} (from:"{company}" OR subject:"{company}")'
        threads = self.search_threads(query, max_results=5)
        snippets = []
        for t in threads:
            try:
                snippets.append(self.get_thread_snippet(t["id"]))
            except Exception:
                pass
        return snippets

    def send_email(self, to, subject, html_body, text_body=None):
        self._ensure_auth()
        msg = MIMEMultipart("alternative")
        msg["To"] = to
        msg["Subject"] = subject
        if text_body:
            msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        self.service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()

    def search_replies(self, max_results: int = 10) -> list:
        """Find user's replies to job agent digest emails (last 2 days)."""
        self._ensure_auth()
        query = 'subject:"Re: [Job Agent]" newer_than:2d in:sent'
        result = self.service.users().threads().list(
            userId="me", q=query, maxResults=max_results
        ).execute()
        return result.get("threads", [])

    def get_reply_body(self, thread_id: str) -> str:
        """Get plain text body of the latest message in a thread."""
        self._ensure_auth()
        thread = self.service.users().threads().get(
            userId="me", id=thread_id, format="full"
        ).execute()
        messages = thread.get("messages", [])
        if not messages:
            return ""
        return self._extract_text(messages[-1])

    def _extract_text(self, message: dict) -> str:
        return self._decode_parts(message.get("payload", {}))

    def _decode_parts(self, payload: dict) -> str:
        mime = payload.get("mimeType", "")
        if mime == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
        if mime.startswith("multipart/"):
            for part in payload.get("parts", []):
                text = self._decode_parts(part)
                if text:
                    return text
        return ""

    def send_email_with_attachment(self, to, subject, html_body, attachment_path=None):
        self._ensure_auth()
        from email.mime.base import MIMEBase
        from email import encoders

        msg = MIMEMultipart("mixed")
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, "html"))

        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            filename = os.path.basename(attachment_path)
            part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
            msg.attach(part)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        self.service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
