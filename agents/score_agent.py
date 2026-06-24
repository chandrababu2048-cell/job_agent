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
        # ── Gate 2: batch scoring (5 jobs per API call — 5x fewer requests) ──
        batch_size = 5
        batches = [jobs[i:i+batch_size] for i in range(0, len(jobs), batch_size)]
        print(f"\n[ScoreAgent] Gate 2 — rating {len(jobs)} jobs in {len(batches)} batches "
              f"(threshold: {self.min_stars}★)…")

        gate2_passed = []
        for i, batch in enumerate(batches):
            try:
                results = self._gate2_batch(batch)
                gate2_passed.extend(r for r in results if r)
                if (i + 1) % 10 == 0 or (i + 1) == len(batches):
                    print(f"  [Gate2] {i+1}/{len(batches)} batches done "
                          f"({(i+1)*5}/{len(jobs)} jobs) — {len(gate2_passed)} matches so far",
                          flush=True)
            except Exception as e:
                print(f"  [Gate2 batch {i+1}] error: {e}", flush=True)

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

    # ── Gate 2: batch rating (5 jobs per call) ────────────────────────────────

    def _gate2_batch(self, batch):
        candidate_summary = self.master_resume[:600]
        jobs_text = ""
        for i, job in enumerate(batch, 1):
            jobs_text += (f"\nJOB {i}: {job['title']} at {job['company']}\n"
                          f"{job['description'][:600]}\n")

        prompt = f"""You are a technical recruiter. Rate each job for this candidate 1-5 stars.

CANDIDATE:
{candidate_summary}

{jobs_text}
Rate each job. 4★ = strong match | 5★ = exceptional. Only rate 4+ if genuinely competitive.
work_type: Remote, Hybrid, Onsite, or Check JD

Reply ONLY with a JSON array (no markdown):
[{{"job": 1, "stars": 4, "reason": "Short reason", "work_type": "Remote"}}, ...]"""

        try:
            text = call_llm_haiku(self.config, prompt, max_tokens=400)
            text = text.strip()
            start = text.find("[")
            end   = text.rfind("]") + 1
            if start == -1:
                start = text.find("{")
                end   = text.rfind("}") + 1
                text  = "[" + text[start:end] + "]"
            else:
                text = text[start:end]
            ratings = json.loads(text)

            results = []
            for r in ratings:
                idx = int(r.get("job", 0)) - 1
                if 0 <= idx < len(batch):
                    rating = int(r.get("stars", 0))
                    if rating >= self.min_stars:
                        job = batch[idx]
                        job["stars"]       = rating
                        job["match_score"] = rating * 2
                        job["match_reason"] = r.get("reason", "")
                        job["work_type"]   = r.get("work_type", "Check JD")
                        results.append(job)
            return results
        except Exception as e:
            print(f"  [Gate2 batch] parse error: {e}")
            return []

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
