from datetime import datetime, timezone, timedelta
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

        snippet_text = snippets[0].get("snippet", "") + " " + snippets[0].get("subject", "")
        new_status = self._classify_reply(snippet_text)
        self.tracker.update_status(job["job_id"], new_status)
        print(f"[FollowUpAgent] Reply from {job['company']}: → {new_status}")

        if new_status == "interview":
            self._trigger_interview_prep(job, snippet_text)

        return True

    def _classify_reply(self, text):
        text = text.lower()
        if any(w in text for w in ["interview", "schedule", "call", "meet", "available", "slot"]):
            return "interview"
        if any(w in text for w in ["unfortunately", "not moving forward", "not selected",
                                    "other candidates", "filled", "rejected", "regret"]):
            return "rejected"
        return "replied"

    def _trigger_interview_prep(self, job: dict, snippet: str):
        try:
            import yaml
            with open("config.yaml") as f:
                config = yaml.safe_load(f)
            with open(config["resume"]["master_md"]) as f:
                master_resume = f.read()
            from .interview_agent import InterviewPrepAgent
            InterviewPrepAgent(config, master_resume).run(job, snippet)
        except Exception as e:
            print(f"[FollowUpAgent] Interview prep error: {e}")

    def _send_followup(self, job):
        candidate = self.config["candidate"]
        name = candidate["name"]
        title = job["title"]
        company = job["company"]
        applied_date = job.get("applied_at", "")[:10]
        count = job.get("followup_count", 0) + 1

        if count == 1:
            body_text = (
                f"Hi,\n\n"
                f"I wanted to follow up on my application for the {title} role at {company}, "
                f"submitted on {applied_date}. I remain very interested in the opportunity and "
                f"would love to learn if there are any updates on the hiring timeline.\n\n"
                f"Please let me know if you need any additional information from my end.\n\n"
                f"Best regards,\n{name}"
            )
        else:
            body_text = (
                f"Hi,\n\n"
                f"I wanted to check in once more regarding my application for the {title} role at "
                f"{company}. I understand you may be reviewing many candidates and I appreciate "
                f"your time. I'm still very enthusiastic about this position and the team.\n\n"
                f"Happy to provide references or any additional materials if helpful.\n\n"
                f"Best regards,\n{name}"
            )

        subject = f"Following Up — {title} Application"
        html_body = "<div style='font-family:Arial,sans-serif;font-size:14px;line-height:1.6'>"
        for line in body_text.split("\n"):
            html_body += f"<p style='margin:4px 0'>{line}</p>" if line.strip() else "<br>"
        html_body += "</div>"

        try:
            self.gmail.send_email(
                to=job["applied_email"],
                subject=subject,
                html_body=html_body,
                text_body=body_text,
            )
            self.tracker.mark_followup_sent(job["job_id"])
            print(f"[FollowUpAgent] Follow-up #{count} sent → {company} ({job['applied_email']})")
            return True
        except Exception as e:
            print(f"[FollowUpAgent] Send error for {company}: {e}")
            return False
