#!/usr/bin/env python3
"""
Job Agent — Claude-powered interactive assistant.

Run:  python agent.py

Talk to it:
  "what's the status?"
  "hunt for new jobs"
  "show me what's pending"
  "approve everything above score 12"
  "tailor and apply to all approved"
  "any recruiter replies?"
  "approve the Stripe and Anthropic jobs"
"""

import os
import sys
import json
import yaml
import anthropic
from datetime import datetime, timezone
from collections import Counter
from dotenv import load_dotenv

load_dotenv()

# ── Terminal colors ────────────────────────────────────────────────────────────
B   = "\033[94m"    # blue
G   = "\033[92m"    # green
Y   = "\033[93m"    # yellow
R   = "\033[91m"    # red
C   = "\033[96m"    # cyan
D   = "\033[90m"    # dark gray
BLD = "\033[1m"
RST = "\033[0m"


# ══════════════════════════════════════════════════════════════════════════════
# TOOLS — what Claude can do
# ══════════════════════════════════════════════════════════════════════════════

def _get_status() -> str:
    from agents.tracker_agent import TrackerAgent
    t = TrackerAgent()
    all_j = t.get_recent(limit=300)
    counts = Counter(j.get("status") for j in all_j)
    replied  = [j for j in all_j if j.get("status") in ("replied", "interview")]
    approved = [j for j in all_j if j.get("status") == "approved"]
    pending  = [j for j in all_j if j.get("status") == "pending_approval"]
    daily    = t.get_daily_count()
    weekly   = t.get_weekly_count()
    return json.dumps({
        "pipeline": dict(counts),
        "total_tracked": len(all_j),
        "daily_applications": daily,
        "weekly_applications": weekly,
        "active_conversations": [
            {"company": j["company"], "title": j["title"],
             "status": j["status"], "applied": str(j.get("applied_at",""))[:10]}
            for j in replied
        ],
        "top_approved_waiting": [
            {"job_id": j["job_id"], "company": j["company"],
             "title": j["title"], "score": j.get("match_score")}
            for j in sorted(approved, key=lambda x: x.get("match_score",0), reverse=True)[:5]
        ],
        "top_pending_approval": [
            {"job_id": j["job_id"], "company": j["company"],
             "title": j["title"], "score": j.get("match_score")}
            for j in sorted(pending, key=lambda x: x.get("match_score",0), reverse=True)[:5]
        ],
    }, indent=2)


def _get_pending(limit: int = 25) -> str:
    from agents.tracker_agent import TrackerAgent
    t = TrackerAgent()
    jobs = t.get_pending_approval()
    jobs.sort(key=lambda x: x.get("match_score", 0), reverse=True)
    return json.dumps([
        {
            "job_id":      j["job_id"],
            "company":     j["company"],
            "title":       j["title"],
            "score":       j.get("match_score"),
            "source":      j.get("source"),
            "url":         (j.get("url",""))[:80],
            "why":         j.get("match_reason","")[:120],
        }
        for j in jobs[:limit]
    ], indent=2)


def _approve(job_ids: list = None, min_score: int = None) -> str:
    from agents.tracker_agent import TrackerAgent
    t = TrackerAgent()
    if min_score is not None:
        pending  = t.get_pending_approval()
        job_ids  = [j["job_id"] for j in pending
                    if (j.get("match_score") or 0) >= min_score]
    if not job_ids:
        return json.dumps({"approved": 0, "message": "No jobs matched"})
    for jid in job_ids:
        t.approve_job(jid)
    return json.dumps({"approved": len(job_ids),
                       "message": f"{len(job_ids)} jobs moved to approved — ready for tailoring"})


def _skip(job_ids: list) -> str:
    from agents.tracker_agent import TrackerAgent
    t = TrackerAgent()
    for jid in job_ids:
        t.skip_job(jid)
    return json.dumps({"skipped": len(job_ids)})


def _run_hunt() -> str:
    import subprocess
    print(f"\n{D}{'─'*55}{RST}", flush=True)
    r = subprocess.run(
        [sys.executable, "-u", "orchestrator.py", "--hunt"],
        env={**os.environ, "PYTHONUNBUFFERED": "1", "MallocStackLogging": "0"},
    )
    print(f"{D}{'─'*55}{RST}\n", flush=True)
    # Return fresh status after hunt
    from agents.tracker_agent import TrackerAgent
    t = TrackerAgent()
    all_j = t.get_recent(limit=200)
    counts = Counter(j.get("status") for j in all_j)
    return json.dumps({
        "exit_code": r.returncode,
        "pipeline_after": dict(counts),
        "message": "Hunt complete — see output above for details",
    })


def _run_tailor(job_ids: list = None) -> str:
    import subprocess
    print(f"\n{D}{'─'*55}{RST}", flush=True)
    cmd = [sys.executable, "-u", "orchestrator.py", "--tailor"]
    if job_ids:
        cmd += ["--job-ids"] + job_ids
    r = subprocess.run(
        cmd,
        env={**os.environ, "PYTHONUNBUFFERED": "1", "MallocStackLogging": "0"},
    )
    print(f"{D}{'─'*55}{RST}\n", flush=True)
    from agents.tracker_agent import TrackerAgent
    t = TrackerAgent()
    counts = Counter(j.get("status") for j in t.get_recent(limit=200))
    return json.dumps({
        "exit_code": r.returncode,
        "pipeline_after": dict(counts),
        "message": "Tailor cycle complete — see output above",
    })


def _check_replies() -> str:
    import subprocess
    print(f"\n{D}{'─'*55}{RST}", flush=True)
    subprocess.run(
        [sys.executable, "-u", "orchestrator.py", "--followup"],
        env={**os.environ, "PYTHONUNBUFFERED": "1", "MallocStackLogging": "0"},
    )
    print(f"{D}{'─'*55}{RST}\n", flush=True)
    from agents.tracker_agent import TrackerAgent
    t = TrackerAgent()
    active = (t.db.table("job_applications")
                .select("*")
                .in_("status", ["replied", "interview"])
                .execute().data)
    return json.dumps({
        "active_conversations": [
            {"company": j["company"], "title": j["title"], "status": j["status"]}
            for j in active
        ],
        "count": len(active),
    })


def _get_applied(status: str = "applied") -> str:
    from agents.tracker_agent import TrackerAgent
    t = TrackerAgent()
    if status == "all":
        jobs = t.get_recent(limit=50)
    else:
        jobs = (t.db.table("job_applications")
                  .select("*").eq("status", status)
                  .order("applied_at", desc=True).limit(20)
                  .execute().data)
    return json.dumps([
        {"company": j["company"], "title": j["title"],
         "status": j["status"], "source": j.get("source",""),
         "applied": str(j.get("applied_at",""))[:10],
         "followups": j.get("followup_count", 0)}
        for j in jobs
    ], indent=2)


def _llm_status() -> str:
    from agents.base import llm_status
    s = llm_status()
    reset_time = "2026-07-07 00:00 UTC" if datetime.now(timezone.utc).hour >= 0 else "tonight 00:00 UTC"
    return json.dumps({
        "providers": s,
        "quota_resets": "daily at 00:00 UTC",
        "note": "If gemini available=False, Groq fallback is used (lower quality). Jobs with ATS<85% are blocked.",
    })


# ── Tool registry ──────────────────────────────────────────────────────────────

TOOL_FNS = {
    "get_status":       lambda i: _get_status(),
    "get_pending_jobs": lambda i: _get_pending(i.get("limit", 25)),
    "approve_jobs":     lambda i: _approve(i.get("job_ids"), i.get("min_score")),
    "skip_jobs":        lambda i: _skip(i.get("job_ids", [])),
    "run_hunt":         lambda i: _run_hunt(),
    "run_tailor":       lambda i: _run_tailor(i.get("job_ids")),
    "check_replies":    lambda i: _check_replies(),
    "get_applied_jobs": lambda i: _get_applied(i.get("status", "applied")),
    "llm_status":       lambda i: _llm_status(),
}

TOOL_DEFS = [
    {
        "name": "get_status",
        "description": "Current pipeline state — counts by status, active recruiter conversations, top pending/approved jobs.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_pending_jobs",
        "description": "Jobs waiting for your approval, sorted by match score.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max to return (default 25)"},
            },
        },
    },
    {
        "name": "approve_jobs",
        "description": "Approve jobs for tailoring and application. Use job_ids for specific jobs, or min_score to bulk-approve everything at or above that score.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_ids":   {"type": "array", "items": {"type": "string"}},
                "min_score": {"type": "integer", "description": "Approve all pending with score >= this"},
            },
        },
    },
    {
        "name": "skip_jobs",
        "description": "Skip/reject specific jobs by job_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["job_ids"],
        },
    },
    {
        "name": "run_hunt",
        "description": "Search all job sources (LinkedIn, Greenhouse, Lever, Remotive, Serper, etc.) for new matching jobs. Output streams live. Takes 1-3 min.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_tailor",
        "description": "Tailor resumes for approved jobs and auto-submit applications. Full pipeline: keyword extract → LLM tailor → ATS score → PDF → apply. Output streams live.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_ids": {"type": "array", "items": {"type": "string"}, "description": "Optional: only these jobs"},
            },
        },
    },
    {
        "name": "check_replies",
        "description": "Check Gmail for recruiter replies and send follow-ups where needed.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_applied_jobs",
        "description": "List applied jobs filtered by status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["applied", "replied", "interview", "rejected", "needs_1click", "all"],
                },
            },
        },
    },
    {
        "name": "llm_status",
        "description": "Check LLM provider quota usage (Gemini, Groq 70B, Groq 8B). Use when wondering why ATS scores are low or tailoring seems weak.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# AGENT LOOP
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM = """\
You are an autonomous job search agent managing Chandrababu Naidu Anakapalli's job search.
You have direct control over the full pipeline: hunt → score → approve → tailor → apply → track → follow-up.

CANDIDATE PROFILE:
  Name: Chandrababu Naidu Anakapalli
  Stack: Python + .NET, 4 years, Bridgeport CT
  Target: Software Engineer, AI Engineer, Backend Engineer
  Goal: Land a job within 30 days (campaign started June 26, 2026)

PIPELINE RULES YOU KNOW:
  - Jobs need approval before tailoring (pending_approval → approved → applied)
  - ATS score gate: resumes scoring <85% are blocked from submitting (stay as approved until quota resets)
  - LLM router: Gemini 2.0 Flash → Groq 70B → Groq 8B (quality degrades down the chain)
  - Quotas reset daily at 00:00 UTC
  - LinkedIn Easy Apply needs linkedin_session.json — if missing, jobs go to needs_1click
  - LinkedIn login command: python -c "from agents.linkedin_agent import LinkedInAgent; LinkedInAgent().login()"
  - Greenhouse/Lever/Ashby jobs auto-submit via Playwright (Serper/Brave sources)

HOW TO BEHAVE:
  - Be decisive. When told to do something, do it immediately with tools — don't ask "are you sure?".
  - Report concisely after actions: what happened + key numbers.
  - If there's a backlog or something broken, call it out directly.
  - You can chain multiple tool calls to complete complex requests (e.g., hunt → show pending → approve → tailor).
  - Keep responses short — user can always ask for more detail.

Today: {today}"""


def main():
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    today  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    system = SYSTEM.format(today=today)
    messages: list[dict] = []

    print(f"\n{BLD}{C}┌─────────────────────────────────────────┐{RST}")
    print(f"{BLD}{C}│        Job Agent  ·  Interactive         │{RST}")
    print(f"{BLD}{C}└─────────────────────────────────────────┘{RST}")
    print(f"{D}Commands: 'status', 'hunt', 'pending', 'tailor', 'replies', 'exit'{RST}\n")

    while True:
        try:
            raw = input(f"{BLD}You:{RST} ").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{D}Bye.{RST}")
            break

        if not raw:
            continue
        if raw.lower() in ("exit", "quit", "q", "bye"):
            print(f"{D}Bye.{RST}")
            break

        messages.append({"role": "user", "content": raw})

        # ── Agentic loop: keep calling until no more tool calls ────────────────
        while True:
            # Stream response text live
            print(f"\n{BLD}{B}Agent:{RST} ", end="", flush=True)

            with client.messages.stream(
                model    = "claude-sonnet-4-6",
                max_tokens = 2048,
                system   = system,
                tools    = TOOL_DEFS,
                messages = messages,
            ) as stream:
                for text in stream.text_stream:
                    print(text, end="", flush=True)
                final = stream.get_final_message()

            print()  # newline after streamed text

            # Add assistant turn to history
            messages.append({"role": "assistant", "content": final.content})

            # No tool calls → done
            if final.stop_reason != "tool_use":
                print()
                break

            # Execute every tool call
            results = []
            for block in final.content:
                if block.type != "tool_use":
                    continue

                name = block.name
                inp  = block.input
                print(f"{D}  → {name}({', '.join(f'{k}={v}' for k,v in inp.items()) if inp else ''}){RST}")

                try:
                    output = TOOL_FNS[name](inp) if name in TOOL_FNS else json.dumps({"error": f"Unknown tool: {name}"})
                except Exception as e:
                    output = json.dumps({"error": str(e)})

                results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     output,
                })

            messages.append({"role": "user", "content": results})
            # loop back → Claude reads results + responds / calls more tools


if __name__ == "__main__":
    main()
