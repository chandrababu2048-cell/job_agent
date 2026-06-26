"""
TailorWriterAgent — one LLM call returns tailored resume + cover letter.
Halves quota usage vs calling TailorAgent + WriterAgent separately.
"""

import os
from .base import call_llm_sonnet


class TailorWriterAgent:
    def __init__(self, config, master_resume: str):
        self.config = config
        self.master_resume = master_resume
        self.output_dir = config["resume"]["output_dir"]
        os.makedirs(self.output_dir, exist_ok=True)

    def run(self, job: dict, company_research: str = "", edit_feedback: str = "") -> dict:
        print(f"[TailorWriterAgent] {job['title']} @ {job['company']}")
        result = self._generate(job, company_research, edit_feedback)
        resume_md = result["resume"]
        cover_letter = result["cover_letter"]
        path = self._save(job, resume_md)
        job["tailored_resume"] = resume_md
        job["cover_letter"] = cover_letter
        job["tailored_resume_path"] = path
        return job

    def _generate(self, job: dict, company_research: str, edit_feedback: str) -> dict:
        candidate = self.config.get("candidate", {})
        research_block = ""
        if company_research:
            research_block = f"""
COMPANY INTELLIGENCE (use this to make the cover letter specific):
{company_research}
"""
        edit_block = ""
        if edit_feedback:
            edit_block = f"""
USER FEEDBACK (incorporate this into the revised version):
{edit_feedback}
"""

        prompt = f"""You are an elite technical recruiter. Your output will be used directly — no review, no changes.

MASTER RESUME:
{self.master_resume}

TARGET ROLE:
Title: {job['title']}
Company: {job['company']}
{research_block}
JOB DESCRIPTION:
{job.get('description', '')[:3000]}
{edit_block}
━━━ TASK ━━━

Produce EXACTLY two sections with these exact separators. Nothing before, nothing after.

=== RESUME ===
Rewrite the resume in clean markdown:
- HEADER: keep all contact info exactly as-is
- SUMMARY (3-4 lines): mirror job title + top 2 required skills, most relevant achievement, direct connection to this company's needs
- SKILLS: reorder so JD-required skills appear first; mirror JD keywords exactly
- EXPERIENCE: include ALL employers from master resume — never drop any role; keep names/titles/dates exactly; rewrite 2-3 bullets per role to mirror JD language with measurable outcomes; put most relevant bullets first
- PROJECTS: include ALL projects from master resume — never drop any; rewrite bullets to use JD keywords truthfully
- EDUCATION & CERTS: keep unchanged
Rules: every fact from master resume only — never invent; never remove any employer or project; mirror JD keywords naturally; target 90%+ ATS match

=== COVER LETTER ===
3 paragraphs, max 220 words total:
- Para 1 (hook): ONE specific thing about this company/role using the company intelligence above; reference a specific JD requirement; NO "I am excited to apply" or generic openers
- Para 2 (evidence): exactly 2 concrete achievements from the resume with numbers that match what this JD asks for; mirror JD language naturally
- Para 3 (close): what specifically you bring to this team; sign off with full name: {candidate.get('name', 'Chandrababu Naidu Anakapalli')}
Rules: sound like a real human; no buzzwords (passionate/team player/hardworking/synergy); every claim backed by the resume

Return ONLY the two sections with the exact separators. No preamble, no explanation."""

        try:
            raw = call_llm_sonnet(self.config, prompt, max_tokens=5000)
        except Exception as e:
            print(f"[TailorWriterAgent] LLM error: {e} — using master resume + template cover")
            return {
                "resume": self.master_resume,
                "cover_letter": self._fallback_cover(job, candidate),
            }

        return self._parse(raw, job, candidate)

    def _parse(self, raw: str, job: dict, candidate: dict) -> dict:
        resume, cover = "", ""
        if "=== RESUME ===" in raw and "=== COVER LETTER ===" in raw:
            parts = raw.split("=== COVER LETTER ===", 1)
            resume = parts[0].split("=== RESUME ===", 1)[-1].strip()
            cover = parts[1].strip()
        elif "=== RESUME ===" in raw:
            resume = raw.split("=== RESUME ===", 1)[-1].strip()
            cover = self._fallback_cover(job, candidate)
        else:
            resume = self.master_resume
            cover = raw.strip() if len(raw) < 1000 else self._fallback_cover(job, candidate)

        if len(resume) < 200:
            resume = self.master_resume
        return {"resume": resume, "cover_letter": cover}

    def _fallback_cover(self, job: dict, candidate: dict) -> str:
        return (
            f"Dear Hiring Team,\n\n"
            f"I am applying for the {job.get('title')} role at {job.get('company')}. "
            f"My background in full-stack engineering, AI/ML, and .NET development "
            f"makes me a strong fit for this position.\n\n"
            f"I would welcome the opportunity to discuss how my experience can contribute "
            f"to your team.\n\nBest regards,\n"
            f"{candidate.get('name', 'Chandrababu Naidu Anakapalli')}"
        )

    def _save(self, job: dict, content: str) -> str:
        safe = lambda s: "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:35]
        filename = f"{safe(job.get('company','unknown'))}_{safe(job.get('title','role'))}.md"
        path = os.path.join(self.output_dir, filename)
        with open(path, "w") as f:
            f.write(content)
        return path
