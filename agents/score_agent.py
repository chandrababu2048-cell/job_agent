import json
import re
import concurrent.futures
from .base import call_llm_sonnet

STAR_ICONS = {5: "⭐⭐⭐⭐⭐", 4: "⭐⭐⭐⭐☆", 3: "⭐⭐⭐☆☆", 2: "⭐⭐☆☆☆", 1: "⭐☆☆☆☆"}

# ── Keyword tiers for zero-API Gate 2 scoring ─────────────────────────────────
# Tier A: core skills (2 pts each) — must match to get 4★+
KEYWORDS_A = {
    "python", "machine learning", "ai", "artificial intelligence", "llm",
    "large language model", "nlp", "deep learning", "data science", "ml",
    ".net", "c#", "react", "sql", "azure", "aws", "cloud",
    "software engineer", "backend", "full stack", "fullstack", "api",
}
# Tier B: supporting skills (1 pt each)
KEYWORDS_B = {
    "typescript", "javascript", "node", "postgresql", "mongodb", "docker",
    "kubernetes", "terraform", "pytorch", "tensorflow", "transformers",
    "genai", "generative ai", "rag", "langchain", "openai", "gpt",
    "neural network", "computer vision", "data engineer", "devops", "ci/cd",
    "rest", "microservices", "django", "fastapi", "next.js", "prompt",
}


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
        # ── Gate 2: keyword scoring (zero API calls — instant) ────────────────
        print(f"\n[ScoreAgent] Gate 2 — keyword scoring {len(jobs)} jobs "
              f"(threshold: {self.min_stars}★, no API calls)…")

        gate2_passed = []
        for job in jobs:
            rated = self._gate2_keyword(job)
            if rated:
                gate2_passed.append(rated)

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

    # ── Gate 2: instant keyword scoring (no API calls) ────────────────────────

    def _gate2_keyword(self, job):
        text = (job.get("title", "") + " " + job.get("description", "")).lower()
        score = 0
        matched_a, matched_b = [], []
        for kw in KEYWORDS_A:
            if kw in text:
                score += 2
                matched_a.append(kw)
        for kw in KEYWORDS_B:
            if kw in text:
                score += 1
                matched_b.append(kw)

        # Map score → stars: 0-3=1★, 4-5=2★, 6-7=3★, 8-11=4★, 12+=5★
        if   score >= 12: star = 5
        elif score >= 8:  star = 4
        elif score >= 6:  star = 3
        elif score >= 4:  star = 2
        else:             star = 1

        if star < self.min_stars:
            return None

        job["stars"]       = star
        job["match_score"] = score
        job["match_reason"] = f"Keyword match: {', '.join(matched_a[:4])}"
        job["work_type"]   = job.get("work_type", "Check JD")
        return job

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
