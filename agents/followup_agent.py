from datetime import datetime, timezone, timedelta
from .base import call_llm_haiku
from .gmail_agent import GmailAgent
from .tracker_agent import TrackerAgent


class FollowUpAgent:
    def __init__(self, config):
        self.config = config
        self.max_followups = config["followup"]["max_followups_per_job"]
        self.days_wait = config["followup"]["days_before_followup"]
        self.gmail = GmailAgent()
        self.tracker = TrackerAgent()

    def run(self):
        print("\n[FollowUpAgent] Starting follow-up cycle...")
        replied, sent = 0, 0

        # 1. Scan inbox for replies to applied jobs
        applied_jobs = self.tracker.get_applied_jobs()
        for job in applied_jobs:
            if self._check_for_reply(job):
                replied += 1

        # 2. Send follow-ups for overdue applications
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.days_wait)
        overdue = self.tracker.get_overdue_for_followup(cutoff, self.max_followups)
        for job in overdue:
            if job.get("applied_email") and self._send_followup(job):
                sent += 1

        print(f"[FollowUpAgent] Done — {replied} replies detected, {sent} follow-ups sent.")

    def _check_for_reply(self, job):
        """Check Gmail inbox for a reply from the company. Update status if found."""
        if not job.get("applied_at"):
            return False
        applied_date = job["applied_at"][:10]
        try:
            snippets = self.gmail.check_for_reply(job["company"], applied_date)
        except Exception as e:
            print(f"[FollowUpAgent] Gmail search error: {e}")
            return False

        if not snippets:
            return False

        # Classify the reply (interview / rejection / info request)
        snippet_text = snippets[0].get("snippet", "") + " " + snippets[0].get("subject", "")
        new_status = self._classify_reply(snippet_text)
        self.tracker.update_status(job["job_id"], new_status)
        print(f"[FollowUpAgent] Reply from {job['company']}: → {new_status}")
        return True

    def _classify_reply(self, text):
        text = text.lower()
        if any(w in text for w in ["interview", "schedule", "call", "meet", "available", "slot"]):
            return "interview"
        if any(w in text for w in ["unfortunately", "not moving forward", "not selected",
                                    "other candidates", "filled", "rejected", "regret"]):
            return "rejected"
        return "replied"

    def _send_followup(self, job):
        """Generate and send a follow-up email for an application."""
        candidate = self.config["candidate"]
        applied_date = job.get("applied_at", "")[:10]

        prompt = f"""Write a short, professional follow-up email for a job application.

Candidate: {candidate['name']}
Applied for: {job['title']} at {job['company']}
Applied on: {applied_date}
Today: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}
Followup number: {job.get('followup_count', 0) + 1}

Rules:
- 3-4 sentences maximum
- Politely ask about the status of the application
- Reiterate genuine interest in the role (one specific reason)
- Offer to provide anything additional
- Professional but warm — not robotic
- Sign with the candidate's full name

Return ONLY the plain text email body (no subject line)."""

        try:
            body_text = call_llm_haiku(self.config, prompt, max_tokens=300)
        except Exception as e:
            print(f"[FollowUpAgent] LLM error: {e}")
            return False

        subject = f"Following Up — {job['title']} Application"
        html_body = "<div style='font-family:Arial,sans-serif;font-size:14px;'>"
        for line in body_text.split("\n"):
            html_body += f"<p>{line}</p>" if line.strip() else ""
        html_body += "</div>"

        try:
            self.gmail.send_email(
                to=job["applied_email"],
                subject=subject,
                html_body=html_body,
                text_body=body_text,
            )
            self.tracker.mark_followup_sent(job["job_id"])
            print(f"[FollowUpAgent] Follow-up sent → {job['company']} ({job['applied_email']})")
            return True
        except Exception as e:
            print(f"[FollowUpAgent] Send error for {job['company']}: {e}")
            return False
