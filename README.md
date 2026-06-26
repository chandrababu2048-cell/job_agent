# 🤖 Autonomous Job Search Agent

A 24/7 multi-agent pipeline that searches 8+ job boards every 30 minutes, tailors your resume and cover letter per role using LLMs, and auto-submits applications to Greenhouse, Lever, and Ashby — while you sleep.

**Built by:** Chandrababu Naidu Anakapalli · [LinkedIn](https://linkedin.com/in/chandra-a-084825244)

---

## How It Works

```
HuntAgent → ScoreAgent → [Your Approval] → TailorAgent + WriterAgent → ApplyAgent → TrackerAgent → NotifyAgent
```

1. **HuntAgent** — searches 8 sources every 30 min (LinkedIn, Adzuna, Remotive, RemoteOK, WeWorkRemotely, Jobicy, WorkingNomads, Brave Search)
2. **ScoreAgent** — keyword scoring gate filters 1,000+ raw listings down to 4★+ matches with zero API calls
3. **You** — get an email digest, reply YES/NO/EDIT
4. **TailorAgent + WriterAgent** — LLM rewrites your resume and cover letter specifically for that company and role
5. **ApplyAgent** — auto-submits via Playwright to Greenhouse / Lever / Ashby; queues others as 1-click
6. **TrackerAgent** — logs everything to Supabase with full status history
7. **NotifyAgent** — sends job packages and follow-up reminders via Resend + Gmail

---

## Features

- ✅ **Zero-API scoring** — filters 1,000+ jobs per run using keyword matching (no LLM cost)
- ✅ **LLM resume tailoring** — Gemini 2.0 Flash → Groq 70B → Groq 8B with circuit-breaker failover
- ✅ **Email approval workflow** — reply YES/NO/EDIT to the digest email; agent acts on your reply
- ✅ **Playwright ATS automation** — auto-fills and submits Greenhouse, Lever, Ashby forms
- ✅ **Brave Search integration** — finds jobs directly on company career pages
- ✅ **Supabase tracking** — full pipeline visibility with status history
- ✅ **7-day follow-up** — auto-sends follow-up emails after no response
- ✅ **Daily quota management** — tracks Gemini/Groq usage, auto-resets at midnight UTC

---

## Tech Stack

| Layer | Tech |
|---|---|
| Language | Python 3.12+ |
| LLMs | Gemini 2.0 Flash, Groq (Llama 3.3 70B, Llama 3.1 8B) |
| Browser automation | Playwright |
| Database | Supabase (PostgreSQL) |
| Email | Resend + Gmail OAuth |
| Job search | LinkedIn, Adzuna, Remotive, RemoteOK, WeWorkRemotely, Jobicy, WorkingNomads, Brave Search |
| Scheduler | Python subprocess + caffeinate (Mac) |

---

## Architecture

```
agents/
├── base.py              # LLM router (Gemini → Groq 70B → Groq 8B, quota tracking)
├── hunt_agent.py        # Parallel job search across 8 sources
├── score_agent.py       # Keyword scoring gate (zero API cost)
├── tailor_writer_agent.py  # LLM resume + cover letter tailoring
├── apply_agent.py       # Playwright form automation (Greenhouse/Lever/Ashby)
├── tracker_agent.py     # Supabase logging + status management
├── notify_agent.py      # Resend email notifications + digests
├── reply_agent.py       # Gmail reply scanning (YES/NO/EDIT processing)
├── linkedin_agent.py    # LinkedIn Easy Apply automation
├── followup_agent.py    # 7-day follow-up email automation
└── research_agent.py    # Company research (cached)
orchestrator.py          # Pipeline coordinator (hunt / tailor / reply-check / followup)
scheduler.py             # Runs every 30 min, 24/7
cli.py                   # Manual controls
```

---

## Setup

### 1. Clone and install
```bash
git clone https://github.com/chandrababu2048-cell/job_agent.git
cd job_agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure environment
```bash
cp .env.example .env
# Fill in your API keys (see .env.example for all required keys)
```

Required keys:
- `GEMINI_API_KEY` — [Google AI Studio](https://aistudio.google.com) (free)
- `GROQ_API_KEY` — [Groq Console](https://console.groq.com) (free)
- `SUPABASE_URL` + `SUPABASE_KEY` — [Supabase](https://supabase.com) (free)
- `RESEND_API_KEY` — [Resend](https://resend.com) (free)
- `ADZUNA_APP_ID` + `ADZUNA_API_KEY` — [Adzuna](https://developer.adzuna.com) (free)

Optional (enables full auto-submit):
- `BRAVE_API_KEY` — [Brave Search API](https://api.search.brave.com) (free, 2000/month)

### 3. Edit your profile
```bash
# Add your details to config.yaml
nano config.yaml

# Add your master resume
nano resume/master_resume.md
```

### 4. Authorize Gmail (once)
```bash
python -c "from agents.gmail_agent import GmailAgent; GmailAgent()._authenticate()"
```

### 5. Run health check
```bash
python orchestrator.py --test
```

### 6. Start the agent
```bash
python scheduler.py
```

---

## CLI Commands

```bash
python cli.py status              # full pipeline view
python cli.py pending             # jobs waiting for your approval
python cli.py approve <job_id>    # approve a job → triggers tailoring
python cli.py skip <job_id>       # skip a job
python cli.py open-all            # open all needs_1click jobs in browser
python cli.py mark-applied <id>   # mark as applied (starts follow-up timer)
python cli.py run-hunt            # manual hunt cycle
python cli.py run-tailor          # manual tailor cycle
```

---

## Email Workflow

You get a digest email like this:

```
#1 AI Engineer @ OpenAI ⭐⭐⭐⭐⭐
    Matched: python, llm, ai, machine learning
    Job ID: gh_abc123

Reply to this email:
  YES           → approve all jobs
  YES abc123    → approve specific job
  NO abc123     → skip a job
  EDIT abc123: focus more on Python pipelines → re-tailor with your note
```

---

## License

MIT — use it, adapt it, build on it.
