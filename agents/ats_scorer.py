"""
ATSScorer — scores a tailored resume against a job description.
Pure Python, zero LLM cost. Used by TailorWriterAgent to validate
before generating a PDF and enforce the 92-94% target.
"""

import re


# High-value ATS terms that always matter across software engineering roles
_GENERIC_TECH = {
    "python", "java", "javascript", "typescript", "c#", "go", "rust", "kotlin",
    "react", "next.js", "vue", "angular", "node.js", "express", "fastapi", "django",
    "flask", "spring", "asp.net", ".net", "rest", "restful", "graphql", "grpc",
    "sql", "nosql", "postgresql", "mysql", "mongodb", "redis", "elasticsearch",
    "aws", "azure", "gcp", "docker", "kubernetes", "terraform", "ci/cd", "github actions",
    "microservices", "distributed systems", "api", "agile", "scrum",
}


def extract_keywords(jd_text: str) -> list[str]:
    """
    Extract scoreable keywords from a JD using pattern matching.
    Returns a deduplicated list of lowercase phrases.
    """
    text = jd_text.lower()
    found = set()

    # ── 1. Technology names (camelCase, dot-separated, versioned) ─────────────
    tech_pattern = re.compile(
        r'\b(?:'
        r'python|java(?:script|)?|typescript|c#|golang|rust|scala|kotlin|swift|'
        r'react|next\.?js|vue\.?js|angular|svelte|'
        r'node\.?js|express|fastapi|django|flask|spring|asp\.net|\.net\s*\d*|'
        r'graphql|grpc|rest(?:ful)?|websocket|'
        r'postgresql|mysql|mariadb|mongodb|dynamodb|cassandra|redis|elasticsearch|'
        r'aws|azure|gcp|google cloud|cloudflare|vercel|'
        r'docker|kubernetes|k8s|terraform|helm|ansible|'
        r'kafka|rabbitmq|celery|airflow|spark|flink|'
        r'git|github|gitlab|bitbucket|jenkins|'
        r'ci/cd|devops|mlops|'
        r'pytorch|tensorflow|scikit-learn|hugging\s*face|langchain|llamaindex|'
        r'microservices?|monolith|serverless|event.driven|'
        r'oauth|jwt|saml|ldap|sso|'
        r'html5?|css3?|tailwind|sass|'
        r'entity framework|linq|ef core|'
        r'stripe|twilio|sendgrid|resend'
        r')\b',
        re.IGNORECASE,
    )
    for m in tech_pattern.finditer(jd_text):
        found.add(m.group(0).strip().lower())

    # ── 2. Important multi-word phrases ────────────────────────────────────────
    phrase_patterns = [
        r'distributed system[s]?',
        r'high[- ]?(?:performance|throughput|availability|scale|volume)',
        r'real[- ]?time',
        r'machine learning',
        r'deep learning',
        r'natural language processing',
        r'large language model[s]?',
        r'llm[s]?',
        r'data pipeline[s]?',
        r'data platform',
        r'data engineering',
        r'system design',
        r'object[- ]?oriented',
        r'test[- ]?driven',
        r'unit test[s]?(?:ing)?',
        r'integration test[s]?(?:ing)?',
        r'code review[s]?',
        r'pull request[s]?',
        r'agile(?:\s+methodology)?',
        r'cross[- ]?functional',
        r'production[- ]?grade',
        r'scalable (?:system|architecture|solution|application)',
        r'cloud[- ]?native',
        r'full[- ]?stack',
        r'back[- ]?end',
        r'front[- ]?end',
        r'api (?:design|development|integration)',
        r'database (?:design|optimization)',
        r'software (?:engineer(?:ing)?|architect(?:ure)?)',
        r'clean (?:code|architecture)',
        r'design pattern[s]?',
        r'concurrency|multithreading',
        r'load balanc(?:er|ing)',
        r'cach(?:e|ing)',
        r'message (?:queue|broker)',
        r'stream(?:ing)?',
        r'telemetry',
        r'observabilit[y]?',
        r'monitoring',
        r'logging',
        r'debugging',
        r'performance (?:optim|tun)',
        r'security (?:best practices|compliance)',
        r'fleet management',
        r'iot',
        r'sensor data',
    ]
    for pat in phrase_patterns:
        for m in re.finditer(pat, text):
            found.add(m.group(0).strip())

    # ── 3. Years of experience signals ────────────────────────────────────────
    for m in re.finditer(r'\d+\+?\s+years?', text):
        pass  # skip — we don't encode years in resume text

    # ── 4. Single tech words from a broader list ──────────────────────────────
    for tech in _GENERIC_TECH:
        if re.search(r'\b' + re.escape(tech) + r'\b', text, re.IGNORECASE):
            found.add(tech)

    # Remove very short / generic words and job title phrases (not real ATS keywords)
    title_patterns = re.compile(
        r'^(?:senior|junior|lead|principal|staff|mid[- ]?level)?\s*'
        r'(?:software|data|machine learning|frontend|backend|full[- ]?stack|platform)\s*'
        r'(?:engineer(?:ing)?|developer|architect|manager|scientist|analyst)s?$',
        re.IGNORECASE,
    )
    return sorted(
        k for k in found
        if len(k) >= 3 and not title_patterns.match(k.strip())
    )


def score(resume_md: str, keywords: list[str]) -> tuple[float, list[str]]:
    """
    Score resume against keyword list.
    Returns (score_pct, missing_keywords).
    """
    if not keywords:
        return 100.0, []

    resume_lower = resume_md.lower()
    matched   = []
    missing   = []

    for kw in keywords:
        # Allow slight variation: "rest" matches "restful", "api" matches "apis"
        pattern = re.escape(kw).replace(r'\?', '.?')
        if re.search(r'\b' + pattern, resume_lower):
            matched.append(kw)
        else:
            missing.append(kw)

    pct = round(len(matched) / len(keywords) * 100, 1)
    return pct, missing


def keyword_frequency(resume_md: str, keywords: list[str]) -> dict[str, int]:
    """Count how many times each keyword appears in the resume."""
    resume_lower = resume_md.lower()
    return {
        kw: len(re.findall(r'\b' + re.escape(kw), resume_lower))
        for kw in keywords
    }
