import google.generativeai as genai
import yaml
import os
import json

with open("config.yaml") as f:
    config = yaml.safe_load(f)

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
model = genai.GenerativeModel(config["agent"]["gemini_model"])

with open(config["resume"]["master_md"]) as f:
    MASTER_RESUME = f.read()


def score_job(job):
    prompt = f"""
You are a job-resume match scorer.

RESUME:
{MASTER_RESUME}

JOB TITLE: {job['title']}
COMPANY: {job['company']}
JOB DESCRIPTION:
{job['description']}

Score how well this candidate matches this job on a scale of 1-10.
Reply with ONLY a JSON object like this:
{{"score": 8, "reason": "Strong Python and API experience, has AI project work"}}
"""
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text.strip())
        return result.get("score", 0), result.get("reason", "")
    except Exception as e:
        print(f"[tailor] Score error for '{job['title']}': {e}")
        return 0, "scoring failed"


def tailor_resume(job):
    prompt = f"""
You are a professional resume writer. Tailor the candidate's resume for this specific job.

MASTER RESUME (markdown):
{MASTER_RESUME}

JOB TITLE: {job['title']}
COMPANY: {job['company']}
JOB DESCRIPTION:
{job['description']}

Instructions:
- Keep all facts true — do NOT invent experience
- Rewrite the SUMMARY to directly address this job's requirements
- Reorder or emphasize bullet points that match the JD keywords
- Mirror the exact language/keywords from the JD where truthful
- Keep the same markdown format as the master resume
- Do NOT add fake skills or experiences

Return ONLY the tailored resume in the same markdown format. No explanations.
"""
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"[tailor] Resume tailor error for '{job['title']}': {e}")
        return MASTER_RESUME


def generate_cover_letter(job):
    prompt = f"""
Write a concise, professional cover letter (3 short paragraphs) for this candidate applying to this job.

RESUME:
{MASTER_RESUME}

JOB TITLE: {job['title']}
COMPANY: {job['company']}
JOB DESCRIPTION:
{job['description']}

Rules:
- First paragraph: why this role and company specifically
- Second paragraph: 2 most relevant achievements from the resume that match this JD
- Third paragraph: short closing, express eagerness, sign off with candidate name
- Keep it under 250 words
- Do NOT use generic filler phrases like "I am excited to apply"
- Mirror the JD keywords naturally

Return ONLY the cover letter text.
"""
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"[tailor] Cover letter error: {e}")
        return ""


def save_tailored_resume(job, tailored_md):
    os.makedirs(config["resume"]["output_dir"], exist_ok=True)
    safe_company = job["company"].replace(" ", "_").replace("/", "-")
    safe_title = job["title"].replace(" ", "_").replace("/", "-")
    filename = f"{safe_company}_{safe_title}.md"
    path = os.path.join(config["resume"]["output_dir"], filename)
    with open(path, "w") as f:
        f.write(tailored_md)
    return path
