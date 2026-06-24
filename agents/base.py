"""
Smart LLM Router
─────────────────────────────────────────────────────────
call_llm_haiku  → Groq Llama 3.1 8B  (bulk scoring, 14,400 req/day FREE)
call_llm_sonnet → Gemini 2.0 Flash   (quality writing, 1,500 req/day FREE)
                  fallback → Groq Llama 3.3 70B if Gemini fails
"""

import os
import time
import threading
from google import genai
from google.genai import types
from groq import Groq

# ── Lazy clients ───────────────────────────────────────────────────────────────

_gemini_client = None
_groq_client = None


def _get_gemini():
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _gemini_client


def _get_groq():
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _groq_client


# ── Groq rate limiter (30 RPM free tier → cap at 25 RPM for safety) ───────────

_groq_times = []
_groq_lock = threading.Lock()


def _groq_wait():
    """Sliding-window rate limiter: max 25 calls per 60 seconds."""
    with _groq_lock:
        now = time.time()
        _groq_times[:] = [t for t in _groq_times if now - t < 60]
        if len(_groq_times) >= 25:
            sleep_for = 60 - (now - _groq_times[0]) + 0.2
            if sleep_for > 0:
                time.sleep(sleep_for)
        _groq_times.append(time.time())


# ── Provider calls ─────────────────────────────────────────────────────────────

def _call_groq(prompt, model="llama-3.1-8b-instant", max_tokens=1024):
    _groq_wait()
    client = _get_groq()
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.2,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            err = str(e).lower()
            if "rate" in err or "429" in err or "quota" in err:
                wait = 20 * (2 ** attempt)
                print(f"[LLM:Groq] Rate limited, retrying in {wait}s...")
                time.sleep(wait)
            elif attempt == 2:
                raise
            else:
                time.sleep(3)
    raise RuntimeError("Groq call failed after 3 attempts")


def _call_gemini(config, prompt, model=None, max_tokens=4096):
    client = _get_gemini()
    if model is None:
        model = config["agent"].get("gemini_flash_model", "gemini-2.0-flash")
    for attempt in range(3):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=max_tokens,
                    temperature=0.2,
                ),
            )
            return resp.text.strip()
        except Exception as e:
            err = str(e).lower()
            if "quota" in err or "rate" in err or "429" in err:
                wait = 30 * (2 ** attempt)
                print(f"[LLM:Gemini] Rate limited, retrying in {wait}s...")
                time.sleep(wait)
            elif attempt == 2:
                raise
            else:
                time.sleep(5)
    raise RuntimeError("Gemini call failed after 3 attempts")


# ── Public API (used by all agents) ───────────────────────────────────────────

def call_llm_haiku(config, prompt, max_tokens=1024):
    """Fast bulk model — Groq Llama 3.1 8B (14,400 req/day free, ~1s latency)."""
    return _call_groq(prompt, model="llama-3.1-8b-instant", max_tokens=max_tokens)


def call_llm_sonnet(config, prompt, max_tokens=4096):
    """Quality model — Gemini 2.0 Flash, auto-falls back to Groq 70B."""
    try:
        return _call_gemini(config, prompt, max_tokens=max_tokens)
    except Exception as e:
        print(f"[LLM] Gemini failed ({e}), falling back to Groq 70B…")
        return _call_groq(prompt, model="llama-3.3-70b-versatile", max_tokens=max_tokens)


def call_llm(config, prompt, model=None, max_tokens=4096):
    """Generic — Gemini 2.0 Flash."""
    return _call_gemini(config, prompt, model=model, max_tokens=max_tokens)
