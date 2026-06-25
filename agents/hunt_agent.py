import os
import re
import hashlib
import requests
import feedparser
import concurrent.futures
from datetime import datetime, timezone
from bs4 import BeautifulSoup


def _now():
    return datetime.now(timezone.utc).isoformat()


# ─── Gate 1: hard rules applied to every raw job before any LLM call ──────────

_EXCLUDE_TITLE_WORDS = {
    "vp", "vice president", "c-level", "cto", "ceo", "coo", "ciso",
    "director", "principal architect", "managing director", "partner",
    "staff architect",
}
_EXCLUDE_DESC_WORDS = {"security clearance", "top secret", "ts/sci", "polygraph"}
_SPAM_COMPANIES = {"", "n/a", "confidential"}


def _gate1_pass(job, salary_min, exclude_keywords):
    """Return True only if the job clears all hard rules (no LLM needed)."""
    title_lower = job.get("title", "").lower()
    desc_lower = job.get("description", "").lower()
    company = job.get("company", "").strip().lower()

    # Must have a company name
    if company in _SPAM_COMPANIES or len(company) < 2:
        return False

    # Description must be substantial (not a placeholder)
    # LinkedIn cards only carry "Title at Company" so use a lower bar for them
    min_desc = 50 if job.get("source") == "LinkedIn" else 150
    if len(job.get("description", "")) < min_desc:
        return False

    # No executive titles
    if any(w in title_lower for w in _EXCLUDE_TITLE_WORDS):
        return False

    # No clearance requirements
    if any(w in desc_lower for w in _EXCLUDE_DESC_WORDS):
        return False

    # Config-level keyword exclusions
    if any(kw.lower() in title_lower for kw in exclude_keywords):
        return False

    # Salary floor: only reject when salary_max is listed AND clearly below floor
    sal_max = job.get("salary_max")
    if sal_max and sal_max < salary_min * 0.85:
        return False

    return True


def _job_hash(job):
    """Stable dedup key: normalized company + title across sources."""
    company = re.sub(r"[^a-z0-9]", "", job.get("company", "").lower())
    title = re.sub(r"[^a-z0-9]", "", job.get("title", "").lower())
    return hashlib.md5(f"{company}|{title}".encode()).hexdigest()


# ─── HuntAgent ─────────────────────────────────────────────────────────────────

class HuntAgent:
    def __init__(self, config):
        self.config = config
        self.titles = config["job_search"]["titles"]
        self.keywords = config["job_search"]["keywords"]
        self.salary_min = config["job_search"].get("salary_min", 0)
        self.exclude_kw = config["job_search"].get("exclude_keywords", [])
        self.adzuna_app_id = os.environ.get("ADZUNA_APP_ID", "")
        self.adzuna_api_key = os.environ.get("ADZUNA_API_KEY", "")
        self.brave_api_key = os.environ.get("BRAVE_API_KEY", "")

    def run(self):
        print("[HuntAgent] Searching all sources in parallel…")

        tasks = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            # Title-specific sources
            for title in self.titles:
                tasks[pool.submit(self._linkedin, title)]    = f"LinkedIn:{title}"
                if self.adzuna_app_id:
                    tasks[pool.submit(self._adzuna, title)] = f"Adzuna:{title}"

            # Keyword/category sources (search once, filter by keyword)
            tasks[pool.submit(self._remotive)]       = "Remotive"
            tasks[pool.submit(self._remoteok)]       = "RemoteOK"
            tasks[pool.submit(self._weworkremotely)] = "WeWorkRemotely"
            tasks[pool.submit(self._themuse)]        = "TheMuse"
            tasks[pool.submit(self._arbeitnow)]      = "Arbeitnow"
            tasks[pool.submit(self._jobicy)]         = "Jobicy"
            tasks[pool.submit(self._workingnomads)]  = "WorkingNomads"

            # Brave Search — searches real career sites (Greenhouse/Lever/Ashby)
            if self.brave_api_key:
                for title in self.titles:
                    tasks[pool.submit(self._brave_search, title)] = f"Brave:{title}"

            raw = []
            for future in concurrent.futures.as_completed(tasks):
                source = tasks[future]
                try:
                    results = future.result()
                    raw.extend(results)
                    print(f"  [{source}] {len(results)} raw jobs")
                except Exception as e:
                    print(f"  [{source}] failed: {e}")

        # Cross-source dedup by company+title hash BEFORE Gate 1
        seen_hashes: set[str] = set()
        unique = []
        seen_ids: set[str] = set()
        for job in raw:
            jid = job.get("id", "")
            h = _job_hash(job)
            if jid in seen_ids or h in seen_hashes:
                continue
            seen_ids.add(jid)
            seen_hashes.add(h)
            unique.append(job)

        # Gate 1: hard rules
        passed = [j for j in unique if _gate1_pass(j, self.salary_min, self.exclude_kw)]
        rejected = len(unique) - len(passed)

        print(f"[HuntAgent] {len(raw)} raw → {len(unique)} unique → "
              f"{len(passed)} passed Gate 1 ({rejected} rejected by hard rules)")
        return passed

    # ── Source: Jobicy (free JSON API, full descriptions) ────────────────────

    def _jobicy(self):
        try:
            resp = requests.get(
                "https://jobicy.com/?feed=job_feed",
                headers={"User-Agent": "Mozilla/5.0"}, timeout=12,
            )
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)
            jobs = []
            for entry in feed.entries:
                text = (entry.get("title", "") + " " + entry.get("summary", "")).lower()
                if not any(kw.lower() in text for kw in self.keywords):
                    continue
                desc = BeautifulSoup(entry.get("summary", ""), "lxml").get_text(" ", strip=True)
                jobs.append({
                    "id": f"jobicy_{hashlib.md5(entry.get('link','').encode()).hexdigest()[:12]}",
                    "source": "Jobicy",
                    "title": entry.get("title", ""),
                    "company": entry.get("author", entry.get("tags", [{}])[0].get("term", "") if entry.get("tags") else ""),
                    "location": "Remote",
                    "description": desc[:3000],
                    "url": entry.get("link", ""),
                    "salary_min": None,
                    "salary_max": None,
                    "posted_at": entry.get("published", ""),
                    "searched_title": entry.get("title", ""),
                    "fetched_at": _now(),
                })
            return jobs
        except Exception as e:
            print(f"  [Jobicy] {e}")
            return []

    # ── Source: Working Nomads (free JSON API) ────────────────────────────────

    def _workingnomads(self):
        try:
            resp = requests.get(
                "https://www.workingnomads.com/api/exposed_jobs/",
                params={"category": "development"},
                headers={"User-Agent": "Mozilla/5.0"}, timeout=12,
            )
            resp.raise_for_status()
            jobs = []
            for item in resp.json():
                text = (item.get("title", "") + " " + item.get("description", "")).lower()
                if not any(kw.lower() in text for kw in self.keywords):
                    continue
                jobs.append({
                    "id": f"wn_{hashlib.md5(item.get('url','').encode()).hexdigest()[:12]}",
                    "source": "WorkingNomads",
                    "title": item.get("title", ""),
                    "company": item.get("company", ""),
                    "location": "Remote",
                    "description": BeautifulSoup(item.get("description", ""), "lxml").get_text(" ", strip=True)[:3000],
                    "url": item.get("url", ""),
                    "salary_min": None,
                    "salary_max": None,
                    "posted_at": item.get("pub_date", ""),
                    "searched_title": item.get("title", ""),
                    "fetched_at": _now(),
                })
            return jobs
        except Exception as e:
            print(f"  [WorkingNomads] {e}")
            return []

    # ── Source: LinkedIn Jobs Guest API ──────────────────────────────────────

    def _linkedin(self, title):
        url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        params = {
            "keywords": title,
            "location": "United States",
            "geoId": "103644278",
            "f_TPR": "r86400",   # last 24 h
            "position": 1,
            "pageNum": 0,
            "start": 0,
        }
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            jobs = []
            for card in soup.select("li"):
                try:
                    title_el = card.select_one("h3.base-search-card__title")
                    company_el = card.select_one("h4.base-search-card__subtitle")
                    location_el = card.select_one("span.job-search-card__location")
                    link_el = card.select_one("a.base-card__full-link")
                    time_el = card.select_one("time")

                    if not title_el or not company_el or not link_el:
                        continue

                    job_url = link_el.get("href", "").split("?")[0]
                    job_id = f"li_{hashlib.md5(job_url.encode()).hexdigest()[:12]}"

                    jobs.append({
                        "id": job_id,
                        "source": "LinkedIn",
                        "title": title_el.get_text(strip=True),
                        "company": company_el.get_text(strip=True),
                        "location": location_el.get_text(strip=True) if location_el else "United States",
                        "description": f"{title_el.get_text(strip=True)} at {company_el.get_text(strip=True)}. See full JD at link.",
                        "url": job_url,
                        "salary_min": None,
                        "salary_max": None,
                        "posted_at": time_el.get("datetime", "") if time_el else "",
                        "searched_title": title,
                        "fetched_at": _now(),
                    })
                except Exception:
                    continue
            return jobs
        except Exception as e:
            print(f"  [LinkedIn:{title}] {e}")
            return []

    # ── Source: Adzuna (existing, multi-page) ─────────────────────────────────

    def _adzuna(self, title):
        jobs = []
        for page in range(1, 3):
            url = f"https://api.adzuna.com/v1/api/jobs/us/search/{page}"
            params = {
                "app_id": self.adzuna_app_id,
                "app_key": self.adzuna_api_key,
                "what": title,
                "results_per_page": 50,
                "sort_by": "date",
                "max_days_old": 2,
            }
            try:
                resp = requests.get(url, params=params, timeout=10)
                resp.raise_for_status()
                for item in resp.json().get("results", []):
                    jobs.append({
                        "id": f"adzuna_{item.get('id','')}",
                        "source": "Adzuna",
                        "title": item.get("title", ""),
                        "company": item.get("company", {}).get("display_name", ""),
                        "location": item.get("location", {}).get("display_name", ""),
                        "description": item.get("description", ""),
                        "url": item.get("redirect_url", ""),
                        "salary_min": item.get("salary_min"),
                        "salary_max": item.get("salary_max"),
                        "posted_at": item.get("created", ""),
                        "searched_title": title,
                        "fetched_at": _now(),
                    })
            except Exception as e:
                print(f"  [Adzuna p{page}:{title}] {e}")
        return jobs

    # ── Source: Remotive (remote tech, free JSON) ─────────────────────────────

    def _remotive(self):
        categories = ["software-dev", "data", "devops-sysadmin"]
        jobs = []
        for cat in categories:
            try:
                resp = requests.get(
                    f"https://remotive.com/api/remote-jobs?category={cat}",
                    timeout=12,
                )
                resp.raise_for_status()
                for item in resp.json().get("jobs", []):
                    text = (item.get("title", "") + " " + item.get("description", "")).lower()
                    if not any(kw.lower() in text for kw in self.keywords):
                        continue
                    jobs.append({
                        "id": f"remotive_{item.get('id','')}",
                        "source": "Remotive",
                        "title": item.get("title", ""),
                        "company": item.get("company_name", ""),
                        "location": item.get("candidate_required_location", "Remote"),
                        "description": BeautifulSoup(item.get("description", ""), "lxml").get_text(" ", strip=True)[:3000],
                        "url": item.get("url", ""),
                        "salary_min": None,
                        "salary_max": None,
                        "posted_at": item.get("publication_date", ""),
                        "searched_title": item.get("title", ""),
                        "fetched_at": _now(),
                    })
            except Exception as e:
                print(f"  [Remotive:{cat}] {e}")
        return jobs

    # ── Source: RemoteOK (existing) ───────────────────────────────────────────

    def _remoteok(self):
        try:
            resp = requests.get(
                "https://remoteok.com/api",
                headers={"User-Agent": "JobAgent/2.0"},
                timeout=15,
            )
            resp.raise_for_status()
            jobs = []
            for item in resp.json():
                if not isinstance(item, dict) or "id" not in item:
                    continue
                text = (item.get("position", "") + " " + item.get("description", "")).lower()
                if not any(kw.lower() in text for kw in self.keywords):
                    continue
                jobs.append({
                    "id": f"rok_{item['id']}",
                    "source": "RemoteOK",
                    "title": item.get("position", ""),
                    "company": item.get("company", ""),
                    "location": "Remote",
                    "description": item.get("description", ""),
                    "url": item.get("url", ""),
                    "salary_min": None,
                    "salary_max": None,
                    "posted_at": item.get("date", ""),
                    "searched_title": item.get("position", ""),
                    "fetched_at": _now(),
                })
            return jobs
        except Exception as e:
            print(f"  [RemoteOK] {e}")
            return []

    # ── Source: WeWorkRemotely RSS ────────────────────────────────────────────

    def _weworkremotely(self):
        feeds = [
            "https://weworkremotely.com/categories/remote-programming-jobs.rss",
            "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
            "https://weworkremotely.com/categories/remote-data-science-jobs.rss",
        ]
        jobs = []
        for feed_url in feeds:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries:
                    text = (entry.get("title", "") + " " + entry.get("summary", "")).lower()
                    if not any(kw.lower() in text for kw in self.keywords):
                        continue
                    raw_title = entry.get("title", "")
                    company, title = "", raw_title
                    if ": " in raw_title:
                        company, title = raw_title.split(": ", 1)
                    jobs.append({
                        "id": f"wwr_{hashlib.md5(entry.get('link','').encode()).hexdigest()[:12]}",
                        "source": "WeWorkRemotely",
                        "title": title.strip(),
                        "company": company.strip(),
                        "location": "Remote",
                        "description": BeautifulSoup(entry.get("summary", ""), "lxml").get_text(" ", strip=True),
                        "url": entry.get("link", ""),
                        "salary_min": None,
                        "salary_max": None,
                        "posted_at": entry.get("published", ""),
                        "searched_title": title,
                        "fetched_at": _now(),
                    })
            except Exception as e:
                print(f"  [WWR] {e}")
        return jobs

    # ── Source: The Muse (free JSON API, no auth) ─────────────────────────────

    def _themuse(self):
        categories = ["Software Engineer", "Data Science", "Data Engineering"]
        jobs = []
        for cat in categories:
            try:
                resp = requests.get(
                    "https://www.themuse.com/api/public/jobs",
                    params={"category": cat, "page": 0, "descending": "true"},
                    timeout=12,
                )
                resp.raise_for_status()
                for item in resp.json().get("results", []):
                    desc = BeautifulSoup(item.get("contents", ""), "lxml").get_text(" ", strip=True)
                    text = (item.get("name", "") + " " + desc).lower()
                    if not any(kw.lower() in text for kw in self.keywords):
                        continue
                    locations = item.get("locations", [{}])
                    loc = locations[0].get("name", "Remote") if locations else "Remote"
                    jobs.append({
                        "id": f"muse_{item.get('id','')}",
                        "source": "TheMuse",
                        "title": item.get("name", ""),
                        "company": item.get("company", {}).get("name", ""),
                        "location": loc,
                        "description": desc[:3000],
                        "url": item.get("refs", {}).get("landing_page", ""),
                        "salary_min": None,
                        "salary_max": None,
                        "posted_at": item.get("publication_date", ""),
                        "searched_title": item.get("name", ""),
                        "fetched_at": _now(),
                    })
            except Exception as e:
                print(f"  [TheMuse:{cat}] {e}")
        return jobs

    # ── Source: Arbeitnow (free JSON, no auth, global remote) ─────────────────

    def _arbeitnow(self):
        try:
            resp = requests.get(
                "https://www.arbeitnow.com/api/job-board-api",
                timeout=12,
            )
            resp.raise_for_status()
            jobs = []
            for item in resp.json().get("data", []):
                text = (item.get("title", "") + " " + item.get("description", "")).lower()
                if not any(kw.lower() in text for kw in self.keywords):
                    continue
                jobs.append({
                    "id": f"arb_{hashlib.md5(item.get('slug','').encode()).hexdigest()[:12]}",
                    "source": "Arbeitnow",
                    "title": item.get("title", ""),
                    "company": item.get("company_name", ""),
                    "location": "Remote" if item.get("remote") else item.get("location", ""),
                    "description": BeautifulSoup(item.get("description", ""), "lxml").get_text(" ", strip=True)[:3000],
                    "url": item.get("url", ""),
                    "salary_min": None,
                    "salary_max": None,
                    "posted_at": str(item.get("created_at", "")),
                    "searched_title": item.get("title", ""),
                    "fetched_at": _now(),
                })
            return jobs
        except Exception as e:
            print(f"  [Arbeitnow] {e}")
            return []

    # ── Source: Brave Search (career sites — Greenhouse/Lever/Ashby) ──────────

    def _brave_search(self, title):
        """Search real company career pages via Brave Search API (free 2k/month)."""
        query = (
            f'"{title}" remote job '
            f'(site:boards.greenhouse.io OR site:jobs.lever.co OR '
            f'site:jobs.ashbyhq.com OR site:apply.workable.com OR site:careers.smartrecruiters.com)'
        )
        try:
            resp = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": 20, "search_lang": "en", "country": "us"},
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": self.brave_api_key,
                },
                timeout=12,
            )
            resp.raise_for_status()
            results = resp.json().get("web", {}).get("results", [])
            jobs = []
            for r in results:
                url   = r.get("url", "")
                title_text = r.get("title", "")
                desc  = r.get("description", "") or r.get("extra_snippets", [""])[0]

                # Extract company from URL pattern
                company = self._company_from_ats_url(url)
                if not company:
                    continue

                # Clean title — strip " - Company | Greenhouse" suffixes
                job_title = title_text.split(" - ")[0].split(" | ")[0].strip()
                if not job_title:
                    continue

                jobs.append({
                    "id": f"brave_{hashlib.md5(url.encode()).hexdigest()[:12]}",
                    "source": "Brave",
                    "title": job_title,
                    "company": company,
                    "location": "Remote",
                    "description": f"{job_title} at {company}. {desc}"[:3000],
                    "url": url,
                    "salary_min": None,
                    "salary_max": None,
                    "posted_at": "",
                    "searched_title": title,
                    "fetched_at": _now(),
                })
            return jobs
        except Exception as e:
            print(f"  [Brave:{title}] {e}")
            return []

    def _company_from_ats_url(self, url: str) -> str:
        """Extract company name from known ATS URL patterns."""
        import re
        patterns = [
            r"boards\.greenhouse\.io/([^/]+)",
            r"jobs\.lever\.co/([^/]+)",
            r"jobs\.ashbyhq\.com/([^/]+)",
            r"apply\.workable\.com/([^/]+)",
            r"careers\.smartrecruiters\.com/([^/]+)",
        ]
        for pat in patterns:
            m = re.search(pat, url)
            if m:
                return m.group(1).replace("-", " ").replace("_", " ").title()
        return ""
