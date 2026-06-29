"""
ApplyAgent — detects ATS type and auto-submits job applications.

Auto-submit (no user needed):
  Greenhouse, Lever, Ashby

Semi-auto (opens browser, user clicks Submit):
  LinkedIn, Indeed, Workday, Unknown
"""

import os
import re
import time


ATS_PATTERNS = {
    "greenhouse": ["boards.greenhouse.io", "boards.eu.greenhouse.io"],
    "lever":      ["jobs.lever.co"],
    "ashby":      ["app.ashbyhq.com", "jobs.ashbyhq.com", "ashby.io"],
    "linkedin":   ["linkedin.com/jobs", "linkedin.com/job"],
    "indeed":     ["indeed.com/job", "indeed.com/viewjob"],
    "workday":    ["myworkdayjobs.com", "workday.com"],
}


class ApplyAgent:

    def __init__(self, config):
        self.config    = config
        self.candidate = config["candidate"]

    def detect_ats(self, url: str) -> str:
        url_lower = url.lower()
        for ats, patterns in ATS_PATTERNS.items():
            if any(p in url_lower for p in patterns):
                return ats
        return "unknown"

    def apply(self, job: dict, resume_pdf_path: str) -> dict:
        """
        Apply to a job. Returns:
          success (bool), method (str), ats (str), notes (str)
        """
        url = job.get("url", "")
        ats = self.detect_ats(url)
        print(f"  [ApplyAgent] ATS detected: {ats} → {url[:60]}")

        result = {"ats": ats, "success": False, "method": "unknown", "notes": ""}

        try:
            if ats == "greenhouse":
                result.update(self._apply_greenhouse(job, resume_pdf_path))
            elif ats == "lever":
                result.update(self._apply_lever(job, resume_pdf_path))
            elif ats == "ashby":
                result.update(self._apply_ashby(job, resume_pdf_path))
            elif ats == "linkedin":
                result.update(self._apply_linkedin(job, resume_pdf_path))
            else:
                result.update(self._open_browser(job))
        except Exception as e:
            result["notes"] = f"Error: {e}"
            result["success"] = False
            print(f"  [ApplyAgent] ✗ {e}")

        return result

    # ── Stealth browser context ────────────────────────────────────────────────

    def _stealth_browser(self, p):
        """Launch Chromium with anti-bot headers so Greenhouse/Lever don't block us."""
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        # Hide webdriver flag
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        return browser, ctx

    def _wait_and_fill(self, page, selector: str, value: str, timeout: int = 3000):
        """Wait for element to appear then fill it."""
        if not value:
            return
        try:
            page.wait_for_selector(selector, timeout=timeout, state="visible")
            el = page.query_selector(selector)
            if el:
                el.click()
                time.sleep(0.2)
                el.fill(str(value))
        except Exception:
            pass

    def _find_submit_btn(self, page):
        """Try many submit button patterns."""
        selectors = [
            "button[type='submit']:not([disabled])",
            "input[type='submit']:not([disabled])",
            "button:has-text('Submit Application')",
            "button:has-text('Submit')",
            "button:has-text('Apply')",
            "button:has-text('Send Application')",
            "[data-qa='btn-submit']",
            "#submit_app",
        ]
        for sel in selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    return btn
            except Exception:
                pass
        return None

    def _upload_resume(self, page, resume_pdf_path: str):
        """Upload resume to first visible file input."""
        if not resume_pdf_path or not os.path.exists(resume_pdf_path):
            return
        try:
            # Try visible file input first, then any file input
            inp = (page.query_selector("input[type='file']:not([style*='display:none'])") or
                   page.query_selector("input[type='file']"))
            if inp:
                inp.set_input_files(resume_pdf_path)
                time.sleep(2)
                print(f"  [ApplyAgent] Resume uploaded")
        except Exception as e:
            print(f"  [ApplyAgent] Resume upload failed: {e}")

    # ── Greenhouse ─────────────────────────────────────────────────────────────

    def _apply_greenhouse(self, job: dict, resume_pdf_path: str) -> dict:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, ctx = self._stealth_browser(p)
            page = ctx.new_page()

            try:
                page.goto(job["url"], timeout=45000, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)

                # Check for bot block
                if "blocked" in page.title().lower() or "captcha" in page.content().lower():
                    browser.close()
                    print(f"  [ApplyAgent] ⚠️  Greenhouse bot-blocked: {job['company']}")
                    return self._open_browser(job)

                first = self.candidate["name"].split()[0]
                last  = self.candidate["name"].split()[-1]

                # Core fields — Greenhouse uses name attributes
                self._wait_and_fill(page, "input[name='first_name']", first)
                self._wait_and_fill(page, "input[name='last_name']",  last)
                self._wait_and_fill(page, "input[name='email']",      self.candidate["email"])
                self._wait_and_fill(page, "input[name='phone']",      self.candidate.get("phone",""))
                self._wait_and_fill(page, "input[name='location']",   self.candidate.get("location",""))

                # LinkedIn / GitHub / website fields
                linkedin_url = f"https://{self.candidate.get('linkedin','')}"
                github_url   = f"https://{self.candidate.get('github','')}"
                self._wait_and_fill(page, "input[name='linkedin_profile']", linkedin_url)
                self._wait_and_fill(page, "input[id*='linkedin' i]",        linkedin_url)
                self._wait_and_fill(page, "input[placeholder*='linkedin' i]", linkedin_url)
                self._wait_and_fill(page, "input[id*='github' i]",          github_url)
                self._wait_and_fill(page, "input[placeholder*='github' i]", github_url)

                # Resume upload
                self._upload_resume(page, resume_pdf_path)

                # Cover letter
                cover = job.get("cover_letter", "")
                if cover:
                    self._wait_and_fill(page, "textarea[name='cover_letter']", cover[:3000])
                    self._wait_and_fill(page, "textarea[id*='cover' i]",       cover[:3000])

                page.wait_for_timeout(1000)
                btn = self._find_submit_btn(page)

                if btn:
                    btn.scroll_into_view_if_needed()
                    page.wait_for_timeout(500)
                    btn.click()
                    page.wait_for_timeout(4000)
                    browser.close()
                    print(f"  [ApplyAgent] ✅ Greenhouse auto-submitted: {job['company']}")
                    return {"success": True, "method": "greenhouse_auto"}

                # Debug: log what's on the page
                print(f"  [ApplyAgent] ⚠️  No submit button found on Greenhouse form ({job['company']})")
                print(f"  [ApplyAgent]    Page title: {page.title()}")
                browser.close()
                return self._open_browser(job)

            except Exception as e:
                try: browser.close()
                except Exception: pass
                raise e

    # ── Lever ──────────────────────────────────────────────────────────────────

    def _apply_lever(self, job: dict, resume_pdf_path: str) -> dict:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, ctx = self._stealth_browser(p)
            page = ctx.new_page()

            try:
                page.goto(job["url"], timeout=45000, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)

                name         = self.candidate["name"]
                linkedin_url = f"https://{self.candidate.get('linkedin','')}"
                github_url   = f"https://{self.candidate.get('github','')}"

                self._wait_and_fill(page, "input[name='name']",                  name)
                self._wait_and_fill(page, "input[placeholder*='Full name' i]",   name)
                self._wait_and_fill(page, "input[placeholder*='Your name' i]",   name)
                self._wait_and_fill(page, "input[name='email']",                 self.candidate["email"])
                self._wait_and_fill(page, "input[placeholder*='email' i]",       self.candidate["email"])
                self._wait_and_fill(page, "input[name='phone']",                 self.candidate.get("phone",""))
                self._wait_and_fill(page, "input[placeholder*='phone' i]",       self.candidate.get("phone",""))
                self._wait_and_fill(page, "input[name='urls[LinkedIn]']",        linkedin_url)
                self._wait_and_fill(page, "input[name='urls[GitHub]']",          github_url)
                self._wait_and_fill(page, "input[placeholder*='linkedin' i]",    linkedin_url)
                self._wait_and_fill(page, "input[placeholder*='github' i]",      github_url)

                self._upload_resume(page, resume_pdf_path)

                cover = job.get("cover_letter", "")
                if cover:
                    self._wait_and_fill(page, "textarea[name='comments']",       cover[:3000])
                    self._wait_and_fill(page, "textarea[placeholder*='cover' i]", cover[:3000])
                    self._wait_and_fill(page, "textarea[placeholder*='letter' i]", cover[:3000])

                page.wait_for_timeout(1000)
                btn = self._find_submit_btn(page)

                if btn:
                    btn.scroll_into_view_if_needed()
                    page.wait_for_timeout(500)
                    btn.click()
                    page.wait_for_timeout(4000)
                    browser.close()
                    print(f"  [ApplyAgent] ✅ Lever auto-submitted: {job['company']}")
                    return {"success": True, "method": "lever_auto"}

                print(f"  [ApplyAgent] ⚠️  No submit button found on Lever form ({job['company']})")
                browser.close()
                return self._open_browser(job)

            except Exception as e:
                try: browser.close()
                except Exception: pass
                raise e

    # ── Ashby ──────────────────────────────────────────────────────────────────

    def _apply_ashby(self, job: dict, resume_pdf_path: str) -> dict:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, ctx = self._stealth_browser(p)
            page = ctx.new_page()

            try:
                page.goto(job["url"], timeout=45000, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)

                first = self.candidate["name"].split()[0]
                last  = self.candidate["name"].split()[-1]

                self._wait_and_fill(page, "input[name='_systemfield_name']",   self.candidate["name"])
                self._wait_and_fill(page, "input[placeholder*='First' i]",     first)
                self._wait_and_fill(page, "input[placeholder*='Last' i]",      last)
                self._wait_and_fill(page, "input[name='_systemfield_email']",  self.candidate["email"])
                self._wait_and_fill(page, "input[placeholder*='email' i]",     self.candidate["email"])
                self._wait_and_fill(page, "input[type='email']",               self.candidate["email"])
                self._wait_and_fill(page, "input[placeholder*='phone' i]",     self.candidate.get("phone",""))
                self._wait_and_fill(page, "input[type='tel']",                 self.candidate.get("phone",""))

                self._upload_resume(page, resume_pdf_path)

                cover = job.get("cover_letter", "")
                if cover:
                    self._wait_and_fill(page, "textarea[placeholder*='cover' i]",  cover[:3000])
                    self._wait_and_fill(page, "textarea[name*='cover' i]",          cover[:3000])
                    self._wait_and_fill(page, "textarea",                            cover[:3000])

                page.wait_for_timeout(1000)
                btn = self._find_submit_btn(page)

                if btn:
                    btn.scroll_into_view_if_needed()
                    page.wait_for_timeout(500)
                    btn.click()
                    page.wait_for_timeout(4000)
                    browser.close()
                    print(f"  [ApplyAgent] ✅ Ashby auto-submitted: {job['company']}")
                    return {"success": True, "method": "ashby_auto"}

                print(f"  [ApplyAgent] ⚠️  No submit button found on Ashby form ({job['company']})")
                browser.close()
                return self._open_browser(job)

            except Exception as e:
                try: browser.close()
                except Exception: pass
                raise e

    # ── LinkedIn Easy Apply ───────────────────────────────────────────────────

    def _apply_linkedin(self, job: dict, resume_pdf_path: str) -> dict:
        try:
            from .linkedin_agent import LinkedInAgent
            agent = LinkedInAgent(self.config)
            if not agent.is_logged_in():
                print(f"  [ApplyAgent] LinkedIn session missing — queuing 1-click")
                print(f"  [ApplyAgent] Run once: python -c \"from agents.linkedin_agent import LinkedInAgent; LinkedInAgent().login()\"")
                return self._open_browser(job)
            return agent.apply(job, resume_pdf_path)
        except Exception as e:
            print(f"  [ApplyAgent] LinkedIn Easy Apply error: {e} — falling back to 1-click")
            return self._open_browser(job)

    # ── Browser fallback (Indeed, Unknown) ────────────────────────────────────

    def _open_browser(self, job: dict) -> dict:
        url = job.get("url", "")
        print(f"  [ApplyAgent] 🖱️  Queued for 1-click: {job['company']} — {url[:60]}")
        return {
            "success":  False,
            "method":   "needs_1click",
            "notes":    f"Apply at: {url}",
        }

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _fill(self, page, selector: str, value: str):
        if not value:
            return
        try:
            el = page.query_selector(selector)
            if el:
                el.fill(str(value))
        except Exception:
            pass
