"""
ResearchAgent — company intelligence for personalised cover letters.
Sources (all free, no auth): DuckDuckGo, GitHub, HN Algolia.
Results cached in Supabase for 7 days to conserve quota.
Degrades gracefully on any error — tailor still runs without research.
"""

import os
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client
from .base import call_llm_sonnet

_TABLE = "company_research"
_CACHE_DAYS = 7
_HEADERS = {"User-Agent": "JobAgent/2.0 (research bot)"}


class ResearchAgent:
    def __init__(self):
        self._db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    def run(self, company: str, job_title: str = "", config: dict = None) -> str:
        """Return 3-4 sentence research summary. Empty string on any failure."""
        if not company or len(company) < 2:
            return ""
        try:
            cached = self._get_cache(company)
            if cached:
                return cached
            raw = self._fetch(company)
            if not raw.strip():
                return ""
            summary = self._summarise(company, job_title, raw, config or {})
            self._set_cache(company, summary)
            print(f"[ResearchAgent] {company}: research cached")
            return summary
        except Exception as e:
            print(f"[ResearchAgent] {company}: error ({e}) — skipping research")
            return ""

    # ── Cache ──────────────────────────────────────────────────────────────────

    def _get_cache(self, company: str) -> str:
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=_CACHE_DAYS)).isoformat()
            row = (self._db.table(_TABLE)
                   .select("research")
                   .eq("company", company)
                   .gte("researched_at", cutoff)
                   .limit(1)
                   .execute())
            if row.data:
                return row.data[0]["research"]
        except Exception:
            pass
        return ""

    def _set_cache(self, company: str, summary: str):
        try:
            self._db.table(_TABLE).upsert(
                {"company": company, "research": summary,
                 "researched_at": datetime.now(timezone.utc).isoformat()},
                on_conflict="company",
            ).execute()
        except Exception:
            pass

    # ── Data fetchers ──────────────────────────────────────────────────────────

    def _fetch(self, company: str) -> str:
        parts = []
        parts.append(self._ddg(company))
        parts.append(self._github(company))
        parts.append(self._hn(company))
        return "\n\n".join(p for p in parts if p)

    def _ddg(self, company: str) -> str:
        try:
            resp = requests.get(
                "https://api.duckduckgo.com/",
                params={"q": f"{company} engineering tech stack", "format": "json", "no_html": 1},
                headers=_HEADERS, timeout=8,
            )
            data = resp.json()
            abstract = data.get("AbstractText", "")
            related = " | ".join(
                r.get("Text", "") for r in data.get("RelatedTopics", [])[:3]
                if isinstance(r, dict) and r.get("Text")
            )
            return f"DuckDuckGo: {abstract} {related}".strip()
        except Exception:
            return ""

    def _github(self, company: str) -> str:
        try:
            resp = requests.get(
                "https://api.github.com/search/repositories",
                params={"q": f"org:{company.lower().replace(' ','')} OR user:{company.lower().replace(' ','')}",
                        "sort": "stars", "per_page": 3},
                headers={**_HEADERS, "Accept": "application/vnd.github+json"},
                timeout=8,
            )
            items = resp.json().get("items", [])
            if not items:
                return ""
            names = ", ".join(
                f"{r['name']} ({r.get('language','?')}, ★{r.get('stargazers_count',0)})"
                for r in items
            )
            return f"GitHub repos: {names}"
        except Exception:
            return ""

    def _hn(self, company: str) -> str:
        try:
            resp = requests.get(
                "https://hn.algolia.com/api/v1/search",
                params={"query": company, "tags": "story", "hitsPerPage": 3},
                headers=_HEADERS, timeout=8,
            )
            hits = resp.json().get("hits", [])
            if not hits:
                return ""
            titles = " | ".join(h.get("title", "") for h in hits)
            return f"Hacker News mentions: {titles}"
        except Exception:
            return ""

    # ── Summariser ─────────────────────────────────────────────────────────────

    def _summarise(self, company: str, job_title: str, raw: str, config: dict) -> str:
        prompt = f"""Given this raw data about "{company}", write exactly 3-4 sentences
a job applicant targeting a "{job_title}" role needs to know:
- What the company does / focuses on
- Their tech stack or engineering culture (if known)
- Any recent news, funding, or growth signals
- One culture or values signal

Raw data:
{raw[:2000]}

Return ONLY the 3-4 sentences. No headers, no bullets, no preamble."""
        try:
            return call_llm_sonnet(config, prompt, max_tokens=300)
        except Exception:
            return raw[:400]
