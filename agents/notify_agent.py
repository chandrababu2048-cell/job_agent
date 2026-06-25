import os
import resend
from datetime import datetime, timezone
from .score_agent import stars


class NotifyAgent:
    def __init__(self, config):
        self.config = config
        self.notify_email = config["notifications"]["gmail_to"]
        resend.api_key = os.environ["RESEND_API_KEY"]

    # ── Main digest — sent before ANY tailoring (notify first) ────────────────

    def send_approval_digest(self, jobs):
        """Send shortlisted jobs for user YES/NO approval. No tailoring happens yet."""
        if not jobs:
            return
        subject = (f"[Job Agent] {len(jobs)} roles shortlisted for your approval — "
                   f"{datetime.now(timezone.utc).strftime('%b %d, %Y')}")
        html = self._build_digest_html(jobs)
        try:
            resend.Emails.send({
                "from": "Job Agent <onboarding@resend.dev>",
                "to": self.notify_email,
                "subject": subject,
                "html": html,
            })
            print(f"[NotifyAgent] Approval digest sent — {len(jobs)} jobs")
        except Exception as e:
            print(f"[NotifyAgent] Digest error: {e}")

    # ── Per-job email — sent after user approves + tailoring is done ──────────

    def send_job_package(self, job):
        """Send tailored package — either confirmation of auto-submit or 1-click link."""
        s = job.get("stars", "?")
        applied = job.get("apply_success", False)
        prefix  = "✅ AUTO-APPLIED" if applied else "🖱️ 1-CLICK NEEDED"
        subject = (f"{prefix} | {stars(s)} {job['title']} @ {job['company']} "
                   f"| {job.get('confidence','')} confidence")
        html = self._build_package_html(job)
        try:
            resend.Emails.send({
                "from": "Job Agent <onboarding@resend.dev>",
                "to": self.notify_email,
                "subject": subject,
                "html": html,
            })
            print(f"[NotifyAgent] Package sent: {job['title']} @ {job['company']}")
        except Exception as e:
            print(f"[NotifyAgent] Package email error: {e}")

    # ── Weekly Sunday report ───────────────────────────────────────────────────

    def send_weekly_report(self, stats):
        subject = f"[Job Agent] Weekly Report — {datetime.now(timezone.utc).strftime('%b %d, %Y')}"
        html = self._build_weekly_html(stats)
        try:
            resend.Emails.send({
                "from": "Job Agent <onboarding@resend.dev>",
                "to": self.notify_email,
                "subject": subject,
                "html": html,
            })
            print("[NotifyAgent] Weekly report sent")
        except Exception as e:
            print(f"[NotifyAgent] Weekly report error: {e}")

    # ── HTML builders ──────────────────────────────────────────────────────────

    def _build_digest_html(self, jobs):
        rows = ""
        for i, j in enumerate(jobs, 1):
            s = j.get("stars", "?")
            star_html = stars(s)
            salary = self._fmt_salary(j)
            conf = j.get("confidence", "Medium")
            conf_color = "#27ae60" if conf == "High" else "#f39c12"
            why = j.get("why_shortlisted") or j.get("match_reason") or "Strong skill match"

            fit_list = "".join(
                f"<li style='margin:3px 0;font-size:12px;'>✅ {r}</li>"
                for r in j.get("fit_reasons", [])[:3]
            )
            gap_list = "".join(
                f"<li style='margin:3px 0;font-size:12px;color:#888;'>⚠️ {g}</li>"
                for g in j.get("gaps", [])[:2]
            ) or "<li style='font-size:12px;color:#888;'>No significant gaps</li>"

            rows += f"""
<tr style="border-bottom:2px solid #e8eaf0;">
  <td colspan="2" style="padding:20px 16px 0;">
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;">
      <div>
        <span style="font-size:11px;color:#888;font-weight:600;">#{i}</span>
        <span style="font-size:18px;font-weight:bold;color:#1a1a2e;margin-left:6px;">{j['title']}</span>
        <span style="font-size:15px;color:#555;margin-left:8px;">@ {j['company']}</span>
      </div>
      <span style="font-size:20px;">{star_html}</span>
    </div>
    <div style="margin:8px 0;display:flex;gap:8px;flex-wrap:wrap;">
      <span style="background:#f0f4ff;padding:3px 10px;border-radius:12px;font-size:12px;">📍 {j.get('location','Remote')}</span>
      <span style="background:#f0f4ff;padding:3px 10px;border-radius:12px;font-size:12px;">💼 {j.get('work_type','Check JD')}</span>
      <span style="background:#f0f4ff;padding:3px 10px;border-radius:12px;font-size:12px;">💰 {salary}</span>
      <span style="background:{conf_color};color:white;padding:3px 10px;border-radius:12px;font-size:12px;">{conf} confidence</span>
      <span style="background:#f0f4ff;padding:3px 10px;border-radius:12px;font-size:12px;">📡 {j.get('source','')}</span>
    </div>
    <p style="margin:8px 0;font-size:13px;color:#333;font-style:italic;">"{why}"</p>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:10px 0;">
      <div>
        <div style="font-size:11px;font-weight:700;color:#1a6b1a;margin-bottom:4px;">WHY YOU'RE COMPETITIVE</div>
        <ul style="margin:0;padding-left:16px;">{fit_list}</ul>
      </div>
      <div>
        <div style="font-size:11px;font-weight:700;color:#7a5800;margin-bottom:4px;">GAPS TO NOTE</div>
        <ul style="margin:0;padding-left:16px;">{gap_list}</ul>
      </div>
    </div>
    <p style="font-size:12px;color:#555;margin:8px 0;"><b>Recruiter take:</b> {j.get('recommendation','')}</p>
    <div style="margin:12px 0 16px;display:flex;gap:10px;">
      <a href="{j.get('url','#')}" style="background:#1a1a2e;color:white;padding:8px 18px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:bold;">
        View Job →
      </a>
      <span style="background:#f4f4f4;color:#555;padding:8px 14px;border-radius:6px;font-size:12px;">
        Job ID: <code>{j.get('id','')[:12]}</code>
      </span>
    </div>
  </td>
</tr>"""

        approve_cmd = "python cli.py approve " + " ".join(
            j.get("id","")[:12] for j in jobs
        )

        return f"""
<html><body style="font-family:Arial,sans-serif;max-width:760px;margin:auto;color:#1a1a1a;padding:20px;">

  <div style="background:linear-gradient(135deg,#1a1a2e,#16213e);color:white;padding:24px;border-radius:12px 12px 0 0;">
    <h1 style="margin:0 0 6px;font-size:22px;">🎯 Job Agent — Approval Digest</h1>
    <p style="margin:0;opacity:.8;font-size:14px;">
      {len(jobs)} roles shortlisted for you · {datetime.now(timezone.utc).strftime('%A, %B %d %Y')}
    </p>
    <p style="margin:8px 0 0;opacity:.7;font-size:12px;">
      Review below. Run <code>python cli.py approve &lt;job_id&gt;</code> to approve roles for tailoring.
    </p>
  </div>

  <div style="background:#e8f5e9;border-left:4px solid #27ae60;padding:14px 16px;margin:0;">
    <b style="font-size:13px;">✉️ REPLY TO THIS EMAIL to take action:</b><br>
    <code style="background:#f4f4f4;padding:6px 10px;border-radius:4px;display:block;margin:8px 0;font-size:12px;">YES</code>
    <span style="font-size:12px;color:#555;">→ approve ALL jobs listed and trigger auto-apply</span><br><br>
    <code style="background:#f4f4f4;padding:6px 10px;border-radius:4px;display:block;margin:8px 0;font-size:12px;">YES abc123 def456</code>
    <span style="font-size:12px;color:#555;">→ approve specific jobs by their ID (shown below each job)</span><br><br>
    <code style="background:#f4f4f4;padding:6px 10px;border-radius:4px;display:block;margin:8px 0;font-size:12px;">NO abc123</code>
    <span style="font-size:12px;color:#555;">→ skip a job you don't want</span><br><br>
    <code style="background:#f4f4f4;padding:6px 10px;border-radius:4px;display:block;margin:8px 0;font-size:12px;">EDIT abc123: focus more on Python data pipelines</code>
    <span style="font-size:12px;color:#555;">→ re-tailor with your suggestion and send revised version</span>
  </div>

  <table style="width:100%;border-collapse:collapse;background:white;">
    {rows}
  </table>

  <div style="background:#f0f4ff;border-radius:8px;padding:16px;margin-top:16px;">
    <p style="margin:0 0 8px;font-weight:bold;font-size:14px;">✅ To approve ALL jobs:</p>
    <code style="background:#1a1a2e;color:#7fff7f;padding:10px 14px;border-radius:6px;display:block;font-size:12px;">{approve_cmd}</code>
    <p style="margin:10px 0 4px;font-size:13px;">Or approve specific jobs:</p>
    <code style="background:#1a1a2e;color:#7fff7f;padding:10px 14px;border-radius:6px;display:block;font-size:12px;">python cli.py approve &lt;job_id&gt;</code>
    <p style="margin:10px 0 4px;font-size:13px;">To skip a job:</p>
    <code style="background:#1a1a2e;color:#ff9999;padding:10px 14px;border-radius:6px;display:block;font-size:12px;">python cli.py skip &lt;job_id&gt;</code>
    <p style="margin:10px 0 4px;font-size:13px;">See all pending:</p>
    <code style="background:#1a1a2e;color:#fff;padding:10px 14px;border-radius:6px;display:block;font-size:12px;">python cli.py pending</code>
  </div>

  <p style="color:#bbb;font-size:11px;text-align:center;margin-top:16px;">
    Job Agent v2 · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC · Quality-first autonomous recruiter
  </p>
</body></html>"""

    def _build_package_html(self, job):
        s = job.get("stars", "?")
        salary = self._fmt_salary(job)
        conf = job.get("confidence", "")
        conf_color = "#27ae60" if conf == "High" else "#f39c12"

        fit_rows = "".join(f"<li style='margin:4px 0;'>✅ {r}</li>" for r in job.get("fit_reasons", []))
        gap_rows = "".join(f"<li style='margin:4px 0;color:#666;'>⚠️ {g}</li>" for g in job.get("gaps", [])) \
                   or "<li style='color:#888;'>No significant gaps</li>"

        return f"""
<html><body style="font-family:Arial,sans-serif;max-width:740px;margin:auto;color:#1a1a1a;padding:20px;">

  <div style="background:#1a1a2e;color:white;padding:22px;border-radius:10px 10px 0 0;">
    <div style="font-size:24px;margin-bottom:4px;">{stars(s)}</div>
    <h2 style="margin:0 0 4px;">{job['title']}</h2>
    <h3 style="margin:0;font-weight:400;opacity:.85;">{job['company']}</h3>
  </div>

  <div style="background:#f4f6ff;padding:12px;display:flex;gap:8px;flex-wrap:wrap;">
    <span style="background:white;padding:4px 12px;border-radius:20px;font-size:13px;">📍 {job.get('location','?')}</span>
    <span style="background:white;padding:4px 12px;border-radius:20px;font-size:13px;">💼 {job.get('work_type','Check JD')}</span>
    <span style="background:white;padding:4px 12px;border-radius:20px;font-size:13px;">💰 {salary}</span>
    <span style="background:{conf_color};color:white;padding:4px 12px;border-radius:20px;font-size:13px;">{conf} confidence</span>
  </div>

  <div style="margin:16px 0;border-radius:8px;overflow:hidden;border:1px solid #e0e0e0;">
    <div style="background:{conf_color};color:white;padding:10px 16px;font-weight:bold;">
      {conf} Confidence — {job.get('recommendation','')}
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;">
      <div style="padding:14px;background:#f8fff8;border-right:1px solid #e0e0e0;">
        <div style="font-weight:bold;margin-bottom:6px;color:#1a6b1a;font-size:12px;">WHY YOU'RE COMPETITIVE</div>
        <ul style="margin:0;padding-left:16px;font-size:13px;">{fit_rows}</ul>
      </div>
      <div style="padding:14px;background:#fffef8;">
        <div style="font-weight:bold;margin-bottom:6px;color:#7a5800;font-size:12px;">HONEST GAPS</div>
        <ul style="margin:0;padding-left:16px;font-size:13px;">{gap_rows}</ul>
      </div>
    </div>
  </div>

  <h3 style="color:#333;">Your Tailored Resume</h3>
  <div style="background:#f0fff4;padding:14px;border-radius:6px;font-family:monospace;font-size:12px;white-space:pre-wrap;border:1px solid #c3e6cb;line-height:1.5;">
{job.get('tailored_resume','')[:4000]}
  </div>

  <h3 style="color:#333;">Cover Letter</h3>
  <div style="background:#fff8f0;padding:14px;border-radius:6px;font-size:14px;white-space:pre-wrap;border:1px solid #fde8c8;line-height:1.7;">
{job.get('cover_letter','')}
  </div>

  <div style="margin-top:24px;text-align:center;padding:22px;background:#eaf0ff;border-radius:10px;">
    {'<p style="font-size:15px;font-weight:bold;color:#27ae60;margin:0 0 6px;">✅ Application auto-submitted! Nothing to do.</p>' if job.get("apply_success") else '<p style="font-size:16px;font-weight:bold;margin:0 0 6px;">🖱️ One click to apply — takes 30 seconds</p>'}
    <a href="{job.get('url','#')}" style="background:#1a1a2e;color:white;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:bold;font-size:15px;">
      {'View Submission →' if job.get("apply_success") else 'Open & Submit →'}
    </a>
  </div>

  <p style="color:#bbb;font-size:11px;text-align:center;margin-top:16px;">
    Job Agent v2 · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC
  </p>
</body></html>"""

    def _build_weekly_html(self, stats):
        pipeline_rows = ""
        for stage, count in stats.get("pipeline", {}).items():
            pipeline_rows += f"<tr><td style='padding:8px 12px;border-bottom:1px solid #eee;'>{stage}</td><td style='padding:8px 12px;border-bottom:1px solid #eee;text-align:center;font-weight:bold;'>{count}</td></tr>"

        return f"""
<html><body style="font-family:Arial,sans-serif;max-width:640px;margin:auto;padding:20px;">
  <div style="background:#1a1a2e;color:white;padding:22px;border-radius:10px;margin-bottom:20px;">
    <h2 style="margin:0;">📊 Weekly Job Search Report</h2>
    <p style="margin:6px 0 0;opacity:.8;">{datetime.now(timezone.utc).strftime('Week ending %B %d, %Y')}</p>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:20px;">
    <div style="text-align:center;background:#f4f6ff;padding:16px;border-radius:8px;">
      <div style="font-size:32px;font-weight:bold;color:#1a1a2e;">{stats.get('applied',0)}</div>
      <div style="font-size:12px;color:#666;margin-top:4px;">Applications Sent</div>
    </div>
    <div style="text-align:center;background:#f0fff4;padding:16px;border-radius:8px;">
      <div style="font-size:32px;font-weight:bold;color:#27ae60;">{stats.get('responses',0)}</div>
      <div style="font-size:12px;color:#666;margin-top:4px;">Recruiter Responses</div>
    </div>
    <div style="text-align:center;background:#fff8f0;padding:16px;border-radius:8px;">
      <div style="font-size:32px;font-weight:bold;color:#e67e22;">{stats.get('interviews',0)}</div>
      <div style="font-size:12px;color:#666;margin-top:4px;">Interviews Scheduled</div>
    </div>
  </div>

  <h3 style="color:#333;">Pipeline Status</h3>
  <table style="width:100%;border-collapse:collapse;font-size:13px;">
    {pipeline_rows}
  </table>

  <p style="color:#bbb;font-size:11px;text-align:center;margin-top:20px;">
    Job Agent v2 · Weekly Report · {datetime.now(timezone.utc).strftime('%Y-%m-%d')}
  </p>
</body></html>"""

    def _fmt_salary(self, job):
        low, high = job.get("salary_min"), job.get("salary_max")
        if low and high:
            return f"${int(low):,}–${int(high):,}"
        if low:
            return f"${int(low):,}+"
        return "Not listed"
