"""
TailorWriterAgent — genius-mode resume tailoring targeting 92-94% ATS score.

Flow:
  1. Extract exact keywords from JD (haiku call — cheap)
  2. Tailor resume + cover letter with keyword injection rules (sonnet call)
  3. Score against keyword list (Python — zero cost)
  4. If score < 92 → one retry with gap list injected (sonnet call)
  5. Generate PDF
"""

import os
import json
import re
from .base import call_llm_sonnet, call_llm_haiku
from . import ats_scorer


class TailorWriterAgent:
    def __init__(self, config, master_resume: str):
        self.config        = config
        self.master_resume = master_resume
        self.output_dir    = config["resume"]["output_dir"]
        os.makedirs(self.output_dir, exist_ok=True)

    def run(self, job: dict, company_research: str = "", edit_feedback: str = "") -> dict:
        print(f"[TailorWriterAgent] {job['title']} @ {job['company']}")

        jd = job.get("description", "")

        # ── Step 1: extract keywords ───────────────────────────────────────────
        keywords = self._extract_keywords(jd)
        print(f"[TailorWriterAgent] {len(keywords)} keywords extracted from JD")

        # ── Step 2: tailor with keyword rules ─────────────────────────────────
        result = self._generate(job, keywords, company_research, edit_feedback)
        resume_md = result["resume"]
        cover     = result["cover_letter"]

        # ── Step 3: score ──────────────────────────────────────────────────────
        score, missing = ats_scorer.score(resume_md, keywords)
        print(f"[TailorWriterAgent] ATS score: {score}% ({len(missing)} missing)")

        # ── Step 4: retry if below 92% ────────────────────────────────────────
        if score < 92 and missing:
            master_lower = self.master_resume.lower()
            # Only retry with keywords that exist in the master resume
            # Never force keywords the candidate doesn't actually have (no stuffing)
            can_add  = [k for k in missing if k.lower() in master_lower]
            wont_add = [k for k in missing if k.lower() not in master_lower]
            if wont_add:
                print(f"[TailorWriterAgent] Skipping {len(wont_add)} keywords not in candidate background: {wont_add[:8]}")
            if can_add:
                print(f"[TailorWriterAgent] Surgically adding {len(can_add)} truthful keywords…")
                result = self._retry(job, resume_md, keywords, can_add[:12])
                if result["resume"] and len(result["resume"]) > 300:
                    resume_md = self._ensure_header(result["resume"])
            score2, missing2 = ats_scorer.score(resume_md, keywords)
            print(f"[TailorWriterAgent] ATS score after retry: {score2}% ({len(missing2)} missing)")

        # ── Step 5: save + PDF ─────────────────────────────────────────────────
        path = self._save(job, resume_md)
        pdf_path = self._make_pdf(job, resume_md, path)

        job["tailored_resume"]      = resume_md
        job["cover_letter"]         = cover
        job["tailored_resume_path"] = pdf_path or path
        job["ats_score"]            = score
        return job

    # ── Keyword extraction ─────────────────────────────────────────────────────

    def _extract_keywords(self, jd: str) -> list[str]:
        """Extract exact-match keywords from JD. Uses haiku (cheap) + pattern fallback."""
        # Pattern-based extraction (zero cost, always runs)
        py_keywords = ats_scorer.extract_keywords(jd)

        # LLM top-up: ask for additional phrases patterns missed
        prompt = f"""Extract every technical keyword and important phrase from this job description.
Return ONLY a JSON array of strings — exact phrases as written in the JD.
Include: technologies, frameworks, tools, methodologies, architectural patterns, soft-skill phrases.
Max 40 items. No explanations.

JD:
{jd[:2000]}

Output example: ["Python", "distributed systems", "CI/CD", "REST API", "PostgreSQL"]"""

        try:
            raw = call_llm_haiku(self.config, prompt, max_tokens=512)
            # Parse JSON array
            match = re.search(r'\[.*?\]', raw, re.DOTALL)
            if match:
                llm_kws = json.loads(match.group(0))
                llm_kws = [k.strip().lower() for k in llm_kws if isinstance(k, str) and len(k) >= 2]
                # Merge with pattern-based list
                merged = list(dict.fromkeys(py_keywords + llm_kws))
                return merged[:60]
        except Exception as e:
            print(f"[TailorWriterAgent] Keyword extraction LLM error: {e} — using pattern-only")

        return py_keywords

    # ── Main generation ────────────────────────────────────────────────────────

    def _generate(self, job: dict, keywords: list, company_research: str, edit_feedback: str) -> dict:
        candidate    = self.config.get("candidate", {})
        kw_str       = ", ".join(keywords[:50])
        research_blk = f"\nCOMPANY INTELLIGENCE:\n{company_research}\n" if company_research else ""
        edit_blk     = f"\nUSER FEEDBACK (must incorporate):\n{edit_feedback}\n" if edit_feedback else ""

        prompt = f"""You are an elite ATS optimization specialist. Your resume must score 92-94% on ATS scanners.

MASTER RESUME (source of all facts — never invent anything):
{self.master_resume}

TARGET ROLE:
Title: {job['title']}
Company: {job['company']}
{research_blk}
JOB DESCRIPTION:
{job.get('description','')[:3000]}
{edit_blk}

━━━ MANDATORY KEYWORD LIST (extracted from JD) ━━━
{kw_str}

━━━ ATS RULES — FOLLOW EXACTLY ━━━

RULE 1 — KEYWORD COVERAGE (most important):
Every keyword in the list above MUST appear at least ONCE in the resume.
High-importance keywords (technologies, frameworks) MUST appear 2-3 times
across different sections (summary + skills + bullet).

RULE 2 — SUMMARY (3-4 sentences MAX):
• Sentence 1: Open with what you DO and your years of experience + top 2 JD technologies — NOT "I am excited" or "I leverage" or "As a X"
  GOOD: "Software Engineer with 4 years building distributed systems and REST APIs at Citibank and Datara."
  BAD: "As a Senior Software Engineer, I leverage my expertise..." or "I am excited to bring my skills..."
• Sentence 2: Most impressive quantified achievement directly relevant to this JD
• Sentence 3: What specifically you'll do at {job['company']} — use their actual product/mission
• No more than 4 sentences total. No buzzwords. No "I am excited".

RULE 3 — SKILLS SECTION:
• Reorder categories so the most JD-relevant ones come first
• Every technology in the keyword list that the candidate knows MUST appear here
• Use exact spelling from JD (e.g. if JD says "Node.js" don't write "NodeJS")
• Also add process keywords the candidate does but may not have listed: "code reviews", "system design",
  "unit testing", "integration testing", "observability", "logging", "monitoring" — if JD mentions them

RULE 4 — EXPERIENCE BULLETS:
• Keep ALL employers, titles, dates exactly as master resume (never fabricate)
• For each role, rewrite bullets using this formula:
  [JD action verb] + [specific JD technology] + [measurable outcome with number]
• Every bullet must contain at least 1 keyword from the list
• Put the most JD-relevant bullets first in each role
• Include ALL roles — never drop any employer

RULE 5 — PROJECTS:
• Include ALL projects from master resume
• Rewrite each bullet to use JD keywords naturally where truthful
• Add GitHub URL after each project title: (github.com/chandrababu2048-cell/job_agent), (github.com/chandrababu2048-cell/EduBridge)

RULE 6 — FORMATTING:
• Use this exact header format (preserve YAML keys — PDFAgent parses them):
  name: Chandrababu Naidu Anakapalli
  location: Bridgeport, CT
  phone: 203-814-5534
  email: chandrababunaidu2048@gmail.com
  linkedin: linkedin.com/in/chandra-a-084825244
  github: github.com/chandrababu2048-cell
• Section headers: ## SUMMARY, ## SKILLS, ## EXPERIENCE, ## PROJECTS, ## EDUCATION & CERTS
• Job entry format:
  ### Company Name
  **Title | Start – End**
  - bullet

━━━ OUTPUT FORMAT ━━━

=== RESUME ===
[full tailored resume in markdown]

=== COVER LETTER ===
[3 paragraphs, max 220 words, NO generic openers]
Para 1: ONE specific thing about {job['company']}'s product/mission + reference a specific JD requirement
Para 2: 2 concrete achievements with numbers matching JD asks
Para 3: what you specifically bring + sign off: {candidate.get('name','Chandrababu Naidu Anakapalli')}

Return ONLY the two sections. No preamble, no explanation."""

        try:
            raw = call_llm_sonnet(self.config, prompt, max_tokens=5000)
            return self._parse(raw, job, candidate)
        except Exception as e:
            print(f"[TailorWriterAgent] LLM error: {e}")
            return {"resume": self.master_resume, "cover_letter": self._fallback_cover(job, candidate)}

    # ── Retry with missing keywords ────────────────────────────────────────────

    def _retry(self, job: dict, current_resume: str, keywords: list, missing: list) -> dict:
        candidate = self.config.get("candidate", {})
        missing_str = ", ".join(missing)

        prompt = f"""This resume is missing some ATS keywords. Add ONLY the ones that truthfully apply to this candidate.

CURRENT RESUME:
{current_resume}

MISSING KEYWORDS TO ADD (only where genuinely applicable):
{missing_str}

SURGICAL RULES — READ CAREFULLY:
1. Only add a keyword if it truthfully fits — do NOT force Kafka/Spark/Flink into a banking role
2. Add to the SKILLS section first (e.g. add "code reviews" under Tools, "system design" under Backend)
3. If a keyword fits a bullet naturally, rewrite that bullet to include it
4. DO NOT add more than 1-2 new keywords per bullet — no keyword stuffing
5. Keep ALL facts, employers, titles, dates exactly as-is
6. Keep the same markdown structure
7. The summary: only add keywords if they fit without making it unnatural

Return ONLY the updated resume in markdown. No preamble, no explanation."""

        try:
            raw = call_llm_sonnet(self.config, prompt, max_tokens=4500)
            # Strip any preamble
            if "name:" in raw[:200] or "# " in raw[:50]:
                return {"resume": raw.strip(), "cover_letter": ""}
            # If it returned the full structure accidentally
            if "=== RESUME ===" in raw:
                resume = raw.split("=== RESUME ===", 1)[-1].split("=== COVER LETTER ===")[0].strip()
                return {"resume": resume, "cover_letter": ""}
            return {"resume": raw.strip(), "cover_letter": ""}
        except Exception as e:
            print(f"[TailorWriterAgent] Retry LLM error: {e}")
            return {"resume": current_resume, "cover_letter": ""}

    # ── Parse LLM output ───────────────────────────────────────────────────────

    def _parse(self, raw: str, job: dict, candidate: dict) -> dict:
        resume, cover = "", ""
        if "=== RESUME ===" in raw and "=== COVER LETTER ===" in raw:
            parts  = raw.split("=== COVER LETTER ===", 1)
            resume = parts[0].split("=== RESUME ===", 1)[-1].strip()
            cover  = parts[1].strip()
        elif "=== RESUME ===" in raw:
            resume = raw.split("=== RESUME ===", 1)[-1].strip()
            cover  = self._fallback_cover(job, candidate)
        else:
            resume = self.master_resume
            cover  = raw.strip() if len(raw) < 800 else self._fallback_cover(job, candidate)

        if len(resume) < 300:
            resume = self.master_resume

        # If LLM dropped the YAML header, prepend it from master resume
        resume = self._ensure_header(resume)

        return {"resume": resume, "cover_letter": cover}

    def _ensure_header(self, resume: str) -> str:
        """Prepend YAML contact header if LLM dropped it."""
        yaml_keys = ("name:", "location:", "phone:", "email:", "linkedin:", "github:")
        first200 = resume[:200]
        if any(k in first200 for k in yaml_keys):
            return resume  # already present

        # Extract header lines from master_resume
        header_lines = []
        for line in self.master_resume.splitlines():
            stripped = line.strip()
            if stripped == "---" and header_lines:
                break
            if any(stripped.startswith(k) for k in yaml_keys):
                header_lines.append(line)

        if header_lines:
            header = "\n".join(header_lines)
            return header + "\n\n---\n\n" + resume
        return resume

    # ── PDF generation ─────────────────────────────────────────────────────────

    def _make_pdf(self, job: dict, resume_md: str, md_path: str) -> str:
        try:
            from .pdf_agent import PDFAgent
            pdf_path = md_path.replace(".md", ".pdf")
            PDFAgent().generate(resume_md, pdf_path)
            print(f"[TailorWriterAgent] PDF: {pdf_path}")
            return pdf_path
        except Exception as e:
            print(f"[TailorWriterAgent] PDF error: {e}")
            return ""

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _save(self, job: dict, content: str) -> str:
        safe = lambda s: "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:35]
        filename = f"{safe(job.get('company','unknown'))}_{safe(job.get('title','role'))}.md"
        path = os.path.join(self.output_dir, filename)
        with open(path, "w") as f:
            f.write(content)
        return path

    def _fallback_cover(self, job: dict, candidate: dict) -> str:
        return (
            f"Dear Hiring Team,\n\n"
            f"I am applying for the {job.get('title')} role at {job.get('company')}. "
            f"My background in full-stack engineering, AI/ML integration, and .NET development "
            f"makes me a strong fit for this position.\n\n"
            f"I look forward to discussing how my experience can contribute to your team.\n\n"
            f"Best regards,\n{candidate.get('name','Chandrababu Naidu Anakapalli')}"
        )
