"""
LLM Router — resilient multi-provider gateway
═══════════════════════════════════════════════
Providers (priority order for sonnet-tier):
  1. Gemini 2.0 Flash   — 15 RPM, 1500 req/day  (quality writing)
  2. Groq 70B           — 30 RPM, ~1000 req/day  (fallback)
  3. Groq 8B            — 30 RPM, 14400 req/day  (last resort)

Guarantees:
  - Never hits 429: sliding-window RPM limiter per provider
  - Never loses jobs: raises QuotaAllExhausted when all daily limits hit
  - Auto-resets: daily counters reset at midnight UTC automatically
"""

import os
import time
import threading
from datetime import datetime, timezone, timedelta

from google import genai
from google.genai import types
from groq import Groq


class QuotaAllExhausted(Exception):
    """All LLM providers exhausted. Jobs stay in DB; re-run after reset."""
    def __init__(self, reset_at: str):
        self.reset_at = reset_at
        super().__init__(f"All LLM quotas exhausted. Reset at {reset_at}")


class _LLMRouter:
    """Thread-safe LLM router with RPM limiting + daily quota tracking."""

    PROVIDERS = {
        "gemini":   {"rpm": 14,  "rpd": 1490,  "model": "gemini-2.0-flash"},
        "groq_70b": {"rpm": 28,  "rpd": 990,   "model": "llama-3.3-70b-versatile"},
        "groq_8b":  {"rpm": 28,  "rpd": 14000, "model": "llama-3.1-8b-instant"},
    }

    def __init__(self):
        self._lock = threading.Lock()
        self._gemini_client = None
        self._groq_client = None
        self._rpm_windows = {k: [] for k in self.PROVIDERS}
        self._daily_date = datetime.now(timezone.utc).date()
        self._daily_counts = {k: 0 for k in self.PROVIDERS}

    def _gemini(self):
        if self._gemini_client is None:
            self._gemini_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        return self._gemini_client

    def _groq(self):
        if self._groq_client is None:
            self._groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
        return self._groq_client

    def _maybe_reset(self):
        today = datetime.now(timezone.utc).date()
        if today != self._daily_date:
            self._daily_date = today
            self._daily_counts = {k: 0 for k in self.PROVIDERS}
            print("[LLMRouter] Daily quotas reset (new UTC day)")

    def _rpm_wait(self, provider: str):
        limit = self.PROVIDERS[provider]["rpm"]
        with self._lock:
            now = time.time()
            w = self._rpm_windows[provider]
            w[:] = [t for t in w if now - t < 60]
            if len(w) >= limit:
                sleep_for = 60 - (now - w[0]) + 0.3
                print(f"[LLMRouter:{provider}] RPM limit reached — waiting {sleep_for:.1f}s")
                time.sleep(sleep_for)
                w[:] = [t for t in w if time.time() - t < 60]
            w.append(time.time())

    def _is_available(self, provider: str) -> bool:
        self._maybe_reset()
        return self._daily_counts[provider] < self.PROVIDERS[provider]["rpd"]

    def _next_reset_str(self) -> str:
        tomorrow = (datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))
        return tomorrow.strftime("%Y-%m-%d 00:00 UTC")

    def _call_gemini(self, config, prompt: str, max_tokens: int) -> str:
        model = config.get("agent", {}).get("gemini_flash_model", "gemini-2.0-flash")
        self._rpm_wait("gemini")
        for attempt in range(3):
            try:
                resp = self._gemini().models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        max_output_tokens=max_tokens,
                        temperature=0.2,
                    ),
                )
                self._daily_counts["gemini"] += 1
                return resp.text.strip()
            except Exception as e:
                err = str(e).lower()
                if any(x in err for x in ("quota", "429", "rate", "resource")):
                    if attempt == 2:
                        self._daily_counts["gemini"] = self.PROVIDERS["gemini"]["rpd"]
                        print("[LLMRouter:gemini] Daily quota exhausted")
                        raise
                    wait = 12 * (attempt + 1)
                    print(f"[LLMRouter:gemini] Rate limited, retrying in {wait}s…")
                    time.sleep(wait)
                else:
                    raise
        raise RuntimeError("Gemini failed after retries")

    def _call_groq(self, provider: str, prompt: str, max_tokens: int) -> str:
        model = self.PROVIDERS[provider]["model"]
        self._rpm_wait(provider)
        for attempt in range(3):
            try:
                resp = self._groq().chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    temperature=0.2,
                )
                self._daily_counts[provider] += 1
                return resp.choices[0].message.content.strip()
            except Exception as e:
                err = str(e).lower()
                if any(x in err for x in ("rate", "429", "quota")):
                    if attempt == 2:
                        self._daily_counts[provider] = self.PROVIDERS[provider]["rpd"]
                        print(f"[LLMRouter:{provider}] Daily quota exhausted")
                        raise
                    wait = 10 * (attempt + 1)
                    print(f"[LLMRouter:{provider}] Rate limited, retrying in {wait}s…")
                    time.sleep(wait)
                else:
                    raise
        raise RuntimeError(f"{provider} failed after retries")

    def call_sonnet(self, config, prompt: str, max_tokens: int = 4096) -> str:
        for provider in ["gemini", "groq_70b", "groq_8b"]:
            if not self._is_available(provider):
                print(f"[LLMRouter] {provider} quota exhausted, trying next…")
                continue
            try:
                if provider == "gemini":
                    return self._call_gemini(config, prompt, max_tokens)
                return self._call_groq(provider, prompt, max_tokens)
            except Exception as e:
                if any(x in str(e).lower() for x in ("quota", "exhausted", "429")):
                    print(f"[LLMRouter] {provider} failed, trying next provider…")
                    continue
                raise
        raise QuotaAllExhausted(self._next_reset_str())

    def call_haiku(self, config, prompt: str, max_tokens: int = 1024) -> str:
        for provider in ["groq_8b", "groq_70b"]:
            if not self._is_available(provider):
                continue
            try:
                return self._call_groq(provider, prompt, max_tokens)
            except Exception as e:
                if any(x in str(e).lower() for x in ("quota", "exhausted", "429")):
                    continue
                raise
        raise QuotaAllExhausted(self._next_reset_str())

    def call_generic(self, config, prompt: str, model=None, max_tokens: int = 4096) -> str:
        return self.call_sonnet(config, prompt, max_tokens)

    def status(self) -> dict:
        self._maybe_reset()
        return {
            p: {
                "used": self._daily_counts[p],
                "limit": self.PROVIDERS[p]["rpd"],
                "available": self._is_available(p),
            }
            for p in self.PROVIDERS
        }


_router = _LLMRouter()


def call_llm_sonnet(config, prompt: str, max_tokens: int = 4096) -> str:
    return _router.call_sonnet(config, prompt, max_tokens)


def call_llm_haiku(config, prompt: str, max_tokens: int = 1024) -> str:
    return _router.call_haiku(config, prompt, max_tokens)


def call_llm(config, prompt: str, model=None, max_tokens: int = 4096) -> str:
    return _router.call_generic(config, prompt, model, max_tokens)


def llm_status() -> dict:
    return _router.status()
