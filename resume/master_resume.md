name: Chandrababu Naidu Anakapalli
location: Bridgeport, CT
phone: 203-814-5534
email: chandrababunaidu2048@gmail.com
linkedin: linkedin.com/in/chandra-a-084825244
github: github.com/chandrababu2048-cell

---

## SUMMARY
Python and .NET Software Engineer with 4 years of production experience building scalable distributed systems, high-throughput REST APIs, and autonomous AI infrastructure. Shipped banking APIs at Citibank processing real-time payments at scale and engineered a 24/7 multi-agent AI pipeline in Python integrating Gemini, Groq, vector databases, and Model Context Protocol (MCP). Anthropic-certified in AI Fluency, Claude API, and Advanced MCP. Targeting Software Engineer, AI Engineer, and Backend roles at high-scale tech firms and AI-native startups.

---

## TECHNICAL SKILLS
Languages: Python, C#, TypeScript, JavaScript (ES6+), SQL, Go (learning)
Backend: Python (FastAPI, Django), ASP.NET Core, .NET 8, Node.js, Express, RESTful APIs, gRPC, WebSockets, event-driven architecture, stream processing, async queues
AI & LLM: Claude API, Gemini, Groq, Multi-agent Systems, Model Context Protocol (MCP), RAG, Vector Similarity Search, Prompt Engineering, LLM Integration, Evaluation Harnesses, Circuit Breakers, Inference-time Scaling
Vector & Search: pgvector, Supabase Vector, Vector Databases, Semantic Search, Embedding Pipelines
Databases: PostgreSQL, SQL Server, MongoDB, Redis, Supabase, Entity Framework Core, LINQ, Kafka (learning)
Frontend: React, Next.js, TypeScript, Vite, Tailwind CSS, HTML5, CSS3
Cloud & DevOps: Microsoft Azure, AWS, GCP, Docker, Kubernetes, GitHub Actions, CI/CD, Azure DevOps, Vercel
Tools: Git, Playwright, Stripe, JWT/OAuth2, Agile/Scrum, System Design, Code Reviews, Unit Testing, Integration Testing, Observability, Logging, Monitoring, Telemetry

---

## PROJECTS

### Job Search Automation Agent (2026 | Python · FastAPI · Gemini · Groq · Playwright · Supabase · Redis)
github.com/chandrababu2048-cell/job_agent
- Engineered a 24/7 event-driven pipeline with a 6-stage multi-agent architecture (HuntAgent → ScoreAgent → TailorAgent → ApplyAgent → TrackerAgent → NotifyAgent) that streams and processes 1,000+ job listings per run from 8+ sources using Python async queues, Supabase state store, and Model Context Protocol (MCP) for Claude API tool integration.
- Built a resilient LLM router (Gemini 2.0 Flash → Groq 70B → Groq 8B) with circuit-breaker pattern, sliding-window RPM limiting, and daily quota failover — zero dropped events across 1,000+ daily API calls with full observability via structured logging, monitoring, and telemetry.
- Automated ATS form submissions (Greenhouse, Lever, Ashby, LinkedIn Easy Apply) via Playwright stealth browser context; integrated Serper.dev for real-time parallel job discovery across 4 career site platforms.
- Deployed an ATS keyword scoring engine with a validation loop enforcing 92%+ keyword coverage per tailored resume; generates PDF output with per-job vector similarity scoring against the target job description.

### EduBridge — AI Tutor for Underprivileged Children (2026 | React · Node.js · Claude API · Vercel)
github.com/chandrababu2048-cell/EduBridge
- Shipped a production full-stack AI tutoring platform (React + Vite, Node.js/Express, Claude Sonnet API) deployed on Vercel, providing free real-time tutoring in Math, Science, and English to underserved children.
- Engineered a lightweight evaluation harness with age-appropriateness scoring to validate AI responses before serving real users; built English/Telugu bilingual toggle for regional accessibility.
- Authored RUNBOOK.md and NGO_GUIDE.md enabling non-technical NGO staff to independently maintain and operate the platform with zero developer dependency.

### Symbite — AURA Personal AI Assistant (2026 | Python · Claude API · pgvector · PostgreSQL)
- Engineered a personal AI assistant with persistent cross-session memory backed by a vector database (pgvector + Supabase Vector), enabling semantic similarity search across 1,000+ stored interactions to surface contextually relevant past conversations.
- Built a multi-mode reasoning engine (Personal, Pro, Hybrid) with parallel candidate response generation, self-consistency evaluation, and best-answer selection — a custom inference-time scaling approach inspired by chain-of-thought and self-consistency research.
- Architected a modular agent framework using Model Context Protocol (MCP) where specialized sub-agents handle memory retrieval, real-time web search, and response synthesis independently before merging outputs — reducing response latency by 40% vs. sequential execution.

### Disaster Relief Coordination Platform (2024 | Django · PostgreSQL · Stripe)
- Built backend systems on a 4-person Agile team: multi-user registration, Stripe donation management, and automated email notification workflows using Django REST Framework and PostgreSQL; delivered on schedule across 3 sprints.

---

## PROFESSIONAL EXPERIENCE

### Datara Inc
**.NET Developer | Dec 2025 – Present**
- Designed and shipped scalable RESTful APIs in C#, ASP.NET Core, and .NET 8 integrated with SQL Server via Entity Framework Core and LINQ, supporting enterprise ERP workflows and high-throughput data pipelines processing thousands of transactions daily.
- Implemented centralized error-handling middleware with structured logging, monitoring, and telemetry across the full application stack, reducing production error rates by 25% and cutting mean time to resolution.
- Enforced code reviews, unit testing, and integration testing standards; maintained CI/CD pipelines via GitHub Actions and Agile/Scrum workflows, improving deployment frequency by 30%.
- Engineered ERP API gateway for third-party service integration; authored and maintained database migration scripts using Entity Framework Core across multiple production environments.

### Citibank
**.NET Developer | Feb 2024 – Nov 2025**
- Built and maintained high-throughput Web APIs in C#/.NET 8 and ASP.NET Core supporting core banking workflows including real-time payments, trade settlement, fund transfers, and balance inquiries at scale.
- Optimized data access layer using Entity Framework Core and LINQ against SQL Server for high-volume transactional data, achieving a 20% improvement in data processing efficiency.
- Engineered JWT/OAuth2 authentication and authorization across banking APIs; drove CI/CD pipeline improvements using Azure DevOps and GitHub Actions, reducing deployment time by 40%.
- Delivered React/Next.js/TypeScript front-end features including biometric login, push notifications, and Stripe/PayPal integrations; managed deployments on Azure App Services and Azure SQL with high availability.
- Migrated legacy ASP.NET applications to .NET Core microservices; achieved 20% increase in customer satisfaction and 35% reduction in application latency.

### AT&T
**.NET Developer Intern (Part-time, during B.Tech) | Feb 2021 – Apr 2023**
- Developed high-performance REST API endpoints in ASP.NET Core for telecom platform services supporting real-time network monitoring and third-party vendor integration, increasing platform engagement by 25%.
- Built and scaled high-volume telecom systems using ASP.NET MVC, C#, SQL Server, and Entity Framework processing millions of daily transactions; reduced technical debt by 40%.
- Migrated monolithic telecom applications to microservices on Azure, decreasing operational overhead by 30%; developed responsive UIs with HTML5, CSS3, and JavaScript.

---

## EDUCATION & CERTIFICATIONS
Master of Science — Computer and Information Sciences
Sacred Heart University, Fairfield, CT | GPA: 3.3 | Aug 2023 – Dec 2024 (coursework), graduated May 2025

Bachelor of Technology — Computer Science
Chennai, India | 2019 – Apr 2023

- AI Fluency: Framework & Foundations — Anthropic (Mar 2026)
- Claude 101 — Anthropic
- Advanced MCP (Model Context Protocol) — Anthropic
- Build a Computer Vision App with Azure Cognitive Services — Microsoft
