"""
RecruiterOutreachAgent — finds hiring managers for applied jobs and drafts
LinkedIn connection messages. Triggered manually or after auto-submit.

Usage:
  python cli.py outreach            # draft messages for all applied jobs
  python cli.py outreach <job_id>   # draft for one specific job
"""

import os
import json
import hashlib
import requests
from .notify_agent import NotifyAgent


OUTREACH_TABLE = "outreach_drafts"


class RecruiterOutreachAgent:
    def __init__(self, config: dict):
        self.config      = config
        self.candidate   = config.get("candidate", {})
        self.serper_key  = os.environ.get("SERPER_API_KEY", "")
        self.notifier    = NotifyAgent(config)

    def run(self, jobs: list) -> int:
        """Draft LinkedIn outreach messages for a list of applied jobs. Returns count sent."""
        if not jobs:
            print("[OutreachAgent] No jobs to process.")
            return 0

        sent = 0
        all_drafts = []

        for job in jobs:
            company = job.get("company", "")
            title   = job.get("title", "")
            if not company:
                continue

            print(f"[OutreachAgent] Finding hiring manager: {company}…")
            manager = self._find_hiring_manager(company, title)
            message = self._draft_message(job, manager)

            all_drafts.append({
                "company":  company,
                "title":    title,
                "manager":  manager,
                "message":  message,
                "job_url":  job.get("url", ""),
            })

        if all_drafts:
            self._send_digest(all_drafts)
            sent = len(all_drafts)

        print(f"[OutreachAgent] Done — {sent} outreach draft(s) sent to your inbox.")
        return sent

    def _find_hiring_manager(self, company: str, role_title: str) -> dict:
        """Search LinkedIn via Serper to find a relevant hiring manager."""
        if not self.serper_key:
            return {}

        query = (
            f'site:linkedin.com/in "{company}" '
            f'("engineering manager" OR "head of engineering" OR "recruiter" OR '
            f'"talent acquisition" OR "hiring manager" OR "VP engineering")'
        )
        try:
            resp = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": self.serper_key, "Content-Type": "application/json"},
                json={"q": query, "num": 3},
                timeout=10,
            )
            resp.raise_for_status()
            results = resp.json().get("organic", [])
            if not results:
                return {}

            r = results[0]
            raw_title = r.get("title", "")
            snippet   = r.get("snippet", "")
            url       = r.get("link", "")

            # Parse "Name - Title - Company | LinkedIn"
            name, person_title = "", ""
            parts = raw_title.split(" - ")
            if len(parts) >= 2:
                name         = parts[0].strip()
                person_title = parts[1].strip().split(" | ")[0].strip()

            return {
                "name":    name,
                "title":   person_title,
                "url":     url,
                "snippet": snippet,
            }
        except Exception as e:
            print(f"  [OutreachAgent] Serper error: {e}")
            return {}

    def _draft_message(self, job: dict, manager: dict) -> str:
        """Pure-Python template — no LLM cost."""
        name     = self.candidate.get("name", "Chandrababu Naidu Anakapalli")
        first    = name.split()[0]
        company  = job.get("company", "your company")
        role     = job.get("title", "the role")
        mgr_name = manager.get("name", "")
        greeting = f"Hi {mgr_name.split()[0]}," if mgr_name else "Hi,"

        return (
            f"{greeting}\n\n"
            f"I recently applied for the {role} position at {company} and wanted to "
            f"connect directly. I'm a Full-Stack Engineer with 4 years of production "
            f"experience in .NET, Python, and React — most recently building banking APIs "
            f"at Citibank and an autonomous multi-agent AI system on the side.\n\n"
            f"I'm genuinely excited about {company} and would love to chat if you have "
            f"5 minutes. Happy to share more about my background.\n\n"
            f"Best,\n{first}"
        )

    def _send_digest(self, drafts: list):
        """Email all outreach drafts in one digest."""
        to_email = self.config["notifications"]["gmail_to"]

        cards = ""
        for d in drafts:
            mgr = d["manager"]
            mgr_line = ""
            if mgr.get("name"):
                mgr_line = (
                    f"<p style='margin:4px 0;font-size:13px;color:#555'>"
                    f"👤 <b>{mgr['name']}</b> — {mgr.get('title','?')} "
                    f"<a href='{mgr.get('url','')}' style='color:#007bff'>LinkedIn ↗</a></p>"
                )
            else:
                mgr_line = "<p style='color:#999;font-size:12px'>No hiring manager found — send to company page</p>"

            cards += f"""
<div style="border:1px solid #e0e0e0;border-radius:8px;padding:16px;margin-bottom:16px;background:white">
  <h3 style="margin:0 0 4px;font-size:16px">{d['title']} @ {d['company']}</h3>
  {mgr_line}
  <div style="background:#f8f9fa;border-radius:6px;padding:12px;margin-top:10px;
              font-size:13px;white-space:pre-line;line-height:1.7;font-family:monospace">
{d['message']}
  </div>
  <p style="font-size:12px;color:#999;margin:8px 0 0">
    Copy the message above → go to their LinkedIn profile → Connect → Add a note → Paste
  </p>
</div>"""

        html = f"""
<div style="font-family:Arial,sans-serif;max-width:680px;margin:0 auto;padding:20px;color:#222">
  <div style="background:#1a1a2e;color:white;padding:20px 24px;border-radius:8px 8px 0 0">
    <h1 style="margin:0;font-size:20px">📨 Recruiter Outreach Drafts</h1>
    <p style="margin:6px 0 0;opacity:.8;font-size:14px">{len(drafts)} message(s) ready to send</p>
  </div>
  <div style="padding:16px 0">{cards}</div>
  <div style="background:#f0f4ff;padding:12px 16px;border-radius:8px;font-size:13px">
    <b>How to send:</b> Open the LinkedIn profile link → Click <b>Connect</b> →
    Click <b>Add a note</b> → Paste the message → Send. Keep it under 300 chars for LinkedIn.
  </div>
</div>"""

        text = f"RECRUITER OUTREACH DRAFTS — {len(drafts)} jobs\n\n"
        for d in drafts:
            text += f"{'='*50}\n{d['title']} @ {d['company']}\n"
            if d["manager"].get("name"):
                text += f"Manager: {d['manager']['name']} — {d['manager'].get('url','')}\n"
            text += f"\n{d['message']}\n\n"

        import resend
        resend.api_key = os.environ["RESEND_API_KEY"]
        resend.Emails.send({
            "from":    "Job Agent <onboarding@resend.dev>",
            "to":      [to_email],
            "subject": f"📨 Recruiter Outreach — {len(drafts)} draft(s) ready",
            "html":    html,
            "text":    text,
        })
        print(f"[OutreachAgent] Digest sent — {len(drafts)} drafts")
