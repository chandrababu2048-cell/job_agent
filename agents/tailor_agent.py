import os
from .base import call_llm_sonnet


class TailorAgent:
    def __init__(self, config, master_resume):
        self.config = config
        self.master_resume = master_resume
        self.output_dir = config["resume"]["output_dir"]

    def run(self, job):
        print(f"[TailorAgent] Tailoring resume: {job['title']} at {job['company']}")
        tailored = self._tailor(job)
        path = self._save(job, tailored)
        job["tailored_resume"] = tailored
        job["tailored_resume_path"] = path
        return job

    def _tailor(self, job):
        candidate = self.config.get("candidate", {})
        prompt = f"""You are an elite technical recruiter and resume writer with 15+ years placing engineers at top companies. Your job is to transform this resume into a perfectly tailored, ATS-optimized document that will pass automated screening and impress a hiring manager.

MASTER RESUME:
{self.master_resume}

TARGET ROLE:
Title: {job['title']}
Company: {job['company']}
Work Type: {job.get('work_type', 'Unknown')}

JOB DESCRIPTION:
{job['description'][:3000]}

━━━ YOUR TASK ━━━

Step 1 — Extract from the JD:
• Required skills (must-have)
• Preferred skills (nice-to-have)
• Key responsibilities
• Seniority signals (years of exp, scope)

Step 2 — Rewrite the resume with these rules:

HEADER: Keep all contact info exactly as-is.

SUMMARY (3-4 lines):
• Line 1: Mirror the exact job title + top 2 required skills from JD
• Line 2: Highlight the candidate's most relevant achievement for this role
• Line 3: Connect their background directly to what this company needs
• Line 4: One forward-looking statement about what they bring

TECHNICAL SKILLS:
• Reorder skill categories so JD-required skills appear first
• Bold or front-load the exact keywords from the JD within each category
• Add any skills from the JD that the candidate genuinely has but didn't list

EXPERIENCE (most important section):
• Keep all employer names, titles, dates exactly as-is (never fabricate)
• For each role, rewrite the 2-3 most relevant bullets to directly mirror JD language
• Format: Strong action verb + specific technology/method + measurable outcome
• If the JD mentions a metric (e.g., "reduce latency by 30%"), find analogous achievements in the resume and frame them with numbers
• Move the most JD-relevant bullets to the top of each role

PROJECTS:
• Only include projects relevant to this job
• Rewrite bullets to use exact JD keywords where truthful
• If a project directly maps to a JD requirement, make that connection explicit

EDUCATION & CERTS: Keep as-is, no changes needed.

STRICT RULES:
✓ Every fact must come from the master resume — never invent experience
✓ Mirror JD keywords naturally (not keyword-stuffing)
✓ Target 90%+ ATS match for the required skills
✓ Keep the same markdown structure as the master resume
✓ Maximum 1 page worth of content per major section

Return ONLY the tailored resume in clean markdown. No explanations, no preamble."""

        try:
            return call_llm_sonnet(self.config, prompt, max_tokens=4096)
        except Exception as e:
            print(f"[TailorAgent] Error: {e}")
            return self.master_resume

    def _save(self, job, content):
        os.makedirs(self.output_dir, exist_ok=True)
        safe = lambda s: "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:35]
        filename = f"{safe(job['company'])}_{safe(job['title'])}.md"
        path = os.path.join(self.output_dir, filename)
        with open(path, "w") as f:
            f.write(content)
        return path
