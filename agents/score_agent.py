import json
import concurrent.futures
from .base import call_llm_haiku, call_llm_sonnet

STAR_ICONS = {5: "⭐⭐⭐⭐⭐", 4: "⭐⭐⭐⭐☆", 3: "⭐⭐⭐☆☆", 2: "⭐⭐☆☆☆", 1: "⭐☆☆☆☆"}


def stars(n):
    return STAR_ICONS.get(int(n), "☆☆☆☆☆")


class ScoreAgent:
    """
    Two-stage quality gate:
      Gate 2 — fast 1-5 star rating (Groq Llama 8B, all jobs in parallel)
      Gate 3 — deep recruiter fit analysis (Groq 70B, only 4-5★ jobs)
    Only jobs rated 4★+ proceed. Hard cap: top 10 per run.
    """

    def __init__(self, config, master_resume):
        self.config = config
        self.master_resume = master_resume
        self.min_stars = config["job_search"].get("min_stars", 4)

    def run(self, jobs):
        # ── Gate 2: fast star rating on all jobs ──────────────────────────────
        print(f"\n[ScoreAgent] Gate 2 — rating {len(jobs)} jobs (1-5★ threshold: {self.min_stars}★)…")
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(self._gate2_rate, job): job for job in jobs}
            gate2_passed = []
            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result()
                    if result:
                        gate2_passed.append(result)
                except Exception as e:
                    print(f"  [Gate2 error] {e}")

        gate2_passed.sort(key=lambda j: j["stars"], reverse=True)
        print(f"[ScoreAgent] Gate 2: {len(gate2_passed)}/{len(jobs)} rated {self.min_stars}★+")

        # Cap at top 15 before deep analysis (saves API calls)
        candidates = gate2_passed[:15]

        # ── Gate 3: deep recruiter fit analysis on top candidates ─────────────
        print(f"[ScoreAgent] Gate 3 — deep fit on top {len(candidates)} candidates…")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = {pool.submit(self._gate3_deep_fit, job): job for job in candidates}
            qualified = []
            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result()
                    if result:
                        qualified.append(result)
                except Exception as e:
                    print(f"  [Gate3 error] {e}")

        qualified.sort(key=lambda j: j["stars"], reverse=True)
        # Hard cap: best 10 per run (quality over quantity)
        qualified = qualified[:10]

        print(f"[ScoreAgent] Gate 3: {len(qualified)} shortlisted for your approval")
        for j in qualified:
            print(f"  {stars(j['stars'])} {j['title']} @ {j['company']} "
                  f"[{j.get('work_type','?')}] — {j.get('why_shortlisted','')[:60]}")

        return qualified

    # ── Gate 2: fast 1-5 star rating ──────────────────────────────────────────

    def _gate2_rate(self, job):
        prompt = f"""You are an expert technical recruiter. Rate this job match 1-5 stars.

CANDIDATE SUMMARY:
{self.master_resume[:1200]}

JOB: {job['title']} at {job['company']}
DESCRIPTION:
{job['description'][:1500]}

Rate 1-5 stars based on: skills match, seniority fit, role alignment.
4★ = strong match worth applying | 5★ = exceptional fit

Reply ONLY with valid JSON (no markdown):
{{"stars": 4, "reason": "Strong Python/AI match", "work_type": "Remote"}}

work_type must be exactly: Remote, Hybrid, Onsite, or Check JD"""

        try:
            text = call_llm_haiku(self.config, prompt, max_tokens=200)
            text = text.strip()
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                text = text[start:end]
            data = json.loads(text)
            rating = int(data.get("stars", 0))
            if rating < self.min_stars:
                return None
            job["stars"] = rating
            job["match_score"] = rating * 2   # keep numeric for compatibility
            job["match_reason"] = data.get("reason", "")
            job["work_type"] = data.get("work_type", "Check JD")
            return job
        except Exception as e:
            print(f"  [Gate2:{job.get('company','?')}] error: {e}")
            return None

    # ── Gate 3: deep recruiter analysis ───────────────────────────────────────

    def _gate3_deep_fit(self, job):
        prompt = f"""You are a senior technical recruiter screening candidates for a role.
Be honest, strategic, and direct. Protect the candidate from wasting applications on poor fits.

CANDIDATE:
{self.master_resume}

ROLE: {job['title']} at {job['company']}
INITIAL RATING: {job['stars']}★
WORK TYPE: {job.get('work_type', '?')}

FULL JOB DESCRIPTION:
{job['description'][:3000]}

Provide a recruiter-level assessment. Reply ONLY with valid JSON:
{{
  "stars": 4,
  "why_shortlisted": "One sentence summary of why this is a strong match",
  "fit_reasons": [
    "Specific skill/experience that directly matches a JD requirement",
    "Project or achievement that proves capability for this role",
    "Relevant background that makes candidate stand out"
  ],
  "gaps": ["Only real gaps — skills explicitly REQUIRED in JD that candidate lacks"],
  "dealbreaker": false,
  "confidence": "High",
  "recommendation": "One clear sentence — apply or skip and why"
}}

confidence must be: High, Medium, or Low
dealbreaker: true only if a REQUIRED skill is completely missing"""

        try:
            text = call_llm_sonnet(self.config, prompt, max_tokens=700)
            text = text.strip()
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                text = text[start:end]
            data = json.loads(text)

            if data.get("dealbreaker", False) or data.get("confidence") == "Low":
                return None

            job["stars"] = int(data.get("stars", job["stars"]))
            job["match_score"] = job["stars"] * 2
            job["why_shortlisted"] = data.get("why_shortlisted", "")
            job["fit_reasons"] = data.get("fit_reasons", [])
            job["gaps"] = data.get("gaps", [])
            job["confidence"] = data.get("confidence", "Medium")
            job["recommendation"] = data.get("recommendation", "")
            return job
        except Exception as e:
            print(f"  [Gate3:{job.get('company','?')}] error: {e}")
            job["why_shortlisted"] = job.get("match_reason", "")
            job["fit_reasons"] = []
            job["gaps"] = []
            job["confidence"] = "Medium"
            job["recommendation"] = "Review manually"
            return job
