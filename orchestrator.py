"""
Job Agent v2 — Orchestrator
════════════════════════════
Modes:
  python orchestrator.py --hunt          (find + shortlist + email digest)
  python orchestrator.py --tailor        (tailor + apply all approved jobs)
  python orchestrator.py --tailor --job-ids id1 id2 ...  (specific jobs)
  python orchestrator.py --reply-check   (process YES/NO/EDIT email replies)
  python orchestrator.py --followup      (check recruiter replies + follow-ups)
  python orchestrator.py --weekly        (weekly report)
"""

import sys
import os
import yaml
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

with open("config.yaml") as f:
    CONFIG = yaml.safe_load(f)

with open(CONFIG["resume"]["master_md"]) as f:
    MASTER_RESUME = f.read()

MAX_PER_DAY  = CONFIG["agent"]["max_per_day"]
MAX_PER_WEEK = CONFIG["agent"]["max_per_week"]
OUTPUT_DIR   = CONFIG["resume"]["output_dir"]
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs("resume/prep", exist_ok=True)


# ── HUNT ──────────────────────────────────────────────────────────────────────

def run_hunt():
    print("\n" + "═" * 60)
    print("  JOB AGENT v2 — Hunt Cycle")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("═" * 60)

    from agents.tracker_agent  import TrackerAgent
    from agents.hunt_agent     import HuntAgent
    from agents.score_agent    import ScoreAgent
    from agents.research_agent import ResearchAgent
    from agents.preference_agent import PreferenceAgent
    from agents.notify_agent   import NotifyAgent

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

    # Step 1: Hunt all sources
    raw_jobs = HuntAgent(CONFIG).run()

    # Step 2: Keyword score (no LLM)
    scorer    = ScoreAgent(CONFIG, MASTER_RESUME)
    qualified = scorer.run(raw_jobs)

    if not qualified:
        print("\n[Orchestrator] No 4★+ jobs this run.")
        return

    # Step 3: Apply preference learning weights
    prefs = PreferenceAgent()
    for job in qualified:
        job["match_score"] = prefs.adjust_score(job, job["match_score"])
    qualified.sort(key=lambda j: j["match_score"], reverse=True)

    # Step 4: Dedup against already-seen jobs
    new_jobs = [j for j in qualified if not tracker.is_seen(j["id"])]
    print(f"\n[Orchestrator] {len(new_jobs)} new jobs "
          f"({len(qualified)-len(new_jobs)} already tracked)")

    to_shortlist = new_jobs[:slots]
    if not to_shortlist:
        print("[Orchestrator] Nothing new to shortlist.")
        return

    # Step 5: Research each company (cached — won't re-fetch same company)
    researcher = ResearchAgent()
    for job in to_shortlist:
        research = researcher.run(job.get("company", ""), job.get("title", ""), CONFIG)
        job["company_research"] = research

    # Step 6: Log as pending_approval — safe in DB before any action
    for job in to_shortlist:
        tracker.log(job, status="pending_approval")

    print(f"\n[Orchestrator] {len(to_shortlist)} jobs logged as pending_approval")

    # Step 7: Send approval digest email
    try:
        NotifyAgent(CONFIG).send_approval_digest(to_shortlist)
    except Exception as e:
        print(f"[Orchestrator] Digest email error: {e}")

    print(f"\n[Orchestrator] Hunt done. Reply to the digest email with YES/NO/EDIT.")
    print(f"  Or run: python cli.py pending")


# ── TAILOR ────────────────────────────────────────────────────────────────────

def run_tailor(filter_job_ids: list = None):
    print("\n" + "═" * 60)
    print("  JOB AGENT v2 — Tailor Cycle")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("═" * 60)

    from agents.tracker_agent       import TrackerAgent
    from agents.tailor_writer_agent import TailorWriterAgent
    from agents.pdf_agent           import PDFAgent
    from agents.review_agent        import ReviewAgent
    from agents.apply_agent         import ApplyAgent
    from agents.notify_agent        import NotifyAgent
    from agents.preference_agent    import PreferenceAgent
    from agents.base                import QuotaAllExhausted

    tracker = TrackerAgent()
    approved = tracker.get_approved()

    if filter_job_ids:
        approved = [j for j in approved
                    if any(j["job_id"].startswith(fid) for fid in filter_job_ids)]

    if not approved:
        print("[Orchestrator] No approved jobs to process.")
        return

    print(f"[Orchestrator] Processing {len(approved)} approved job(s)…")

    tw        = TailorWriterAgent(CONFIG, MASTER_RESUME)
    pdf_agent = PDFAgent()
    reviewer  = ReviewAgent(CONFIG, MASTER_RESUME)
    applier   = ApplyAgent(CONFIG)
    notifier  = NotifyAgent(CONFIG)
    prefs     = PreferenceAgent()

    auto_applied = 0
    needs_1click = 0
    quota_hit    = False

    for i, job_row in enumerate(approved):
        job = dict(job_row)
        company = job.get("company", "?")
        title   = job.get("title", "?")
        print(f"\n[Orchestrator] {i+1}/{len(approved)}: {title} @ {company}")

        try:
            # 1. Tailor resume + cover letter (1 LLM call)
            job = tw.run(job, company_research=job.get("company_research", ""))

            # 2. Generate PDF
            safe   = lambda s: "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:35]
            pdf_p  = os.path.join(OUTPUT_DIR, f"{safe(company)}_{safe(title)}.pdf")
            try:
                pdf_agent.generate(job["tailored_resume"], pdf_p)
                job["resume_pdf_path"] = pdf_p
            except Exception as e:
                print(f"  [PDF] Warning: {e}")
                job["resume_pdf_path"] = None

            # 3. ATS review
            try:
                job = reviewer.run(job)
            except Exception:
                job["review_passed"] = True
                job["review_notes"]  = "Review skipped"

            # 4. Apply
            result = applier.apply(job, job.get("resume_pdf_path"))
            job["apply_result"]  = result
            job["apply_method"]  = result.get("method", "unknown")
            job["apply_success"] = result.get("success", False)
            job["ats_type"]      = result.get("ats", "unknown")

            # 5. Log to Supabase
            status = "applied" if result.get("success") else "needs_1click"
            tracker.log(job, status=status)
            if result.get("success"):
                tracker.mark_applied(job["job_id"])

            # 6. Record preference decision
            prefs.record_decision(job, "yes")

            # 7. Send notification
            try:
                notifier.send_job_package(job)
            except Exception as e:
                print(f"  [Notify] {e}")

            if result.get("success"):
                auto_applied += 1
            else:
                needs_1click += 1

        except QuotaAllExhausted as e:
            quota_hit = True
            print(f"\n[Orchestrator] ⚠️  All LLM quotas exhausted. Reset at {e.reset_at}")
            print(f"[Orchestrator] {len(approved) - i} job(s) remain approved in DB — "
                  f"will be processed automatically after quota resets.")
            break

        except Exception as e:
            print(f"  [Pipeline] Error for {company}: {e}")
            continue

    print(f"\n{'═'*60}")
    print(f"  Auto-submitted:  {auto_applied}")
    print(f"  Needs 1-click:   {needs_1click} (check email)")
    if quota_hit:
        print(f"  Quota exhausted: remaining jobs safe in DB, resuming at reset")
    print("═" * 60)


# ── REPLY CHECK ───────────────────────────────────────────────────────────────

def run_reply_check():
    print("\n[Orchestrator] Reply-check cycle…")
    try:
        from agents.reply_agent import ReplyAgent
        ReplyAgent(CONFIG, MASTER_RESUME).run()
    except FileNotFoundError as e:
        print(f"[Orchestrator] Gmail not configured: {e}")
    except Exception as e:
        print(f"[Orchestrator] Reply-check error: {e}")


# ── FOLLOW-UP ─────────────────────────────────────────────────────────────────

def run_followup():
    print("\n[Orchestrator] Follow-up cycle…")
    try:
        from agents.followup_agent import FollowUpAgent
        FollowUpAgent(CONFIG).run()
    except FileNotFoundError as e:
        print(f"[Orchestrator] Gmail not configured: {e}")
    except Exception as e:
        print(f"[Orchestrator] Follow-up error: {e}")


# ── WEEKLY ────────────────────────────────────────────────────────────────────

def run_weekly():
    print("\n[Orchestrator] Generating weekly report…")
    from agents.tracker_agent    import TrackerAgent
    from agents.notify_agent     import NotifyAgent
    from agents.preference_agent import PreferenceAgent
    from collections import Counter

    tracker  = TrackerAgent()
    notifier = NotifyAgent(CONFIG)
    prefs    = PreferenceAgent()

    all_jobs = tracker.get_recent(limit=500)
    counts   = Counter(j.get("status", "") for j in all_jobs)

    stats = {
        "applied":    counts.get("applied", 0) + counts.get("awaiting_review", 0),
        "responses":  counts.get("replied", 0) + counts.get("interview", 0),
        "interviews": counts.get("interview", 0),
        "pipeline": {
            "🔔 Pending approval":   counts.get("pending_approval", 0),
            "✅ Approved":           counts.get("approved", 0),
            "📤 Applied (auto)":     counts.get("applied", 0),
            "🖱️  Needs 1-click":    counts.get("needs_1click", 0),
            "💬 Recruiter replied":  counts.get("replied", 0),
            "🎯 Interview":          counts.get("interview", 0),
            "❌ Rejected":           counts.get("rejected", 0),
        },
        "preference_summary": prefs.weekly_summary(),
    }
    notifier.send_weekly_report(stats)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]
    mode = args[0] if args else "--hunt"

    if mode == "--tailor":
        job_ids = None
        if "--job-ids" in args:
            idx = args.index("--job-ids")
            job_ids = args[idx + 1:]
        run_tailor(filter_job_ids=job_ids)
    elif mode == "--reply-check":
        run_reply_check()
    elif mode == "--followup":
        run_followup()
    elif mode == "--weekly":
        run_weekly()
    else:
        run_hunt()
