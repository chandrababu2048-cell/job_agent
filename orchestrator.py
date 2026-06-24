"""
Job Agent v2 — 30-Day Aggressive Orchestrator
═══════════════════════════════════════════════
Goal: land a job in 30 days via maximum quality applications.

FLOW (runs every 30 min, fully automatic):
  Hunt → Score (4★+) → Tailor + PDF → Apply
    ├── Greenhouse / Lever / Ashby → AUTO-SUBMIT
    └── LinkedIn / Indeed / Unknown → email user 1-click link

Daily 8am UTC → digest of what was applied + pending 1-clicks
Every 7 days  → auto follow-up emails
Every Sunday  → weekly report

Run:
  python orchestrator.py --hunt      (main cycle)
  python orchestrator.py --followup
  python orchestrator.py --weekly
"""

import sys
import os
import yaml
import concurrent.futures
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

from agents.hunt_agent    import HuntAgent
from agents.score_agent   import ScoreAgent
from agents.tailor_agent  import TailorAgent
from agents.writer_agent  import WriterAgent
from agents.review_agent  import ReviewAgent
from agents.pdf_agent     import PDFAgent
from agents.apply_agent   import ApplyAgent
from agents.tracker_agent import TrackerAgent
from agents.notify_agent  import NotifyAgent
from agents.followup_agent import FollowUpAgent

# ── Config ─────────────────────────────────────────────────────────────────────

with open("config.yaml") as f:
    CONFIG = yaml.safe_load(f)

with open(CONFIG["resume"]["master_md"]) as f:
    MASTER_RESUME = f.read()

MAX_PER_DAY  = CONFIG["agent"]["max_per_day"]
MAX_PER_WEEK = CONFIG["agent"]["max_per_week"]
OUTPUT_DIR   = CONFIG["resume"]["output_dir"]
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ── Per-job pipeline ───────────────────────────────────────────────────────────

def _process_job(job, tailor, writer, reviewer, pdf_agent, apply_agent, tracker, notifier):
    """
    Full pipeline for one job:
    Tailor → Cover letter → PDF → Review → Apply → Log → Notify
    Returns enriched job dict or None on failure.
    """
    company = job.get("company", "?")
    title   = job.get("title", "?")

    try:
        # ── 1. Tailor resume + write cover letter (parallel) ──────────────────
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            tailor_f = pool.submit(tailor.run, job.copy())
            write_f  = pool.submit(writer.run,  job.copy())
            job      = tailor_f.result()
            job["cover_letter"] = write_f.result().get("cover_letter", "")

        # ── 2. Generate PDF resume ─────────────────────────────────────────────
        safe_name = f"{company}_{title}".replace(" ", "_").replace("/", "-")[:50]
        pdf_path  = os.path.join(OUTPUT_DIR, f"{safe_name}.pdf")
        try:
            pdf_agent.generate(job.get("tailored_resume", MASTER_RESUME), pdf_path)
            job["resume_pdf_path"] = pdf_path
        except Exception as e:
            print(f"  [PDF] Warning: {e} — will submit without PDF")
            job["resume_pdf_path"] = None

        # ── 3. ATS review ──────────────────────────────────────────────────────
        try:
            job = reviewer.run(job)
        except Exception:
            job["review_passed"] = True
            job["review_notes"]  = "Review skipped"

        # ── 4. Apply ───────────────────────────────────────────────────────────
        apply_result = apply_agent.apply(job, job.get("resume_pdf_path"))
        job["apply_result"]  = apply_result
        job["apply_method"]  = apply_result.get("method", "unknown")
        job["apply_success"] = apply_result.get("success", False)
        job["ats_type"]      = apply_result.get("ats", "unknown")

        # ── 5. Log to Supabase ─────────────────────────────────────────────────
        if apply_result.get("success"):
            tracker.log(job, status="applied")
            tracker.mark_applied(job["id"], applied_email=None)
        else:
            tracker.log(job, status="needs_1click")

        # ── 6. Send notification ───────────────────────────────────────────────
        try:
            notifier.send_job_package(job)
        except Exception as e:
            print(f"  [Notify] {e}")

        return job

    except Exception as e:
        print(f"  [Pipeline] ✗ {company}: {e}")
        return None


# ── Main hunt cycle ────────────────────────────────────────────────────────────

def run_hunt():
    print("\n" + "═" * 60)
    print("  JOB AGENT v2 — 30-Day Hunt Cycle")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("═" * 60)

    tracker = TrackerAgent()
    weekly  = tracker.get_weekly_count()
    daily   = tracker.get_daily_count()

    print(f"\n[Orchestrator] Budget: {daily}/{MAX_PER_DAY} today | {weekly}/{MAX_PER_WEEK} this week")

    if weekly >= MAX_PER_WEEK:
        print("[Orchestrator] Weekly cap reached — resting.")
        return
    if daily >= MAX_PER_DAY:
        print("[Orchestrator] Daily cap reached — see you tomorrow.")
        return

    slots = min(MAX_PER_DAY - daily, MAX_PER_WEEK - weekly)
    print(f"[Orchestrator] Slots available: {slots}\n")

    # ── Step 1: Hunt ───────────────────────────────────────────────────────────
    hunter   = HuntAgent(CONFIG)
    raw_jobs = hunter.run()

    # ── Step 2: Score (4★+ only) ───────────────────────────────────────────────
    scorer    = ScoreAgent(CONFIG, MASTER_RESUME)
    qualified = scorer.run(raw_jobs)

    if not qualified:
        print("\n[Orchestrator] No 4★+ jobs this run.")
        return

    # ── Step 3: Dedup ──────────────────────────────────────────────────────────
    new_jobs = [j for j in qualified if not tracker.is_seen(j["id"])]
    print(f"\n[Orchestrator] {len(new_jobs)} new 4★+ jobs "
          f"({len(qualified)-len(new_jobs)} already tracked)")

    to_process = new_jobs[:slots]
    if not to_process:
        print("[Orchestrator] Nothing new to process.")
        return

    print(f"[Orchestrator] Processing {len(to_process)} jobs now…\n")

    # ── Step 4: Tailor → PDF → Apply (max 3 parallel) ─────────────────────────
    tailor    = TailorAgent(CONFIG, MASTER_RESUME)
    writer    = WriterAgent(CONFIG, MASTER_RESUME)
    reviewer  = ReviewAgent(CONFIG, MASTER_RESUME)
    pdf_agent = PDFAgent()
    apply_agt = ApplyAgent(CONFIG)
    notifier  = NotifyAgent(CONFIG)

    processed = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_process_job, job, tailor, writer, reviewer,
                        pdf_agent, apply_agt, tracker, notifier): job
            for job in to_process
        }
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                processed.append(result)

    # ── Step 5: Summary ────────────────────────────────────────────────────────
    auto_applied  = [j for j in processed if j.get("apply_success")]
    needs_1click  = [j for j in processed if not j.get("apply_success")]

    print(f"\n{'═' * 60}")
    print(f"  ✅ Auto-submitted:  {len(auto_applied)} applications")
    print(f"  🖱️  Needs 1-click:  {len(needs_1click)} (check your email)")
    print(f"  📊 Weekly total:   {tracker.get_weekly_count()}/{MAX_PER_WEEK}")
    print("═" * 60)

    for j in auto_applied:
        s = j.get("stars", "?")
        print(f"  ✅ {'★'*s} {j['company']} — {j['title']} [{j.get('ats_type','')}]")
    for j in needs_1click:
        s = j.get("stars", "?")
        print(f"  🖱️  {'★'*s} {j['company']} — {j['title']} [check email]")
    print()


# ── Follow-up cycle ────────────────────────────────────────────────────────────

def run_followup():
    print("\n[Orchestrator] Follow-up cycle…")
    try:
        FollowUpAgent(CONFIG).run()
    except FileNotFoundError as e:
        print(f"[Orchestrator] Gmail not configured: {e}")
    except Exception as e:
        print(f"[Orchestrator] Follow-up error: {e}")


# ── Weekly report ──────────────────────────────────────────────────────────────

def run_weekly():
    print("\n[Orchestrator] Generating weekly report…")
    tracker  = TrackerAgent()
    notifier = NotifyAgent(CONFIG)

    all_jobs = tracker.get_recent(limit=200)
    from collections import Counter
    counts = Counter(j.get("status","") for j in all_jobs)

    stats = {
        "applied":    counts.get("applied", 0) + counts.get("awaiting_review", 0),
        "responses":  counts.get("replied", 0) + counts.get("interview", 0),
        "interviews": counts.get("interview", 0),
        "pipeline": {
            "🔔 Pending approval":  counts.get("pending_approval", 0),
            "📤 Applied (auto)":    counts.get("applied", 0),
            "🖱️ Needs 1-click":    counts.get("needs_1click", 0),
            "💬 Recruiter replied": counts.get("replied", 0),
            "🎯 Interview":         counts.get("interview", 0),
            "❌ Rejected":          counts.get("rejected", 0),
        },
    }
    notifier.send_weekly_report(stats)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "--hunt"
    if   mode == "--followup": run_followup()
    elif mode == "--weekly":   run_weekly()
    else:                      run_hunt()
