import yaml
from search import search_jobs
from tailor import score_job, tailor_resume, generate_cover_letter, save_tailored_resume
from tracker import is_already_applied, log_application, get_daily_summary

with open("config.yaml") as f:
    config = yaml.safe_load(f)

MIN_SCORE = config["job_search"]["min_match_score"]
MAX_APPLICATIONS = config["agent"]["max_applications_per_run"]


def run():
    print("\n=== Job Agent Starting ===\n")

    jobs = search_jobs()
    applied_count = 0

    for job in jobs:
        if applied_count >= MAX_APPLICATIONS:
            print(f"[main] Reached max applications ({MAX_APPLICATIONS}) for this run.")
            break

        if is_already_applied(job["id"]):
            print(f"[main] Already applied: {job['company']} — {job['title']}")
            continue

        print(f"\n[main] Evaluating: {job['title']} at {job['company']}")

        score, reason = score_job(job)
        print(f"[main] Score: {score}/10 — {reason}")

        if score < MIN_SCORE:
            print(f"[main] Skipping (score {score} < {MIN_SCORE})")
            continue

        tailored_md = tailor_resume(job)
        cover_letter = generate_cover_letter(job)
        resume_path = save_tailored_resume(job, tailored_md)

        print(f"[main] Tailored resume saved: {resume_path}")
        print(f"[main] Cover letter: {cover_letter[:120]}...")

        log_application(job, score, reason, resume_path, status="tailored_ready")
        applied_count += 1

    print(f"\n=== Run complete. Processed {applied_count} jobs. ===")

    summary = get_daily_summary()
    print(f"\n[main] Today's total applications: {len(summary)}")
    for app in summary:
        print(f"  - {app['company']} | {app['title']} | score={app['match_score']} | {app['status']}")


if __name__ == "__main__":
    run()
