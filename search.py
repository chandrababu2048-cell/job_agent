import requests
import yaml
import os
from datetime import datetime

with open("config.yaml") as f:
    config = yaml.safe_load(f)

ADZUNA_APP_ID = os.environ["ADZUNA_APP_ID"]
ADZUNA_API_KEY = os.environ["ADZUNA_API_KEY"]

def search_jobs():
    jobs = []
    titles = config["job_search"]["titles"]
    locations = config["job_search"]["locations"]

    for title in titles:
        for location in locations:
            results = _adzuna_search(title, location)
            jobs.extend(results)

    seen = set()
    unique_jobs = []
    for job in jobs:
        if job["id"] not in seen:
            seen.add(job["id"])
            unique_jobs.append(job)

    print(f"[search] Found {len(unique_jobs)} unique jobs across {len(titles)} titles")
    return unique_jobs


def _adzuna_search(title, location):
    url = f"https://api.adzuna.com/v1/api/jobs/us/search/1"
    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_API_KEY,
        "what": title,
        "where": location,
        "results_per_page": 20,
        "sort_by": "date",
        "max_days_old": 3,
        "content-type": "application/json",
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        jobs = []
        for item in data.get("results", []):
            jobs.append({
                "id": item.get("id", ""),
                "title": item.get("title", ""),
                "company": item.get("company", {}).get("display_name", ""),
                "location": item.get("location", {}).get("display_name", ""),
                "description": item.get("description", ""),
                "url": item.get("redirect_url", ""),
                "salary_min": item.get("salary_min"),
                "salary_max": item.get("salary_max"),
                "posted_at": item.get("created", ""),
                "searched_title": title,
                "fetched_at": datetime.utcnow().isoformat(),
            })
        return jobs

    except Exception as e:
        print(f"[search] Error fetching '{title}' in '{location}': {e}")
        return []
