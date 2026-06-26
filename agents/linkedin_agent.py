"""
LinkedInAgent — LinkedIn Easy Apply automation.

SETUP (run once):
  python -c "from agents.linkedin_agent import LinkedInAgent; LinkedInAgent().login()"

This opens a real browser window. Log in manually, then the session is saved
to linkedin_session.json and reused for all future applications headlessly.

NEVER commit linkedin_session.json — it contains your login cookies.
"""

import os
import json
import time
import random
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

SESSION_FILE = os.environ.get("LINKEDIN_SESSION_PATH", "linkedin_session.json")

# Answers to common LinkedIn screening questions
# Agent reads question label, maps to these answers
DEFAULT_ANSWERS = {
    # Work authorization
    "authorized to work":           "Yes",
    "legally authorized":           "Yes",
    "require sponsorship":          "No",
    "visa sponsorship":             "No",
    "require visa":                 "No",
    "work in the united states":    "Yes",
    "work in the us":               "Yes",
    # Remote / location
    "willing to relocate":          "No",
    "open to relocation":           "No",
    "remote":                       "Yes",
    # Availability
    "available to start":           "Immediately",
    "start date":                   "Immediately",
    "notice period":                "2 weeks",
    # Experience (number)
    "years of experience":          "4",
    "years of professional":        "4",
    "years working":                "4",
    # Salary
    "salary":                       "110000",
    "compensation":                 "110000",
    "expected salary":              "110000",
    # Education
    "highest level of education":   "Master's Degree",
    "degree":                       "Master's Degree",
}


class LinkedInAgent:
    def __init__(self, config: dict = None):
        self.config    = config or {}
        self.candidate = config.get("candidate", {}) if config else {}
        self.li_cfg    = config.get("linkedin", {}) if config else {}
        # Merge config answers on top of defaults
        self.answers   = {**DEFAULT_ANSWERS, **self.li_cfg.get("easy_apply_answers", {})}

    # ── Login (run once interactively) ─────────────────────────────────────────

    def login(self):
        """Open a real browser window, let user log in, save session cookies."""
        print("[LinkedIn] Opening browser — log in manually, then press Enter here.")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, slow_mo=50)
            ctx  = browser.new_context(**self._ctx_kwargs())
            page = ctx.new_page()
            self._stealth(page)
            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
            input("[LinkedIn] Press Enter after you have logged in… ")
            self._save_session(ctx)
            print(f"[LinkedIn] Session saved → {SESSION_FILE}")
            browser.close()

    def is_logged_in(self) -> bool:
        return Path(SESSION_FILE).exists()

    # ── Easy Apply ─────────────────────────────────────────────────────────────

    def apply(self, job: dict, resume_pdf_path: str) -> dict:
        """
        Auto-apply via LinkedIn Easy Apply.
        Returns dict: success, method, notes.
        """
        if not self.is_logged_in():
            return {
                "success": False, "method": "linkedin_no_session",
                "notes": "Run: python -c \"from agents.linkedin_agent import LinkedInAgent; LinkedInAgent().login()\"",
            }

        url = job.get("url", "")
        print(f"  [LinkedIn] Easy Apply → {job.get('company','?')} — {url[:60]}")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=self._stealth_args())
            ctx  = browser.new_context(**self._ctx_kwargs())
            self._load_session(ctx)
            page = ctx.new_page()
            self._stealth(page)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                self._human_pause(2, 3)

                # Check for Easy Apply button
                easy_btn = (
                    page.query_selector("button.jobs-apply-button[aria-label*='Easy Apply' i]") or
                    page.query_selector("button[aria-label*='Easy Apply' i]") or
                    page.query_selector("button:has-text('Easy Apply')")
                )
                if not easy_btn:
                    browser.close()
                    return {"success": False, "method": "linkedin_no_easy_apply",
                            "notes": "No Easy Apply button — job may require external apply"}

                easy_btn.click()
                self._human_pause(1, 2)

                # Walk through the multi-step modal
                result = self._walk_modal(page, resume_pdf_path)
                self._save_session(ctx)  # refresh cookies after use
                browser.close()
                return result

            except Exception as e:
                try:
                    browser.close()
                except Exception:
                    pass
                return {"success": False, "method": "linkedin_error", "notes": str(e)}

    # ── Modal walker (handles multi-step Easy Apply flow) ──────────────────────

    def _walk_modal(self, page, resume_pdf_path: str) -> dict:
        max_steps = 10
        for step in range(max_steps):
            self._human_pause(1, 2)

            # Fill whatever fields are visible in the current step
            self._fill_contact_fields(page)
            self._upload_resume(page, resume_pdf_path)
            self._answer_questions(page)

            # Decide next action
            submit_btn = self._find_button(page, ["Submit application", "Submit"])
            next_btn   = self._find_button(page, ["Next", "Continue", "Review"])
            done_btn   = self._find_button(page, ["Done", "Close"])

            if submit_btn:
                self._human_pause(0.5, 1)
                submit_btn.click()
                self._human_pause(2, 3)
                print(f"  [LinkedIn] ✅ Application submitted!")
                # Dismiss post-submit modal
                if done_btn := self._find_button(page, ["Done", "Close"]):
                    done_btn.click()
                return {"success": True, "method": "linkedin_easy_apply", "notes": ""}

            elif next_btn:
                self._human_pause(0.5, 1)
                next_btn.click()

            elif done_btn:
                # Ended early without submit — incomplete
                done_btn.click()
                return {"success": False, "method": "linkedin_incomplete",
                        "notes": "Modal closed before submit"}
            else:
                break

        return {"success": False, "method": "linkedin_max_steps",
                "notes": f"Could not complete after {max_steps} steps"}

    # ── Field fillers ──────────────────────────────────────────────────────────

    def _fill_contact_fields(self, page):
        name  = self.candidate.get("name", "")
        email = self.candidate.get("email", "")
        phone = self.candidate.get("phone", "")

        self._try_fill(page, "input[id*='phoneNumber' i]", phone)
        self._try_fill(page, "input[id*='phone' i]",       phone)
        self._try_fill(page, "input[name*='phone' i]",     phone)

        # Email is usually pre-filled; only override if blank
        for sel in ["input[id*='email' i]", "input[name*='email' i]"]:
            el = page.query_selector(sel)
            if el:
                current = el.input_value()
                if not current:
                    self._human_type(el, email)

    def _upload_resume(self, page, resume_pdf_path: str):
        if not resume_pdf_path or not os.path.exists(resume_pdf_path):
            return
        upload = (
            page.query_selector("input[type='file'][accept*='pdf' i]") or
            page.query_selector("input[type='file']")
        )
        if upload:
            upload.set_input_files(resume_pdf_path)
            self._human_pause(1, 2)
            print(f"  [LinkedIn] Uploaded resume: {os.path.basename(resume_pdf_path)}")

    def _answer_questions(self, page):
        """
        Find all visible form questions and answer them from the answer map.
        Handles: text inputs, number inputs, dropdowns, radio buttons.
        """
        # --- Text / number inputs ---
        for group in page.query_selector_all("div.jobs-easy-apply-form-section__grouping, "
                                             "div[data-test-form-element]"):
            label_el = group.query_selector("label, span.artdeco-text-input--label")
            if not label_el:
                continue
            label = label_el.inner_text().strip().lower()
            answer = self._lookup_answer(label)
            if not answer:
                continue

            inp = (group.query_selector("input[type='text']") or
                   group.query_selector("input[type='number']") or
                   group.query_selector("input[aria-label]"))
            if inp:
                current = inp.input_value()
                if not current:
                    self._human_type(inp, answer)
                continue

            # Dropdown
            sel_el = group.query_selector("select")
            if sel_el:
                self._select_option(sel_el, answer)
                continue

        # --- Radio buttons (Yes/No questions) ---
        for fieldset in page.query_selector_all("fieldset"):
            legend = fieldset.query_selector("legend, span")
            if not legend:
                continue
            question = legend.inner_text().strip().lower()
            answer = self._lookup_answer(question)
            if not answer:
                continue

            # Find radio with matching label
            for radio_label in fieldset.query_selector_all("label"):
                label_text = radio_label.inner_text().strip().lower()
                if answer.lower() in label_text or label_text in answer.lower():
                    radio_input = radio_label.query_selector("input[type='radio']")
                    if not radio_input:
                        # label's `for` attribute
                        for_id = radio_label.get_attribute("for")
                        if for_id:
                            radio_input = fieldset.query_selector(f"input#{for_id}")
                    if radio_input and not radio_input.is_checked():
                        radio_input.check()
                        self._human_pause(0.3, 0.6)
                    break

    def _lookup_answer(self, label: str) -> str:
        """Return best matching answer for a question label."""
        label = label.lower()
        for keyword, answer in self.answers.items():
            if keyword.lower() in label:
                return str(answer)
        return ""

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _find_button(self, page, texts: list):
        for text in texts:
            btn = page.query_selector(f"button:has-text('{text}')")
            if btn and btn.is_visible():
                return btn
        return None

    def _try_fill(self, page, selector: str, value: str):
        if not value:
            return
        el = page.query_selector(selector)
        if el and el.is_visible():
            current = el.input_value()
            if not current:
                self._human_type(el, value)

    def _human_type(self, el, text: str):
        el.click()
        el.fill("")
        for char in text:
            el.type(char, delay=random.randint(30, 80))
        self._human_pause(0.2, 0.5)

    def _select_option(self, sel_el, value: str):
        options = sel_el.query_selector_all("option")
        for opt in options:
            if value.lower() in opt.inner_text().lower():
                sel_el.select_option(value=opt.get_attribute("value"))
                return
        # fallback: pick first non-empty option
        for opt in options:
            v = opt.get_attribute("value")
            if v and v not in ("", "Select an option"):
                sel_el.select_option(value=v)
                return

    def _human_pause(self, lo: float = 0.5, hi: float = 1.5):
        time.sleep(random.uniform(lo, hi))

    def _stealth_args(self):
        return [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-extensions",
        ]

    def _stealth(self, page):
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

    def _ctx_kwargs(self):
        return {
            "user_agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "viewport": {"width": 1280, "height": 800},
            "locale": "en-US",
        }

    def _save_session(self, ctx):
        Path(SESSION_FILE).write_text(json.dumps(ctx.cookies()))

    def _load_session(self, ctx):
        if Path(SESSION_FILE).exists():
            cookies = json.loads(Path(SESSION_FILE).read_text())
            ctx.add_cookies(cookies)
