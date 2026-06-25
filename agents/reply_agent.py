"""
ReplyAgent — scans Gmail for user's YES/NO/EDIT replies to job digest emails.

Reply format (user sends to the job agent digest email):
  YES                    → approve all pending_approval jobs
  YES abc123 def456      → approve specific job IDs (first 8 chars)
  NO abc123              → skip specific job
  EDIT abc123: feedback  → re-tailor job with user's feedback

Scans for emails with subject containing "Re: [Job Agent]" in the last 2 days.
"""

import os
import re
import base64
from datetime import datetime, timezone
from supabase import create_client
from .gmail_agent import GmailAgent
from .tracker_agent import TrackerAgent
from .preference_agent import PreferenceAgent


class ReplyAgent:
    def __init__(self, config, master_resume: str = ""):
        self.config = config
        self.master_resume = master_resume
        self._db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
        self.gmail = GmailAgent()
        self.tracker = TrackerAgent()
        self.prefs = PreferenceAgent()

    def run(self) -> dict:
        """Scan Gmail, parse replies, process actions. Returns action counts."""
        print("\n[ReplyAgent] Scanning Gmail for YES/NO/EDIT replies…")
        counts = {"yes": 0, "no": 0, "edit": 0, "errors": 0}

        try:
            threads = self.gmail.search_replies()
        except Exception as e:
            print(f"[ReplyAgent] Gmail search failed: {e}")
            return counts

        if not threads:
            print("[ReplyAgent] No replies found.")
            return counts

        print(f"[ReplyAgent] {len(threads)} reply thread(s) found")

        for thread in threads:
            tid = thread["id"]
            try:
                # Skip threads already processed
                seen = (self._db.table("processed_reply_threads")
                        .select("thread_id").eq("thread_id", tid)
                        .execute().data)
                if seen:
                    continue

                body = self.gmail.get_reply_body(tid)
                if not body:
                    continue
                actions = self._parse(body)
                for action in actions:
                    self._execute(action, counts)

                # Mark as processed so we never re-run this thread
                self._db.table("processed_reply_threads").upsert(
                    {"thread_id": tid}, on_conflict="thread_id"
                ).execute()
            except Exception as e:
                print(f"[ReplyAgent] Thread {tid}: {e}")
                counts["errors"] += 1

        print(f"[ReplyAgent] Done — YES:{counts['yes']} NO:{counts['no']} EDIT:{counts['edit']}")
        return counts

    # ── Parser ─────────────────────────────────────────────────────────────────

    def _parse(self, body: str) -> list:
        """Extract YES/NO/EDIT instructions from reply body."""
        actions = []
        body_clean = body.strip()

        for line in body_clean.splitlines():
            line = line.strip()
            if not line:
                continue

            # EDIT abc123: feedback text
            edit_match = re.match(r'EDIT\s+([a-zA-Z0-9_-]+)\s*:\s*(.+)', line, re.IGNORECASE)
            if edit_match:
                actions.append({
                    "type": "edit",
                    "job_id": edit_match.group(1).lower(),
                    "feedback": edit_match.group(2).strip(),
                })
                continue

            # NO abc123 def456 ...
            no_match = re.match(r'NO\s+(.*)', line, re.IGNORECASE)
            if no_match:
                ids = no_match.group(1).split()
                for jid in ids:
                    actions.append({"type": "no", "job_id": jid.lower()})
                continue

            # YES abc123 def456 ... (or just YES for all)
            yes_match = re.match(r'YES\s*(.*)', line, re.IGNORECASE)
            if yes_match:
                ids_str = yes_match.group(1).strip()
                if ids_str:
                    for jid in ids_str.split():
                        actions.append({"type": "yes", "job_id": jid.lower()})
                else:
                    actions.append({"type": "yes", "job_id": "ALL"})
                continue

        return actions

    # ── Executor ───────────────────────────────────────────────────────────────

    def _execute(self, action: dict, counts: dict):
        atype = action["type"]
        job_id_prefix = action.get("job_id", "")

        if atype == "yes":
            if job_id_prefix == "ALL":
                pending = self.tracker.get_pending_approval()
                for job in pending:
                    self.tracker.approve_job(job["job_id"])
                    self.prefs.record_decision(job, "yes")
                    counts["yes"] += 1
                    print(f"[ReplyAgent] Approved ALL → {job.get('company','?')} — {job.get('title','?')}")
                # Trigger tailor cycle for all newly approved
                if pending:
                    self._trigger_tailor([j["job_id"] for j in pending])
            else:
                job = self._find_job(job_id_prefix)
                if job:
                    self.tracker.approve_job(job["job_id"])
                    self.prefs.record_decision(job, "yes")
                    counts["yes"] += 1
                    print(f"[ReplyAgent] Approved: {job.get('company','?')}")
                    self._trigger_tailor([job["job_id"]])

        elif atype == "no":
            job = self._find_job(job_id_prefix)
            if job:
                self.tracker.skip_job(job["job_id"])
                self.prefs.record_decision(job, "no")
                counts["no"] += 1
                print(f"[ReplyAgent] Skipped: {job.get('company','?')}")

        elif atype == "edit":
            job = self._find_job(job_id_prefix)
            if job:
                feedback = action.get("feedback", "")
                self.prefs.record_decision(job, "edit", feedback)
                counts["edit"] += 1
                print(f"[ReplyAgent] Re-tailoring {job.get('company','?')} with feedback: {feedback}")
                self._retailor(job, feedback)

    def _find_job(self, id_prefix: str) -> dict | None:
        """Find a job in DB by job_id prefix (first N chars)."""
        try:
            rows = (self._db.table("job_applications")
                    .select("*")
                    .ilike("job_id", f"{id_prefix}%")
                    .limit(1)
                    .execute()
                    .data)
            return rows[0] if rows else None
        except Exception:
            return None

    def _trigger_tailor(self, job_ids: list):
        """Trigger the tailor cycle for specific job IDs via orchestrator."""
        import subprocess, sys
        ids_str = " ".join(job_ids)
        print(f"[ReplyAgent] Triggering tailor for {len(job_ids)} job(s)…")
        subprocess.Popen([sys.executable, "orchestrator.py", "--tailor", "--job-ids", ids_str])

    def _retailor(self, job: dict, feedback: str):
        """Re-tailor a specific job with user feedback and send revised email."""
        try:
            from .tailor_writer_agent import TailorWriterAgent
            from .pdf_agent import PDFAgent
            from .notify_agent import NotifyAgent
            from .research_agent import ResearchAgent

            research = ResearchAgent().run(job.get("company", ""), job.get("title", ""), self.config)
            tw = TailorWriterAgent(self.config, self.master_resume)
            job = tw.run(job, company_research=research, edit_feedback=feedback)

            safe = lambda s: "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:35]
            pdf_path = f"resume/tailored/{safe(job.get('company','co'))}_{safe(job.get('title','role'))}.pdf"
            try:
                PDFAgent().generate(job["tailored_resume"], pdf_path)
                job["resume_pdf_path"] = pdf_path
            except Exception:
                job["resume_pdf_path"] = None

            self.tracker.log(job, status="approved")
            NotifyAgent(self.config).send_job_package(job)
            print(f"[ReplyAgent] Revised package sent for {job.get('company','?')}")
        except Exception as e:
            print(f"[ReplyAgent] Re-tailor error: {e}")
