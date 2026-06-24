from .base import call_llm_sonnet


class WriterAgent:
    def __init__(self, config, master_resume):
        self.config = config
        self.master_resume = master_resume

    def run(self, job):
        print(f"[WriterAgent] Cover letter: {job['title']} at {job['company']}")
        job["cover_letter"] = self._write(job)
        return job

    def _write(self, job):
        candidate = self.config.get("candidate", {})
        prompt = f"""You are writing a cover letter for a senior job application. This letter must feel like it was written by a real person — specific, confident, and direct.

CANDIDATE:
{self.master_resume[:2000]}

TARGET ROLE:
Title: {job['title']}
Company: {job['company']}
Work Type: {job.get('work_type', 'Unknown')}

JOB DESCRIPTION:
{job['description'][:2500]}

━━━ STRUCTURE (3 paragraphs, max 220 words total) ━━━

PARAGRAPH 1 — The Hook (2-3 sentences):
• Open with ONE specific thing about this company or role that genuinely fits this candidate
• Show you read the JD — reference a specific requirement or company detail
• NO generic phrases like "I am excited to apply" or "I came across your posting"

PARAGRAPH 2 — The Evidence (3-4 sentences):
• Pick exactly 2 concrete achievements from the resume that directly address what the JD asks for
• Use numbers wherever possible (built X that handled Y requests, reduced Z by N%)
• Mirror the JD's language naturally

PARAGRAPH 3 — The Close (2 sentences):
• One forward-looking sentence: what specifically you'll bring to this team
• Clean sign-off with full name: {candidate.get('name', 'Chandrababu Naidu Anakapalli')}

STRICT RULES:
✓ Sound like a real human, not a template
✓ Mirror JD language naturally — not copy-paste
✓ Every claim must be backed by something in the resume
✓ No buzzwords: "passionate", "team player", "hardworking", "synergy"
✓ No subject line — return only the letter body

Return ONLY the cover letter text."""

        try:
            return call_llm_sonnet(self.config, prompt, max_tokens=1024)
        except Exception as e:
            print(f"[WriterAgent] Error: {e}")
            return ""
