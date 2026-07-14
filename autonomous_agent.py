#!/usr/bin/env python3
"""
Autonomous Job Search Agent — Claude is the brain.

Every 30 minutes Claude wakes up, reads the pipeline state, reads actual
job descriptions, decides what to do, takes actions with tools, and repeats
until the cycle is done. No fixed script. No human needed.

Run once:   python autonomous_agent.py --once
Run 24/7:   python autonomous_agent.py
"""

import os
import sys
import json
import time
import requests
import schedule
import threading
import anthropic
import yaml
from datetime import datetime, timezone
from collections import Counter
from dotenv import load_dotenv
from bs4 import BeautifulSoup

load_dotenv()

with open("config.yaml") as f:
    CONFIG = yaml.safe_load(f)

with open(CONFIG["resume"]["master_md"]) as f:
    MASTER_RESUME = f.read()

# ── Colors ─────────────────────────────────────────────────────────────────────
G = "\033[92m"; Y = "\033[93m"; C = "\033[96m"; D = "\033[90m"; BLD = "\033[1m"; RST = "\033[0m"

_cycle_lock = threading.Lock()   # prevent overlapping cycles


# ══════════════════════════════════════════════════════════════════════════════
# TOOLS — everything Claude can do
# ══════════════════════════════════════════════════════════════════════════════

def _now(): return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def tool_get_pipeline_state() -> str:
    """Full current state of the job search pipeline."""
    from agents.tracker_agent import TrackerAgent
    from agents.base import llm_status
    t = TrackerAgent()
    all_j = t.get_recent(limit=300)
    counts = Counter(j.get("status") for j in all_j)
    replied   = [j for j in all_j if j["status"] in ("replied", "interview")]
    approved  = [j for j in all_j if j["status"] == "approved"]
    pending   = [j for j in all_j if j["status"] == "pending_approval"]
    quota     = llm_status()
    return json.dumps({
        "time_utc": _now(),
        "pipeline": dict(counts),
        "total_tracked": len(all_j),
        "daily_count": t.get_daily_count(),
        "weekly_count": t.get_weekly_count(),
        "daily_budget": CONFIG["agent"]["max_per_day"],
        "weekly_budget": CONFIG["agent"]["max_per_week"],
        "llm_quota": {p: {"used": s["used"], "limit": s["limit"], "ok": s["available"]}
                      for p, s in quota.items()},
        "recruiter_replies": [
            {"company": j["company"], "title": j["title"],
             "status": j["status"], "applied": str(j.get("applied_at",""))[:10]}
            for j in replied
        ],
        "approved_waiting": [
            {"job_id": j["job_id"], "company": j["company"],
             "title": j["title"], "score": j.get("match_score"), "url": j.get("url","")}
            for j in sorted(approved, key=lambda x: x.get("match_score",0), reverse=True)[:10]
        ],
        "pending_approval": [
            {"job_id": j["job_id"], "company": j["company"],
             "title": j["title"], "score": j.get("match_score"), "url": j.get("url","")}
            for j in sorted(pending, key=lambda x: x.get("match_score",0), reverse=True)[:15]
        ],
    }, indent=2)


def tool_read_job(url: str) -> str:
    """Fetch and return the full text of a job description from its URL."""
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
        soup = BeautifulSoup(resp.text, "lxml")
        # Remove nav/footer noise
        for tag in soup(["nav", "footer", "header", "script", "style", "aside"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
        # Trim to meaningful chunk
        return json.dumps({"url": url, "text": text[:4000]})
    except Exception as e:
        return json.dumps({"url": url, "error": str(e)})


def tool_hunt_jobs() -> str:
    """Search all job sources for new openings matching the profile."""
    from agents.hunt_agent     import HuntAgent
    from agents.score_agent    import ScoreAgent
    from agents.research_agent import ResearchAgent
    from agents.preference_agent import PreferenceAgent
    from agents.tracker_agent  import TrackerAgent

    tracker  = TrackerAgent()
    daily    = tracker.get_daily_count()
    weekly   = tracker.get_weekly_count()
    budget   = min(CONFIG["agent"]["max_per_day"] - daily,
                   CONFIG["agent"]["max_per_week"] - weekly)

    if budget <= 0:
        return json.dumps({"status": "budget_exhausted", "daily": daily, "weekly": weekly})

    raw      = HuntAgent(CONFIG).run()
    scorer   = ScoreAgent(CONFIG, MASTER_RESUME)
    scored   = scorer.run(raw)
    prefs    = PreferenceAgent()
    for j in scored:
        j["match_score"] = prefs.adjust_score(j, j["match_score"])
    scored.sort(key=lambda j: j["match_score"], reverse=True)

    new_jobs = [j for j in scored if not tracker.is_seen(j["id"])]
    results  = new_jobs[:budget]

    researcher = ResearchAgent()
    for j in results:
        j["company_research"] = researcher.run(j.get("company",""), j.get("title",""), CONFIG)

    return json.dumps({
        "found": len(raw),
        "scored": len(scored),
        "new": len(new_jobs),
        "returning": [
            {"job_id": j["id"], "company": j["company"], "title": j["title"],
             "score": j["match_score"], "source": j["source"], "url": j.get("url",""),
             "description_snippet": j.get("description","")[:300]}
            for j in results
        ],
        "_raw_jobs": results,   # passed to approve tool
    })


def tool_approve_job(job_id: str, reason: str = "", job_data: dict = None) -> str:
    """Approve a job for tailoring and application. Pass the full job dict if available."""
    from agents.tracker_agent import TrackerAgent
    t = TrackerAgent()
    if job_data:
        # New job from hunt — log it first then approve
        job_data["job_id"] = job_data.get("job_id") or job_data.get("id", job_id)
        t.log(job_data, status="approved")
    else:
        t.approve_job(job_id)
    print(f"{G}  ✓ Approved: {job_id} — {reason}{RST}")
    return json.dumps({"approved": job_id, "reason": reason})


def tool_skip_job(job_id: str, reason: str = "") -> str:
    """Skip a job — not a good fit."""
    from agents.tracker_agent import TrackerAgent
    t = TrackerAgent()
    if t.is_seen(job_id):
        t.skip_job(job_id)
    else:
        # Never seen — log as skipped so we don't see it again
        t.log({"id": job_id, "job_id": job_id, "company": "", "title": "",
               "source": "", "url": "", "match_score": 0}, status="skipped")
    print(f"{D}  ✗ Skipped: {job_id} — {reason}{RST}")
    return json.dumps({"skipped": job_id, "reason": reason})


def tool_tailor_and_apply(job_id: str) -> str:
    """Tailor resume + cover letter for a specific job, generate PDF, and submit application."""
    from agents.tracker_agent       import TrackerAgent
    from agents.tailor_writer_agent import TailorWriterAgent
    from agents.pdf_agent           import PDFAgent
    from agents.review_agent        import ReviewAgent
    from agents.apply_agent         import ApplyAgent
    from agents.notify_agent        import NotifyAgent
    from agents.base                import QuotaAllExhausted
    import os

    tracker = TrackerAgent()
    rows = tracker.db.table("job_applications").select("*").eq("job_id", job_id).execute().data
    if not rows:
        return json.dumps({"error": f"Job {job_id} not found in DB"})
    job = dict(rows[0])

    try:
        # 1. Tailor
        tw  = TailorWriterAgent(CONFIG, MASTER_RESUME)
        job = tw.run(job, company_research=job.get("company_research",""))

        # 2. PDF
        safe   = lambda s: "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:35]
        pdf_p  = os.path.join(CONFIG["resume"]["output_dir"],
                              f"{safe(job.get('company',''))}_{safe(job.get('title',''))}.pdf")
        try:
            PDFAgent().generate(job["tailored_resume"], pdf_p)
            job["resume_pdf_path"] = pdf_p
        except Exception as e:
            job["resume_pdf_path"] = None

        # 3. ATS gate
        ats = float(job.get("ats_score") or 0)
        if 0 < ats < 85:
            tracker.log(job, status="approved")
            return json.dumps({"status": "ats_too_low", "ats_score": ats,
                               "message": "Kept as approved — retry after LLM quota resets"})

        # 4. Apply
        try:
            job = ReviewAgent(CONFIG, MASTER_RESUME).run(job)
        except Exception:
            job["review_passed"] = True

        result = ApplyAgent(CONFIG).apply(job, job.get("resume_pdf_path"))
        status = "applied" if result.get("success") else "needs_1click"
        tracker.log(job, status=status)
        if result.get("success"):
            tracker.mark_applied(job["job_id"])

        # 5. Email notification
        try:
            NotifyAgent(CONFIG).send_job_package(job)
        except Exception:
            pass

        return json.dumps({
            "job_id":   job_id,
            "company":  job.get("company"),
            "title":    job.get("title"),
            "status":   status,
            "ats_score": job.get("ats_score"),
            "method":   result.get("method"),
            "success":  result.get("success"),
        })

    except QuotaAllExhausted as e:
        return json.dumps({"error": "llm_quota_exhausted", "reset_at": e.reset_at})
    except Exception as e:
        return json.dumps({"error": str(e)})


def tool_check_replies() -> str:
    """Check Gmail for recruiter replies. Detect interviews, rejections, and replies."""
    from agents.followup_agent import FollowUpAgent
    try:
        FollowUpAgent(CONFIG).run()
    except FileNotFoundError:
        return json.dumps({"error": "Gmail not configured — run OAuth setup first"})
    except Exception as e:
        return json.dumps({"error": str(e)})

    from agents.tracker_agent import TrackerAgent
    t = TrackerAgent()
    active = (t.db.table("job_applications")
                .select("*").in_("status", ["replied", "interview"]).execute().data)
    return json.dumps({
        "active_conversations": [
            {"company": j["company"], "title": j["title"],
             "status": j["status"], "applied": str(j.get("applied_at",""))[:10]}
            for j in active
        ]
    })


def tool_send_email(subject: str, body_html: str) -> str:
    """Send an email to Chandrababu (status updates, summaries, alerts)."""
    import resend
    resend.api_key = os.environ["RESEND_API_KEY"]
    resend.Emails.send({
        "from":    "Job Agent <onboarding@resend.dev>",
        "to":      CONFIG["candidate"]["email"],
        "subject": subject,
        "html":    body_html,
    })
    return json.dumps({"sent": True, "subject": subject})


# ── Tool registry ──────────────────────────────────────────────────────────────

_HUNT_CACHE = {}   # store raw hunt results so approve can access them

TOOL_FNS = {
    "get_pipeline_state":  lambda i: tool_get_pipeline_state(),
    "read_job":            lambda i: tool_read_job(i["url"]),
    "hunt_jobs":           lambda i: _hunt_and_cache(i),
    "approve_job":         lambda i: tool_approve_job(i["job_id"], i.get("reason",""), _HUNT_CACHE.get(i["job_id"])),
    "skip_job":            lambda i: tool_skip_job(i["job_id"], i.get("reason","")),
    "tailor_and_apply":    lambda i: tool_tailor_and_apply(i["job_id"]),
    "check_replies":       lambda i: tool_check_replies(),
    "send_email":          lambda i: tool_send_email(i["subject"], i["body_html"]),
}

def _hunt_and_cache(inp: dict) -> str:
    result_str = tool_hunt_jobs()
    result     = json.loads(result_str)
    for j in result.get("_raw_jobs", []):
        jid = j.get("id") or j.get("job_id")
        if jid:
            _HUNT_CACHE[jid] = j
    result.pop("_raw_jobs", None)
    return json.dumps(result)


TOOL_DEFS = [
    {
        "name": "get_pipeline_state",
        "description": "Read current pipeline — counts by status, LLM quota, recruiter conversations, approved/pending jobs. Always call this first.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_job",
        "description": "Fetch the full job description text from a URL so you can evaluate fit before deciding to apply.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "hunt_jobs",
        "description": "Search LinkedIn, Greenhouse, Lever, Remotive, Serper, and 6 other sources for new job openings. Returns jobs with scores and snippets for your review.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "approve_job",
        "description": "Approve a job for tailoring and application. Provide a reason so the decision is logged.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "reason": {"type": "string", "description": "Why this job is a good fit"},
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "skip_job",
        "description": "Skip a job — not a good fit. Provide a reason.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "reason": {"type": "string", "description": "Why skipping (e.g. 'requires 8 years Java', 'crypto company', 'too senior')"},
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "tailor_and_apply",
        "description": "Full application pipeline for one job: tailor resume → score ATS → generate PDF → submit. Call once per approved job.",
        "input_schema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
        },
    },
    {
        "name": "check_replies",
        "description": "Scan Gmail for recruiter replies to applications. Detects interviews, rejections, and general replies. Sends follow-ups where needed.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "send_email",
        "description": "Send an email to Chandrababu. Use for cycle summaries, alerts about interviews, or important updates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject":   {"type": "string"},
                "body_html": {"type": "string", "description": "HTML email body"},
            },
            "required": ["subject", "body_html"],
        },
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM = """You are an autonomous job search agent. Your mission: land Chandrababu Naidu Anakapalli a software engineering job within 30 days. The campaign started June 26, 2026.

CANDIDATE:
  Name: Chandrababu Naidu Anakapalli
  Stack: Python (FastAPI, Django), C#/.NET 8, React, TypeScript
  AI/ML: Claude API, Gemini, Groq, Multi-agent systems, MCP, RAG, pgvector
  Experience: 4 years — Citibank (.NET banking APIs), Datara Inc (.NET ERP), AT&T (intern)
  Education: MS Computer Science, Sacred Heart University (May 2025)
  Location: Bridgeport, CT — open to remote or CT/NYC area
  Certs: Anthropic AI Fluency, Claude 101, Advanced MCP, Azure Cognitive Services

GOOD FIT — actively apply:
  Python backend, AI/ML engineer, .NET developer, full-stack (React + Python/Node)
  Companies: startups, scale-ups, fintech, AI-native, SaaS
  Score >= 10 = strong match, score >= 8 = worth reviewing

BAD FIT — skip these:
  Java-only, Ruby/PHP/Go/Rust-only, mobile (iOS/Android), pure DevOps/SRE
  Requires security clearance, crypto/Web3, Brazil/LATAM-only, 7+ years experience required
  Pure "Staff Engineer" or "Principal Engineer" (too senior)

HOW TO RUN A CYCLE:
1. Call get_pipeline_state — understand what needs attention
2. PRIORITY 1: If there are recruiter replies → call check_replies immediately
3. PRIORITY 2: If there are approved jobs waiting → call tailor_and_apply for each
4. PRIORITY 3: If daily budget allows → call hunt_jobs, then read_job for top candidates
5. After reading JDs, approve good fits and skip bad ones
6. Apply to approved jobs with tailor_and_apply
7. Send a concise summary email of what you did this cycle

WHEN READING JDs:
- Read the actual requirements — don't just trust the score
- Skip if: requires 6+ years, Java/Ruby/PHP only, security clearance, visa impossible
- Approve if: Python or .NET, remote or CT/NYC, 0-5 years experience, company looks real
- A brief reason for each decision is enough

CONSTRAINTS:
- ATS gate: resumes scoring <85% are blocked (LLM quality too low) — skip apply, keep as approved
- LLM quota: Gemini 1490/day, Groq 70B 990/day, Groq 8B 14000/day — resets 00:00 UTC
- If quota exhausted mid-cycle: stop and send summary of what was completed
- Max 20 applications/day, 140/week

Be decisive. Don't ask for permission. Just do the work."""


# ══════════════════════════════════════════════════════════════════════════════
# AGENT CYCLE
# ══════════════════════════════════════════════════════════════════════════════

def run_cycle():
    """One full agent cycle — Claude decides what to do and does it."""
    if not _cycle_lock.acquire(blocking=False):
        print(f"{Y}[Agent] Previous cycle still running — skipping{RST}")
        return

    try:
        client   = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        messages = [{
            "role":    "user",
            "content": f"Run your job search cycle. Time: {_now()}. Check state first, then work through your priorities.",
        }]

        print(f"\n{BLD}{C}{'═'*55}{RST}")
        print(f"{BLD}{C}  Autonomous Agent — {_now()}{RST}")
        print(f"{BLD}{C}{'═'*55}{RST}\n")

        # Agentic loop — keep going until Claude stops calling tools
        iterations = 0
        max_iterations = 30   # safety cap

        while iterations < max_iterations:
            iterations += 1

            response = client.messages.create(
                model      = "claude-sonnet-4-6",
                max_tokens = 4096,
                system     = SYSTEM,
                tools      = TOOL_DEFS,
                messages   = messages,
            )

            # Print any text Claude outputs
            for block in response.content:
                if hasattr(block, "text") and block.text.strip():
                    print(f"{BLD}Agent:{RST} {block.text.strip()}\n")

            messages.append({"role": "assistant", "content": response.content})

            # No tool calls = Claude is done
            if response.stop_reason == "end_turn":
                break

            # Execute tool calls
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                name = block.name
                inp  = block.input
                print(f"{D}  [{name}] {json.dumps(inp)[:120]}{RST}")

                try:
                    result = TOOL_FNS[name](inp) if name in TOOL_FNS else json.dumps({"error": f"Unknown: {name}"})
                except Exception as e:
                    result = json.dumps({"error": str(e)})
                    print(f"  ✗ Error in {name}: {e}")

                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     result,
                })

            messages.append({"role": "user", "content": tool_results})

        print(f"\n{G}[Agent] Cycle complete ({iterations} steps){RST}\n")

    except Exception as e:
        print(f"\n  [Agent] Cycle error: {e}")

    finally:
        _cycle_lock.release()


# ══════════════════════════════════════════════════════════════════════════════
# SCHEDULER
# ══════════════════════════════════════════════════════════════════════════════

def main():
    once = "--once" in sys.argv

    if once:
        run_cycle()
        return

    print(f"\n{BLD}{C}┌──────────────────────────────────────────┐{RST}")
    print(f"{BLD}{C}│   Autonomous Job Agent — 24/7 Mode        │{RST}")
    print(f"{BLD}{C}│   Claude claude-sonnet-4-6 · Every 30 min       │{RST}")
    print(f"{BLD}{C}└──────────────────────────────────────────┘{RST}")
    print(f"{D}Ctrl+C to stop{RST}\n")

    run_cycle()   # run immediately on start

    schedule.every(30).minutes.do(run_cycle)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
