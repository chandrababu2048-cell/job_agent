import os
from supabase import create_client
from datetime import datetime

supabase = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_KEY"]
)

TABLE = "job_applications"


def is_already_applied(job_id):
    result = supabase.table(TABLE).select("id").eq("job_id", job_id).execute()
    return len(result.data) > 0


def log_application(job, score, reason, tailored_resume_path, status="applied"):
    record = {
        "job_id": job["id"],
        "title": job["title"],
        "company": job["company"],
        "location": job["location"],
        "url": job["url"],
        "match_score": score,
        "match_reason": reason,
        "tailored_resume_path": tailored_resume_path,
        "status": status,
        "applied_at": datetime.utcnow().isoformat(),
    }
    supabase.table(TABLE).insert(record).execute()
    print(f"[tracker] Logged: {job['company']} — {job['title']} ({status})")


def get_daily_summary():
    today = datetime.utcnow().date().isoformat()
    result = supabase.table(TABLE).select("*").gte("applied_at", today).execute()
    return result.data
