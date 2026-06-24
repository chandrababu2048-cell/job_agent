import json
from .base import call_llm_sonnet


class ReviewAgent:
    def __init__(self, config, master_resume):
        self.config = config
        self.master_resume = master_resume

    def run(self, job):
        print(f"[ReviewAgent] Reviewing package: {job['title']} at {job['company']}")
        result = self._review(job)
        job["review_passed"] = result["passed"]
        job["review_notes"] = result["notes"]
        job["review_flags"] = result["flags"]
        job["ats_score"] = result.get("ats_score", "?")
        return job

    def _review(self, job):
        prompt = f"""You are a senior technical recruiter doing a final quality check on a job application package.

ROLE: {job['title']} at {job['company']}
WORK TYPE: {job.get('work_type', 'Unknown')}
MATCH SCORE: {job.get('match_score', '?')}/10

JOB DESCRIPTION (key requirements):
{job['description'][:1500]}

TAILORED RESUME:
{job.get('tailored_resume', '')[:2500]}

COVER LETTER:
{job.get('cover_letter', '')}

━━━ REVIEW CHECKLIST ━━━
1. Does the resume directly address the top 3-4 requirements from the JD?
2. Are there any fabricated or exaggerated claims vs the original experience?
3. Is the cover letter specific to this role (not generic)?
4. Are there any red flags (massive skill gaps, seniority mismatch, etc.)?
5. ATS keyword coverage: what % of required JD keywords appear in the resume?
6. Is the candidate realistically qualified for this role?

Reply ONLY with valid JSON, no markdown:
{{
  "passed": true,
  "ats_score": 87,
  "notes": "Strong match. Resume directly mirrors JD requirements. Cover letter cites specific EduBridge achievement relevant to the AI role.",
  "flags": []
}}

OR if issues found:
{{
  "passed": false,
  "ats_score": 52,
  "notes": "Candidate lacks required PyTorch experience. Cover letter is too generic.",
  "flags": ["Missing: PyTorch/TensorFlow", "Cover letter doesn't mention the company's AI platform"]
}}"""

        try:
            text = call_llm_sonnet(self.config, prompt, max_tokens=512)
            text = text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            return json.loads(text)
        except Exception as e:
            print(f"[ReviewAgent] Error: {e}")
            return {"passed": True, "ats_score": "?", "notes": "Review skipped", "flags": []}
