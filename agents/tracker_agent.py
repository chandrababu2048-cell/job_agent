import os
from datetime import datetime, timezone, timedelta
from supabase import create_client

TABLE = "job_applications"

# ── Run this SQL once in your Supabase SQL editor ─────────────────────────────
MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS job_applications (
    id                   BIGSERIAL PRIMARY KEY,
    job_id               TEXT UNIQUE NOT NULL,
    source               TEXT,
    title                TEXT,
    company              TEXT,
    location             TEXT,
    work_type            TEXT,
    url                  TEXT,
    match_score          NUMERIC,
    match_reason         TEXT,
    fit_reasons          TEXT[],
    gaps                 TEXT[],
    confidence           TEXT,
    recommendation       TEXT,
    ats_score            TEXT,
    review_passed        BOOLEAN,
    review_notes         TEXT,
    review_flags         TEXT[],
    tailored_resume_path TEXT,
    status               TEXT DEFAULT 'awaiting_review',
    applied_email        TEXT,
    followup_count       INTEGER DEFAULT 0,
    followup_sent_at     TIMESTAMPTZ,
    applied_at           TIMESTAMPTZ DEFAULT NOW(),
    salary_min           NUMERIC,
    salary_max           NUMERIC
);
CREATE INDEX IF NOT EXISTS idx_job_applications_applied_at ON job_applications (applied_at DESC);
CREATE INDEX IF NOT EXISTS idx_job_applications_status    ON job_applications (status);
"""


class TrackerAgent:
    def __init__(self):
        self.db = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_KEY"],
        )

    # ── Dedup ──────────────────────────────────────────────────────────────────

    def is_seen(self, job_id: str) -> bool:
        res = self.db.table(TABLE).select("id").eq("job_id", job_id).execute()
        return len(res.data) > 0

    # ── Write ──────────────────────────────────────────────────────────────────

    def log(self, job: dict, status: str = "awaiting_review"):
        record = {
            "job_id":               job["id"],
            "source":               job.get("source", ""),
            "title":                job.get("title", ""),
            "company":              job.get("company", ""),
            "location":             job.get("location", ""),
            "work_type":            job.get("work_type", ""),
            "url":                  job.get("url", ""),
            "match_score":          job.get("match_score"),
            "match_reason":         job.get("match_reason", ""),
            "fit_reasons":          job.get("fit_reasons", []),
            "gaps":                 job.get("gaps", []),
            "confidence":           job.get("confidence", ""),
            "recommendation":       job.get("recommendation", ""),
            "review_passed":        job.get("review_passed", True),
            "review_notes":         job.get("review_notes", ""),
            "review_flags":         job.get("review_flags", []),
            "tailored_resume_path": job.get("tailored_resume_path", ""),
            "status":               status,
            "salary_min":           job.get("salary_min"),
            "salary_max":           job.get("salary_max"),
            "applied_at":           datetime.now(timezone.utc).isoformat(),
        }
        self.db.table(TABLE).upsert(record, on_conflict="job_id").execute()
        print(f"[TrackerAgent] Logged: {job.get('company')} — {job.get('title')} ({status})")

    def update_status(self, job_id: str, status: str):
        self.db.table(TABLE).update({"status": status}).eq("job_id", job_id).execute()

    def mark_applied(self, job_id: str, applied_email: str = None):
        update = {
            "status":     "applied",
            "applied_at": datetime.now(timezone.utc).isoformat(),
        }
        if applied_email:
            update["applied_email"] = applied_email
        self.db.table(TABLE).update(update).eq("job_id", job_id).execute()

    def mark_followup_sent(self, job_id: str):
        row = (self.db.table(TABLE)
               .select("followup_count")
               .eq("job_id", job_id)
               .single()
               .execute()
               .data or {})
        new_count = (row.get("followup_count") or 0) + 1
        self.db.table(TABLE).update({
            "followup_count":  new_count,
            "followup_sent_at": datetime.now(timezone.utc).isoformat(),
        }).eq("job_id", job_id).execute()

    # ── Read ───────────────────────────────────────────────────────────────────

    def get_weekly_count(self) -> int:
        """Number of jobs logged since Monday 00:00 UTC this week."""
        today = datetime.now(timezone.utc)
        monday = (today - timedelta(days=today.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        res = (self.db.table(TABLE)
               .select("id", count="exact")
               .gte("applied_at", monday.isoformat())
               .execute())
        return res.count or 0

    def get_daily_count(self) -> int:
        """Number of jobs logged today (UTC)."""
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        res = (self.db.table(TABLE)
               .select("id", count="exact")
               .gte("applied_at", today_start.isoformat())
               .execute())
        return res.count or 0

    def get_daily(self):
        today = datetime.now(timezone.utc).date().isoformat()
        return (self.db.table(TABLE)
                .select("*")
                .gte("applied_at", today)
                .execute()
                .data)

    def get_recent(self, limit: int = 20):
        return (self.db.table(TABLE)
                .select("*")
                .order("applied_at", desc=True)
                .limit(limit)
                .execute()
                .data)

    def get_applied_jobs(self):
        return (self.db.table(TABLE)
                .select("*")
                .eq("status", "applied")
                .execute()
                .data)

    def get_pending_approval(self):
        return (self.db.table(TABLE)
                .select("*")
                .eq("status", "pending_approval")
                .order("match_score", desc=True)
                .execute()
                .data)

    def get_approved(self):
        return (self.db.table(TABLE)
                .select("*")
                .eq("status", "approved")
                .execute()
                .data)

    def approve_job(self, job_id: str):
        self.db.table(TABLE).update({"status": "approved"}).eq("job_id", job_id).execute()
        print(f"[TrackerAgent] ✅ Approved: {job_id}")

    def skip_job(self, job_id: str):
        self.db.table(TABLE).update({"status": "skipped"}).eq("job_id", job_id).execute()
        print(f"[TrackerAgent] ⏭️  Skipped: {job_id}")

    def get_overdue_for_followup(self, cutoff_dt, max_followups: int):
        return (self.db.table(TABLE)
                .select("*")
                .eq("status", "applied")
                .lt("applied_at", cutoff_dt.isoformat())
                .lt("followup_count", max_followups)
                .not_.is_("applied_email", "null")
                .execute()
                .data)
