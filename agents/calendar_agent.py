"""
CalendarAgent — creates Google Calendar events for interviews.
Shares OAuth credentials with GmailAgent (same token file).
"""

import os
from datetime import datetime, timezone, timedelta

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
]


class CalendarAgent:
    def __init__(self):
        self._service = None

    def _ensure_auth(self):
        if self._service:
            return
        creds = None
        token_path = os.environ.get("GMAIL_TOKEN_PATH", "gmail_token.json")
        creds_path = os.environ.get("GMAIL_CREDENTIALS_PATH", "gmail_credentials.json")
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(creds_path):
                    raise FileNotFoundError(
                        f"Gmail/Calendar credentials not found at '{creds_path}'. "
                        "Setup: console.cloud.google.com → APIs & Services → Credentials "
                        "→ OAuth 2.0 Client ID (Desktop)"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(token_path, "w") as f:
                f.write(creds.to_json())
        self._service = build("calendar", "v3", credentials=creds)

    def create_interview_event(self, company: str, title: str,
                                email_snippet: str = "", config: dict = None) -> str:
        """
        Create a Google Calendar event for the interview.
        Attempts to parse date/time from email_snippet.
        Falls back to +3 days from now if parsing fails.
        Returns event HTML link or empty string on failure.
        """
        start_dt = self._parse_datetime(email_snippet, config)
        end_dt = start_dt + timedelta(hours=1)

        event = {
            "summary": f"Interview: {title} @ {company}",
            "description": (
                f"Interview for {title} position at {company}.\n\n"
                f"Recruiter message:\n{email_snippet[:500]}"
            ),
            "start": {"dateTime": start_dt.isoformat(), "timeZone": "America/New_York"},
            "end":   {"dateTime": end_dt.isoformat(),   "timeZone": "America/New_York"},
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email",  "minutes": 1440},
                    {"method": "popup",  "minutes": 30},
                ],
            },
        }

        try:
            self._ensure_auth()
            created = self._service.events().insert(
                calendarId="primary", body=event
            ).execute()
            link = created.get("htmlLink", "")
            print(f"[CalendarAgent] Event created: {link}")
            return link
        except Exception as e:
            print(f"[CalendarAgent] Could not create event: {e}")
            return ""

    def _parse_datetime(self, snippet: str, config: dict = None) -> datetime:
        """Try to extract interview date/time from email snippet using LLM."""
        default = datetime.now(timezone.utc) + timedelta(days=3)
        default = default.replace(hour=14, minute=0, second=0, microsecond=0)

        if not snippet or len(snippet) < 10:
            return default

        try:
            from .base import call_llm_haiku
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            prompt = (
                f"Today is {today}. Extract the interview date and time from this email snippet.\n"
                f"Return ONLY a valid ISO 8601 datetime like 2026-06-28T14:00:00-05:00.\n"
                f"If no date found return: UNKNOWN\n\nSnippet: {snippet[:500]}"
            )
            result = call_llm_haiku(config or {}, prompt, max_tokens=50).strip()
            if result != "UNKNOWN" and "T" in result:
                return datetime.fromisoformat(result.split()[0])
        except Exception:
            pass
        return default
