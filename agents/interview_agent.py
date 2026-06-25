"""
InterviewPrepAgent — triggered when a recruiter reply is classified as "interview".
Generates a role-specific prep PDF and emails it with calendar event.
"""

import os
from datetime import datetime, timezone
from .base import call_llm_sonnet


class InterviewPrepAgent:
    def __init__(self, config, master_resume: str):
        self.config = config
        self.master_resume = master_resume
        self.output_dir = os.path.join("resume", "prep")
        os.makedirs(self.output_dir, exist_ok=True)

    def run(self, job: dict, recruiter_email_snippet: str = "") -> str:
        """Generate prep guide PDF, email it, attempt calendar event. Returns PDF path."""
        print(f"[InterviewPrepAgent] Preparing for: {job['title']} @ {job['company']}")

        prep_md = self._generate_prep(job)
        pdf_path = self._save_pdf(job, prep_md)
        self._send_email(job, pdf_path, recruiter_email_snippet)
        self._create_calendar_event(job, recruiter_email_snippet)
        return pdf_path

    # ── Generate prep content ──────────────────────────────────────────────────

    def _generate_prep(self, job: dict) -> str:
        prompt = f"""You are a senior technical interview coach. Create a focused interview prep guide.

CANDIDATE RESUME:
{self.master_resume[:3000]}

ROLE: {job['title']} at {job['company']}
JOB DESCRIPTION:
{job.get('description', '')[:2000]}

Generate a prep guide with these EXACT sections:

# Interview Prep: {job['title']} @ {job['company']}

## 15 Likely Interview Questions
(Mix of behavioral, technical, and role-specific. Number them 1-15.)

## Your 6 STAR Stories
(Map your strongest resume achievements to common question themes.
Format each as: **Theme** → Situation → Task → Action → Result with metrics.)

## 3 Technical Topics to Review
(Specific concepts, frameworks, or skills from the JD to brush up on.)

## 2 Smart Questions to Ask Them
(Questions that show strategic thinking about the role.)

## Key Company Signals
(2-3 sentences: what matters to this company based on their JD.)

Keep it concise and actionable. Return clean markdown."""

        try:
            return call_llm_sonnet(self.config, prompt, max_tokens=3000)
        except Exception as e:
            print(f"[InterviewPrepAgent] LLM error: {e}")
            return self._fallback_prep(job)

    def _fallback_prep(self, job: dict) -> str:
        return f"""# Interview Prep: {job['title']} @ {job['company']}

## Key Prep Areas
- Review the job description carefully
- Prepare 3-5 STAR stories from your experience
- Research {job['company']} on LinkedIn and their website
- Prepare questions about the team and role

## General Questions to Expect
1. Tell me about yourself
2. Why do you want to work at {job['company']}?
3. Describe a challenging project you delivered
4. How do you handle tight deadlines?
5. Where do you see yourself in 3 years?

Good luck!"""

    # ── Save PDF ───────────────────────────────────────────────────────────────

    def _save_pdf(self, job: dict, prep_md: str) -> str:
        safe = lambda s: "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:30]
        filename = f"{safe(job.get('company','co'))}_{safe(job.get('title','role'))}_prep.pdf"
        path = os.path.join(self.output_dir, filename)
        try:
            from .pdf_agent import PDFAgent
            PDFAgent().generate(prep_md, path)
        except Exception as e:
            print(f"[InterviewPrepAgent] PDF error: {e} — saving markdown instead")
            path = path.replace(".pdf", ".md")
            with open(path, "w") as f:
                f.write(prep_md)
        return path

    # ── Send email ─────────────────────────────────────────────────────────────

    def _send_email(self, job: dict, pdf_path: str, snippet: str):
        try:
            import resend
            resend.api_key = os.environ["RESEND_API_KEY"]
            notify_email = self.config["notifications"]["gmail_to"]

            html = f"""
<html><body style="font-family:Arial,sans-serif;max-width:640px;margin:auto;padding:20px;">
  <div style="background:#1a1a2e;color:white;padding:22px;border-radius:10px;margin-bottom:16px;">
    <h2 style="margin:0;">🎯 Interview Incoming!</h2>
    <p style="margin:6px 0 0;opacity:.85;">{job['title']} @ {job['company']}</p>
  </div>
  <p style="font-size:14px;">A recruiter replied — your prep guide is attached.</p>
  <div style="background:#f0f4ff;padding:14px;border-radius:8px;font-size:13px;">
    <b>Recruiter message snippet:</b><br>
    <i style="color:#555;">{snippet[:300] if snippet else 'See your inbox.'}</i>
  </div>
  <p style="font-size:13px;margin-top:16px;">Your prep guide includes:
    15 likely questions · 6 STAR stories · 3 topics to review · 2 questions to ask them
  </p>
</body></html>"""

            params = {
                "from": "Job Agent <onboarding@resend.dev>",
                "to": notify_email,
                "subject": f"🎯 Interview Prep: {job['title']} @ {job['company']}",
                "html": html,
            }
            if os.path.exists(pdf_path):
                with open(pdf_path, "rb") as f:
                    import base64
                    params["attachments"] = [{
                        "filename": os.path.basename(pdf_path),
                        "content": base64.b64encode(f.read()).decode(),
                    }]
            resend.Emails.send(params)
            print(f"[InterviewPrepAgent] Prep email sent for {job['company']}")
        except Exception as e:
            print(f"[InterviewPrepAgent] Email error: {e}")

    # ── Calendar event ─────────────────────────────────────────────────────────

    def _create_calendar_event(self, job: dict, snippet: str):
        try:
            from .calendar_agent import CalendarAgent
            CalendarAgent().create_interview_event(
                company=job["company"],
                title=job["title"],
                email_snippet=snippet,
                config=self.config,
            )
        except Exception as e:
            print(f"[InterviewPrepAgent] Calendar: {e}")
