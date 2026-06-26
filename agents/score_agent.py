import re
import concurrent.futures

STAR_ICONS = {5: "⭐⭐⭐⭐⭐", 4: "⭐⭐⭐⭐☆", 3: "⭐⭐⭐☆☆", 2: "⭐⭐☆☆☆", 1: "⭐☆☆☆☆"}

# CORE skills — job must match at least 1 of these or it's rejected outright
KEYWORDS_CORE = {
    "python", "machine learning", "artificial intelligence", "llm",
    "large language model", "nlp", "deep learning", "data science",
    ".net", "c#", "asp.net", "react", "sql", "software engineer",
    "full stack", "fullstack", "ai engineer", "ml engineer",
    "data scientist", "backend engineer",
}
# Tier A: strong matches worth 2 pts each
KEYWORDS_A = {
    "python", "machine learning", "ai", "artificial intelligence", "llm",
    "large language model", "nlp", "deep learning", "data science", "ml",
    ".net", "c#", "react", "sql", "azure", "aws",
    "software engineer", "backend", "full stack", "fullstack", "api",
}
# Tier B: supporting skills worth 1 pt each
KEYWORDS_B = {
    "typescript", "javascript", "node", "postgresql", "mongodb", "docker",
    "pytorch", "tensorflow", "transformers", "generative ai", "rag",
    "langchain", "openai", "gpt", "genai", "neural network",
    "data engineer", "ci/cd", "rest", "microservices", "django",
    "fastapi", "next.js", "prompt", "cloud", "supabase",
}


def stars(n):
    try:
        return STAR_ICONS.get(int(n), "☆☆☆☆☆")
    except (ValueError, TypeError):
        return "⭐⭐⭐⭐☆"


class ScoreAgent:
    """
    Two-gate quality filter — both zero API calls:
      Gate 2 — keyword scoring (instant, no LLM)
      Gate 3 — removed; LLM budget saved for tailor + cover letter
    """

    def __init__(self, config, master_resume):
        self.config = config
        self.master_resume = master_resume
        self.min_stars = config["job_search"].get("min_stars", 4)

    def run(self, jobs):
        # ── Gate 2: instant keyword scoring ───────────────────────────────────
        print(f"\n[ScoreAgent] Scoring {len(jobs)} jobs (keyword, no API)…")

        passed = []
        for job in jobs:
            rated = self._score(job)
            if rated:
                passed.append(rated)

        passed.sort(key=lambda j: j["match_score"], reverse=True)
        top = passed[:10]  # hard cap: 10 per run

        print(f"[ScoreAgent] {len(passed)} rated {self.min_stars}★+ → top {len(top)} selected")
        for j in top:
            print(f"  {stars(j['stars'])} {j['title']} @ {j['company']} "
                  f"[{j.get('work_type','?')}] score={j['match_score']}")

        return top

    def _score(self, job):
        title_lower = job.get("title", "").lower()
        desc_lower  = job.get("description", "").lower()
        text = title_lower + " " + desc_lower

        # Must match at least one core skill — filters out pure DevOps/mobile/infra
        if not any(kw in text for kw in KEYWORDS_CORE):
            return None

        score = 0
        matched = []
        for kw in KEYWORDS_A:
            if kw in text:
                score += 2
                matched.append(kw)
        for kw in KEYWORDS_B:
            if kw in text:
                score += 1
                matched.append(kw)

        # Title bonus: LinkedIn/ZipRecruiter jobs have short descriptions;
        # boost when the JOB TITLE itself names a core skill so they survive scoring
        if any(kw in title_lower for kw in KEYWORDS_CORE):
            score += 6

        if   score >= 12: star = 5
        elif score >= 8:  star = 4
        elif score >= 6:  star = 3
        elif score >= 4:  star = 2
        else:             star = 1

        if star < self.min_stars:
            return None

        job["stars"]          = star
        job["match_score"]    = score
        job["match_reason"]   = f"Matched: {', '.join(matched[:5])}"
        job["why_shortlisted"] = job["match_reason"]
        job["fit_reasons"]    = matched[:5]
        job["gaps"]           = []
        job["confidence"]     = "High" if score >= 12 else "Medium"
        job["recommendation"] = "Apply"
        job["work_type"]      = job.get("work_type", "Check JD")
        return job
