"""
Job Agent v2 — 24/7 Scheduler (30-Day Aggressive Mode)
═══════════════════════════════════════════════════════
Run:  .venv/bin/python scheduler.py
Stop: Ctrl+C

Background (runs forever on Mac):
  nohup .venv/bin/python scheduler.py > logs/agent.log 2>&1 &

Schedule:
  Hunt:           every 30 minutes
  Reply check:    every 30 minutes (offset 15 min from hunt)
  Follow-ups:     09:00 + 18:00 UTC daily
  Weekly report:  Sunday 08:00 UTC
"""

import os
import schedule
import subprocess
import sys
from datetime import datetime, timezone

os.makedirs("logs", exist_ok=True)


def _run(mode: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n[Scheduler] {ts} → {mode}", flush=True)
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    subprocess.run([sys.executable, "-u", "orchestrator.py", mode], env=env)


def hunt():        _run("--hunt")
def reply_check(): _run("--reply-check")
def followup():    _run("--followup")
def weekly():      _run("--weekly")


if __name__ == "__main__":
    print("═" * 60)
    print("  Job Agent v2 — 30-Day Mode — ACTIVE")
    print("  Hunt:         every 30 minutes")
    print("  Reply check:  every 30 minutes (offset 15 min)")
    print("  Follow-ups:   09:00 + 18:00 UTC daily")
    print("  Weekly:       Sunday 08:00 UTC")
    print("  Ctrl+C to stop")
    print("═" * 60, flush=True)

    hunt()  # Run immediately on start

    schedule.every(30).minutes.do(hunt)
    schedule.every(30).minutes.do(reply_check)
    schedule.every().day.at("09:00").do(followup)
    schedule.every().day.at("18:00").do(followup)
    schedule.every().sunday.at("08:00").do(weekly)

    import time
    # Stagger reply_check by 15 min so it doesn't collide with hunt
    import threading
    def _delayed_first_reply():
        import time as _t
        _t.sleep(900)  # 15 minutes
        reply_check()
    threading.Thread(target=_delayed_first_reply, daemon=True).start()

    while True:
        schedule.run_pending()
        time.sleep(30)
