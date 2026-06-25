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
import base64


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
            else:
                result.update(self._open_browser(job))
        except Exception as e:
            result["notes"] = f"Error: {e}"
            result["success"] = False
            print(f"  [ApplyAgent] ✗ {e}")

        return result

    # ── Greenhouse ─────────────────────────────────────────────────────────────

    def _apply_greenhouse(self, job: dict, resume_pdf_path: str) -> dict:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page    = browser.new_page()

            try:
                page.goto(job["url"], timeout=30000)
                page.wait_for_load_state("networkidle", timeout=15000)

                first = self.candidate["name"].split()[0]
                last  = self.candidate["name"].split()[-1]

                self._fill(page, "input[name='first_name']", first)
                self._fill(page, "input[name='last_name']",  last)
                self._fill(page, "input[name='email']",      self.candidate["email"])
                self._fill(page, "input[name='phone']",      self.candidate.get("phone", ""))
                self._fill(page, "input[name='location']",   self.candidate.get("location", ""))
                self._fill(page, "input[name='linkedin_profile']",
                           f"https://{self.candidate.get('linkedin','')}")

                # Resume upload
                if resume_pdf_path and os.path.exists(resume_pdf_path):
                    inp = page.query_selector("input[type='file']")
                    if inp:
                        inp.set_input_files(resume_pdf_path)
                        time.sleep(2)

                # Cover letter
                cover = job.get("cover_letter", "")
                if cover:
                    self._fill(page, "textarea[name='cover_letter']", cover)

                # Screenshot before submit
                screenshot_b64 = base64.b64encode(page.screenshot()).decode()

                # Find and click submit
                btn = (page.query_selector("input[type='submit'][value*='Submit' i]") or
                       page.query_selector("input[type='submit']") or
                       page.query_selector("button[type='submit']"))

                if btn:
                    btn.click()
                    time.sleep(3)
                    browser.close()
                    print(f"  [ApplyAgent] ✅ Greenhouse auto-submitted: {job['company']}")
                    return {"success": True, "method": "greenhouse_auto",
                            "screenshot": screenshot_b64}

                browser.close()
                return {"success": False, "method": "greenhouse_no_submit",
                        "notes": "Submit button not found — form may have changed"}

            except Exception as e:
                browser.close()
                raise e

    # ── Lever ──────────────────────────────────────────────────────────────────

    def _apply_lever(self, job: dict, resume_pdf_path: str) -> dict:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page    = browser.new_page()

            try:
                page.goto(job["url"], timeout=30000)
                page.wait_for_load_state("networkidle", timeout=15000)

                name = self.candidate["name"]
                self._fill(page, "input[name='name']", name)
                self._fill(page, "input[placeholder*='Full name' i]", name)
                self._fill(page, "input[name='email']",     self.candidate["email"])
                self._fill(page, "input[placeholder*='email' i]", self.candidate["email"])
                self._fill(page, "input[name='phone']",     self.candidate.get("phone", ""))
                self._fill(page, "input[name='org']",       "")
                self._fill(page, "input[name='urls[LinkedIn]']",
                           f"https://{self.candidate.get('linkedin','')}")
                self._fill(page, "input[name='urls[GitHub]']",
                           f"https://{self.candidate.get('github','')}")

                # Resume upload
                if resume_pdf_path and os.path.exists(resume_pdf_path):
                    inp = page.query_selector("input[type='file']")
                    if inp:
                        inp.set_input_files(resume_pdf_path)
                        time.sleep(2)

                # Cover letter / comments
                cover = job.get("cover_letter", "")
                if cover:
                    self._fill(page, "textarea[name='comments']", cover)
                    self._fill(page, "textarea[placeholder*='cover' i]", cover)

                screenshot_b64 = base64.b64encode(page.screenshot()).decode()

                btn = (page.query_selector("button[type='submit']") or
                       page.query_selector("input[type='submit']"))
                if btn:
                    btn.click()
                    time.sleep(3)
                    browser.close()
                    print(f"  [ApplyAgent] ✅ Lever auto-submitted: {job['company']}")
                    return {"success": True, "method": "lever_auto",
                            "screenshot": screenshot_b64}

                browser.close()
                return {"success": False, "method": "lever_no_submit",
                        "notes": "Submit button not found"}

            except Exception as e:
                browser.close()
                raise e

    # ── Ashby ──────────────────────────────────────────────────────────────────

    def _apply_ashby(self, job: dict, resume_pdf_path: str) -> dict:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page    = browser.new_page()

            try:
                page.goto(job["url"], timeout=30000)
                page.wait_for_load_state("networkidle", timeout=15000)

                first = self.candidate["name"].split()[0]
                last  = self.candidate["name"].split()[-1]

                self._fill(page, "input[name='_systemfield_name']",  self.candidate["name"])
                self._fill(page, "input[placeholder*='First' i]",    first)
                self._fill(page, "input[placeholder*='Last' i]",     last)
                self._fill(page, "input[name='_systemfield_email']", self.candidate["email"])
                self._fill(page, "input[placeholder*='email' i]",    self.candidate["email"])
                self._fill(page, "input[placeholder*='phone' i]",    self.candidate.get("phone",""))

                if resume_pdf_path and os.path.exists(resume_pdf_path):
                    inp = page.query_selector("input[type='file']")
                    if inp:
                        inp.set_input_files(resume_pdf_path)
                        time.sleep(2)

                cover = job.get("cover_letter", "")
                if cover:
                    self._fill(page, "textarea[placeholder*='cover' i]", cover)
                    self._fill(page, "textarea[name*='cover' i]", cover)

                screenshot_b64 = base64.b64encode(page.screenshot()).decode()

                btn = (page.query_selector("button[type='submit']") or
                       page.query_selector("button[data-testid*='submit' i]"))
                if btn:
                    btn.click()
                    time.sleep(3)
                    browser.close()
                    print(f"  [ApplyAgent] ✅ Ashby auto-submitted: {job['company']}")
                    return {"success": True, "method": "ashby_auto",
                            "screenshot": screenshot_b64}

                browser.close()
                return {"success": False, "method": "ashby_no_submit",
                        "notes": "Submit button not found"}

            except Exception as e:
                browser.close()
                raise e

    # ── Browser fallback (LinkedIn, Indeed, Unknown) ───────────────────────────

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
