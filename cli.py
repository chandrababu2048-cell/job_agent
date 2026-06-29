"""
Job Agent CLI
─────────────────────────────────────────────
python cli.py pending                    # see all jobs waiting for your approval
python cli.py approve <job_id> [...]     # approve jobs → triggers tailoring
python cli.py skip <job_id> [...]        # skip jobs you don't want
python cli.py status                     # full pipeline view
python cli.py mark-applied <job_id>      # mark as applied (starts follow-up timer)
python cli.py edit-resume                # edit your master resume
python cli.py edit-profile               # edit config.yaml
python cli.py run-hunt                   # manual hunt cycle
python cli.py run-tailor                 # manual tailor cycle (process approved)
"""

import os
import sys
import subprocess
import click
import yaml
from dotenv import load_dotenv

load_dotenv()


def _tracker():
    from agents.tracker_agent import TrackerAgent
    return TrackerAgent()


@click.group()
def cli():
    """Job Agent v2 — your personal AI recruiter."""
    pass


# ── Approval workflow ──────────────────────────────────────────────────────────

@cli.command("pending")
def pending():
    """Show all jobs waiting for your YES/NO approval."""
    jobs = _tracker().get_pending_approval()

    if not jobs:
        click.echo("\n  No jobs pending approval right now.\n")
        return

    click.echo("\n" + "═" * 72)
    click.echo("  PENDING APPROVAL — run: python cli.py approve <job_id>")
    click.echo("═" * 72)

    stars_map = {5: "⭐⭐⭐⭐⭐", 4: "⭐⭐⭐⭐☆", 3: "⭐⭐⭐☆☆"}

    for i, j in enumerate(jobs, 1):
        s = j.get("match_score", 0)
        star_n = min(5, max(1, round(s / 2))) if s else j.get("stars", 4)
        stars = stars_map.get(star_n, "⭐⭐⭐⭐☆")
        salary_min = j.get("salary_min")
        salary = f"${int(salary_min):,}+" if salary_min else "Not listed"
        click.echo(f"\n  #{i} {stars}  {j['title']} @ {j['company']}")
        click.echo(f"      📍 {j.get('location','')}  💼 {j.get('work_type','')}  💰 {salary}")
        click.echo(f"      {j.get('recommendation','') or j.get('match_reason','')}")
        click.echo(f"      ID: {j.get('job_id','')[:16]}")

    click.echo("\n" + "─" * 72)
    click.echo("  Approve: python cli.py approve <job_id>")
    click.echo("  Skip:    python cli.py skip <job_id>")
    click.echo("  Approve all: python cli.py approve " +
               " ".join(j.get("job_id","")[:16] for j in jobs))
    click.echo("─" * 72 + "\n")


@cli.command("approve")
@click.argument("job_ids", nargs=-1, required=True)
def approve(job_ids):
    """Approve jobs for tailoring. Agent will tailor resume + cover letter and email you."""
    t = _tracker()
    for job_id in job_ids:
        t.approve_job(job_id)
    click.echo(f"\n  ✅ Approved {len(job_ids)} job(s).")
    click.echo("  Run 'python cli.py run-tailor' to process them now,")
    click.echo("  or wait for the scheduler to pick them up (runs hourly).\n")


@cli.command("skip")
@click.argument("job_ids", nargs=-1, required=True)
def skip(job_ids):
    """Skip jobs you don't want to apply to."""
    t = _tracker()
    for job_id in job_ids:
        t.skip_job(job_id)
    click.echo(f"  ⏭️  Skipped {len(job_ids)} job(s).")


# ── Status & tracking ──────────────────────────────────────────────────────────

@cli.command("status")
@click.option("--limit", default=25, help="Number of recent jobs to show.")
def status(limit):
    """Full pipeline view — all tracked applications and their status."""
    jobs = _tracker().get_recent(limit)

    if not jobs:
        click.echo("No applications tracked yet.")
        return

    icons = {
        "pending_approval": "🔔",
        "approved":         "✅",
        "awaiting_review":  "📋",
        "needs_1click":     "🖱️ ",
        "applied":          "📤",
        "replied":          "💬",
        "interview":        "🎯",
        "rejected":         "❌",
        "skipped":          "⏭️",
        "flagged":          "⚠️",
    }

    click.echo("\n" + "─" * 80)
    click.echo(f"  {'#':<3} {'COMPANY':<22} {'TITLE':<26} {'STATUS':<18} {'★'} {'DATE'}")
    click.echo("─" * 80)

    for i, j in enumerate(jobs, 1):
        icon   = icons.get(j.get("status",""), "•")
        status = j.get("status","")[:16]
        score  = j.get("match_score", 0)
        star_n = min(5, max(1, round(score / 2))) if score else 0
        stars  = "★" * star_n + "☆" * (5 - star_n) if star_n else "—"
        date   = (j.get("applied_at") or "")[:10]
        click.echo(
            f"  {i:<3} {j['company'][:21]:<22} {j['title'][:25]:<26} "
            f"{icon} {status:<16} {stars}  {date}"
        )

    click.echo("─" * 80)

    # Summary counts
    from collections import Counter
    counts = Counter(j.get("status","") for j in jobs)
    click.echo(f"\n  Pending: {counts.get('pending_approval',0)}  "
               f"Approved: {counts.get('approved',0)}  "
               f"Applied: {counts.get('applied',0) + counts.get('awaiting_review',0)}  "
               f"Interviews: {counts.get('interview',0)}  "
               f"Replies: {counts.get('replied',0)}\n")


@cli.command("mark-applied")
@click.argument("job_id")
@click.option("--email", default=None, help="Recruiter email (starts 7-day follow-up timer).")
def mark_applied(job_id, email):
    """Mark a job as applied after you submit. Starts follow-up countdown."""
    _tracker().mark_applied(job_id, applied_email=email)
    click.echo(f"\n  ✅ '{job_id}' marked as applied.")
    if email:
        click.echo(f"  Follow-up will be sent to {email} in 7 days.\n")


@cli.command("open-all")
def open_all():
    """Open all needs_1click job URLs in your browser so you can apply."""
    import subprocess
    tracker = _tracker()
    jobs = tracker.get_recent(limit=100)
    pending = [j for j in jobs if j.get("status") == "needs_1click"]

    if not pending:
        click.echo("\n  No needs_1click jobs. You're all caught up!\n")
        return

    click.echo(f"\n  Opening {len(pending)} job(s) in browser...\n")
    for j in pending:
        url = j.get("url", "")
        if not url:
            continue
        click.echo(f"  🖱️  {j['company']} — {j['title']}")
        click.echo(f"      {url}")
        subprocess.Popen(["open", url])

    click.echo(f"\n  After applying to each, run:")
    click.echo(f"  python cli.py mark-applied <job_id>\n")


# ── LinkedIn setup ─────────────────────────────────────────────────────────────

@cli.command("linkedin-login")
def linkedin_login():
    """Save LinkedIn session for Easy Apply automation (run once)."""
    from agents.linkedin_agent import LinkedInAgent
    import yaml
    with open("config.yaml") as f:
        config = yaml.safe_load(f)
    click.echo("\n  Opening browser — log in to LinkedIn, then press Enter here.\n")
    LinkedInAgent(config).login()
    click.echo("\n  ✅ LinkedIn session saved. Easy Apply is now active.\n")


# ── Resume & config editing ────────────────────────────────────────────────────

@cli.command("edit-resume")
def edit_resume():
    """Open your master resume for editing."""
    with open("config.yaml") as f:
        config = yaml.safe_load(f)
    path   = config["resume"]["master_md"]
    editor = os.environ.get("EDITOR", "open")
    click.echo(f"Opening {path}…")
    subprocess.run([editor, path])


@cli.command("edit-profile")
def edit_profile():
    """Edit config.yaml — job titles, salary floor, preferences."""
    editor = os.environ.get("EDITOR", "open")
    subprocess.run([editor, "config.yaml"])


# ── Recruiter Outreach ─────────────────────────────────────────────────────────

@cli.command("outreach")
@click.argument("job_id", required=False, default=None)
def outreach(job_id):
    """Draft LinkedIn outreach messages for applied jobs and email them to you."""
    tracker = _tracker()
    if job_id:
        jobs = [j for j in tracker.get_recent(limit=200) if j.get("job_id") == job_id]
    else:
        jobs = tracker.get_applied_jobs()

    if not jobs:
        click.echo("\n  No applied jobs found. Apply to some jobs first.\n")
        return

    click.echo(f"\n  Generating outreach for {len(jobs)} job(s)…\n")
    from agents.outreach_agent import RecruiterOutreachAgent
    with open("config.yaml") as f:
        config = yaml.safe_load(f)
    sent = RecruiterOutreachAgent(config).run(jobs)
    click.echo(f"\n  ✅ {sent} outreach draft(s) sent to your inbox.\n")


# ── Retry apply ────────────────────────────────────────────────────────────────

@cli.command("retry-apply")
@click.argument("job_id", required=False, default=None)
def retry_apply(job_id):
    """Re-run auto-submit on needs_1click jobs (Greenhouse/Lever/Ashby/LinkedIn only)."""
    from agents.apply_agent import ApplyAgent
    from agents.tracker_agent import TrackerAgent
    import yaml, glob

    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    tracker  = TrackerAgent()
    applier  = ApplyAgent(config)
    jobs     = tracker.get_recent(limit=200)

    if job_id:
        jobs = [j for j in jobs if j.get("job_id") == job_id]
    else:
        jobs = [j for j in jobs if j.get("status") == "needs_1click"]

    ats_auto = {"greenhouse", "lever", "ashby", "linkedin"}
    eligible = [j for j in jobs if applier.detect_ats(j.get("url","")) in ats_auto]

    if not eligible:
        click.echo("\n  No eligible jobs (needs Greenhouse/Lever/Ashby/LinkedIn URL).\n")
        return

    click.echo(f"\n  Retrying auto-submit for {len(eligible)} job(s)…\n")
    submitted, failed = 0, 0

    for job in eligible:
        ats = applier.detect_ats(job.get("url",""))
        click.echo(f"  → {job['company']} [{ats}]")

        # Find tailored resume PDF if it exists
        safe = lambda s: "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:35]
        pattern = f"resume/tailored/{safe(job.get('company',''))}*.pdf"
        pdfs = glob.glob(pattern)
        pdf_path = pdfs[0] if pdfs else ""

        result = applier.apply(job, pdf_path)
        if result.get("success"):
            tracker.mark_applied(job["job_id"])
            click.echo(f"    ✅ Auto-submitted")
            submitted += 1
        else:
            click.echo(f"    🖱️  Still needs 1-click: {result.get('notes','')}")
            failed += 1

    click.echo(f"\n  Done — {submitted} auto-submitted, {failed} still need manual apply.\n")


# ── Manual triggers ────────────────────────────────────────────────────────────

@cli.command("run-hunt")
def run_hunt():
    """Trigger an immediate hunt cycle → sends approval digest."""
    click.echo("Starting hunt cycle…")
    subprocess.run([sys.executable, "orchestrator.py", "--hunt"])


@cli.command("run-tailor")
def run_tailor():
    """Tailor resumes for all approved jobs → sends package emails."""
    click.echo("Starting tailor cycle…")
    subprocess.run([sys.executable, "orchestrator.py", "--tailor"])


@cli.command("run-followup")
def run_followup():
    """Check inbox for recruiter replies and send follow-ups."""
    click.echo("Starting follow-up cycle…")
    subprocess.run([sys.executable, "orchestrator.py", "--followup"])


if __name__ == "__main__":
    cli()
