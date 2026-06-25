"""
PreferenceAgent — learns from YES/NO/EDIT decisions to improve scoring over time.
Needs 10+ decisions before it starts influencing scores.
"""

import os
from datetime import datetime, timezone
from collections import Counter
from supabase import create_client

_DECISIONS_TABLE = "preference_decisions"
_PREFS_TABLE = "user_preferences"
_MIN_DECISIONS = 10


class PreferenceAgent:
    def __init__(self):
        self._db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    # ── Record ─────────────────────────────────────────────────────────────────

    def record_decision(self, job: dict, decision: str, feedback: str = ""):
        """decision: 'yes' | 'no' | 'edit'"""
        try:
            self._db.table(_DECISIONS_TABLE).insert({
                "job_id":        job.get("id", ""),
                "decision":      decision,
                "feedback":      feedback,
                "title":         job.get("title", ""),
                "company":       job.get("company", ""),
                "source":        job.get("source", ""),
                "tech_keywords": job.get("fit_reasons", []),
                "match_score":   job.get("match_score"),
                "decided_at":    datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception as e:
            print(f"[PreferenceAgent] record error: {e}")

    # ── Adjust score ───────────────────────────────────────────────────────────

    def adjust_score(self, job: dict, base_score: float) -> float:
        """
        Apply learned preference weights to the base keyword score.
        Returns unchanged score until 10+ decisions are recorded.
        """
        try:
            decisions = self._load_recent(100)
            if len(decisions) < _MIN_DECISIONS:
                return base_score

            yes_count = sum(1 for d in decisions if d["decision"] == "yes")
            no_count  = sum(1 for d in decisions if d["decision"] == "no")
            total = yes_count + no_count
            if total == 0:
                return base_score

            # Source preference
            source = job.get("source", "")
            src_yes = sum(1 for d in decisions if d["decision"] == "yes" and d.get("source") == source)
            src_total = sum(1 for d in decisions if d.get("source") == source)
            src_rate = src_yes / src_total if src_total >= 3 else 0.5

            # Keyword preference
            job_keywords = set(k.lower() for k in job.get("fit_reasons", []))
            kw_rates = []
            for kw in job_keywords:
                kw_yes = sum(1 for d in decisions
                             if d["decision"] == "yes"
                             and kw in [k.lower() for k in (d.get("tech_keywords") or [])])
                kw_total = sum(1 for d in decisions
                               if kw in [k.lower() for k in (d.get("tech_keywords") or [])])
                if kw_total >= 3:
                    kw_rates.append(kw_yes / kw_total)

            avg_kw_rate = sum(kw_rates) / len(kw_rates) if kw_rates else 0.5

            # Blended multiplier (range 0.5 – 1.5)
            blended = 0.4 * src_rate + 0.6 * avg_kw_rate
            multiplier = 0.5 + blended
            return round(base_score * multiplier, 2)

        except Exception as e:
            print(f"[PreferenceAgent] adjust_score error: {e}")
            return base_score

    # ── Weekly summary ─────────────────────────────────────────────────────────

    def weekly_summary(self) -> str:
        try:
            decisions = self._load_recent(500)
            if not decisions:
                return "No preference data yet — make YES/NO decisions to start learning."

            counts = Counter(d["decision"] for d in decisions)
            yes_kws = Counter()
            no_kws  = Counter()
            for d in decisions:
                kws = d.get("tech_keywords") or []
                if d["decision"] == "yes":
                    yes_kws.update(kws)
                elif d["decision"] == "no":
                    no_kws.update(kws)

            top_yes = ", ".join(k for k, _ in yes_kws.most_common(3)) or "—"
            top_no  = ", ".join(k for k, _ in no_kws.most_common(3)) or "—"

            return (
                f"Decisions this period: {counts.get('yes',0)} YES · "
                f"{counts.get('no',0)} NO · {counts.get('edit',0)} EDIT\n"
                f"You tend to approve: {top_yes}\n"
                f"You tend to skip: {top_no}"
            )
        except Exception as e:
            return f"Preference summary unavailable: {e}"

    # ── Internal ───────────────────────────────────────────────────────────────

    def _load_recent(self, limit: int) -> list:
        try:
            return (self._db.table(_DECISIONS_TABLE)
                    .select("*")
                    .order("decided_at", desc=True)
                    .limit(limit)
                    .execute()
                    .data or [])
        except Exception:
            return []
