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
