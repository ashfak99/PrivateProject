# DSA Prep Telegram Bot

AI-agent-powered Telegram bot jo har user ko unke **college year**, **target company type** aur **DSA level** ke hisaab se roz **subah LeetCode** aur **shaam Codeforces** ka 1-1 personalized question bhejta hai. 7-din free trial, uske baad 10 Telegram Stars / 7 din.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Features](#2-features)
3. [User Onboarding & Categories](#3-user-onboarding--categories)
4. [System Architecture](#4-system-architecture)
5. [Two-Phase Daily Flow](#5-two-phase-daily-flow)
6. [Data Model](#6-data-model)
7. [Question Sourcing](#7-question-sourcing)
8. [AI Agent — Scope & Role](#8-ai-agent--scope--role)
9. [Subscription & Payments](#9-subscription--payments)
10. [Tech Stack](#10-tech-stack)
11. [Project Structure](#11-project-structure)
12. [Environment Variables](#12-environment-variables)
13. [Rate Limiting & Failure Handling](#13-rate-limiting--failure-handling)
14. [Setup / Getting Started](#14-setup--getting-started)
15. [Deployment](#15-deployment)
16. [Roadmap](#16-roadmap)
17. [Pre-Launch Checklist](#17-pre-launch-checklist)

---

## 1. Overview

Bot ek **recommendation + scheduling engine** hai. Question selection deterministic/rule-based hai (reliability ke liye), aur AI agent sirf personalization layer hai — hints, chat fallback, aur weekly summaries ke liye. Ye separation isliye zaroori hai taaki:

- Wrong/hallucinated link kabhi na jaye (selection hamesha real DB se)
- LLM cost aur latency control me rahe (per-user nahi, per-bucket call)
- System predictable aur debug-friendly rahe

---

## 2. Features

- 3-step onboarding: **College Year → Target Org Type → DSA Level**
- Daily 2 messages: Morning (LeetCode) + Evening (Codeforces)
- 60 fixed personalization buckets (dedup + weighted pick, koi repeat question nahi)
- AI-generated 1-line hint (spoiler-free) har question ke saath
- Solved / Skip / Hint inline buttons — interaction logging ke liye
- 7-day free trial → Telegram Stars (10 ⭐ / 7 din) subscription
- Weekly AI-generated progress summary (optional, phase 2)

---

## 3. User Onboarding & Categories

Onboarding Telegram **inline keyboard** se hoga (typing nahi — fast UX).

| Dimension | Options |
|---|---|
| **College Year** | 1st / 2nd / 3rd / Final Year / Graduated (Working) |
| **Target Org Type** | Service-based / Product-based / Top Tech (FAANG-tier) / HFT-Quant |
| **DSA Level** | Beginner / Intermediate / Pro |

**Total buckets = 5 × 4 × 3 = 60** (fixed, isse zyada categories add nahi karni — pool curation aur testing manageable rehta hai)

### Bucket → Difficulty/Tag Mapping (guideline)

| Dimension Value | Effect on Selection |
|---|---|
| Year 1-2 | Foundation-heavy: arrays, strings, basic recursion — Easy/Easy-Medium |
| Year 3-Final/Working | Interview-relevant: trees, graphs, DP — Medium/Medium-Hard |
| Service-based | Easy-Medium, high-frequency-asked, aptitude-adjacent |
| Product-based | Medium, pattern-based (sliding window, two pointer, DP) |
| Top Tech | Medium-Hard, optimized/multiple-approach problems |
| HFT/Quant | Hard, math/bit-manipulation/probability, CF Div1-Div2 rated |
| Beginner | Easy only |
| Intermediate | Easy-Medium mix |
| Pro | Medium-Hard, contest-rated Codeforces problems |

> Final tag/difficulty-per-bucket spreadsheet is a separate design artifact — banaya jayega DB seed karne se pehle.

---

## 4. System Architecture

```
Telegram User
     │
     ▼
Telegram Bot API ───────────────┐
     │                          │ (Stars payment webhook)
     ▼                          ▼
 Bot Service (aiogram)   Payment Handler
     │
     ├── Onboarding Handler ──────► Postgres (users)
     │
     ├── AI Agent Layer ──────────► LLM API (hints / chat / summary)
     │
     └── Scheduler (APScheduler)
               │
     ┌─────────┴──────────┐
     ▼                     ▼
 Selector Job         Sender Job
 (T-30min)            (T = send time)
     │                     │
     ▼                     ▼
 Question Pool        Redis Cache (bucket → question)
 (Postgres, cached          │
  from CF/LC APIs)          ▼
                       Postgres (user list per bucket)
                             │
                             ▼
                     Send to users (throttled)
                             │
                             ▼
                  Log interaction (Postgres)
```

---

## 5. Two-Phase Daily Flow

Isse **per-user DB/LLM call avoid hota hai** — cost aur latency dono kam rehte hain, chahe user-base 10 ho ya 100,000.

### Phase 1 — Selector Agent (runs at T-30 min)

1. Saare 60 buckets ko loop karta hai
2. Har bucket ke liye: question pool se filter (tags + difficulty) → already-sent questions exclude (dedup) → weighted-random pick
3. (Optional) AI se ek chhota spoiler-free hint generate karwata hai — **per-bucket ek baar**, per-user nahi
4. Result **Redis** me cache hota hai:
   - Key pattern: `bucket:{year}_{org_type}_{level}:{morning|evening}`
   - Value: question JSON (title, url, difficulty, tags, hint)
   - TTL: 24 hours (auto-expire)
5. Same entry Postgres `daily_question_log` me bhi likhi jaati hai (audit trail + future dedup)

### Phase 2 — Sender/Broadcast Job (runs at actual send time)

1. Bucket-wise loop (user-wise nahi)
2. Har bucket ke liye:
   - Redis se ek baar question fetch (O(1) cache hit)
   - Postgres se us bucket ke active users ki list (ek hi query)
   - Loop karke sabko same cached question bhejna (throttled — see [Section 13](#13-rate-limiting--failure-handling))
3. Agle bucket pe move

```
T-30min → Selector Job
           for bucket in 60_buckets:
               question = select(bucket)
               hint = ai_generate_hint(question)   # per-bucket, not per-user
               redis.set(bucket_key, question+hint, ttl=24h)
               postgres.log(bucket, question)

T (send)  → Sender Job
           for bucket in 60_buckets:
               question = redis.get(bucket_key)          # 1 cache read
               users = postgres.query(bucket)             # 1 query
               for user in users:                          # throttled send
                   telegram.send(user, question)
```

---

## 6. Data Model

| Table | Key Columns |
|---|---|
| **users** | telegram_id, year, org_type, level, trial_start, subscription_end, status |
| **questions** | id, source (LC/CF), title, url, difficulty, tags[], rating (CF only) |
| **user_question_log** | user_id, question_id, sent_at, status (solved/skipped/pending) |
| **daily_question_log** | bucket_key, question_id, slot (morning/evening), date |
| **payments** | user_id, stars_amount, paid_at, valid_till |

---

## 7. Question Sourcing

| Source | Method |
|---|---|
| **LeetCode** | Public GraphQL endpoint (unofficial wrapper e.g. `alfa-leetcode-api`) — title, slug, difficulty, tags |
| **Codeforces** | Official public API (`codeforces.com/api/problemset.problems`) — free, documented, tags + rating |
| **Caching strategy** | Weekly bulk-fetch cron → store/refresh local `questions` pool → runtime selection kabhi bhi external API pe directly depend nahi karta |

---

## 8. AI Agent — Scope & Role

AI (LLM) ka use **sirf** in cases me hota hai — poora selection AI-driven nahi hai:

- Onboarding me optional free-text understanding ("mujhe DP weak lagta hai")
- Per-bucket spoiler-free hint generation (live per-user call nahi)
- Chat fallback (user "explain this topic" / "easier do" bole to)
- Weekly progress summary
- Offline: question pool ko naye tags/difficulty se enrich karna (batch job, live nahi)

**Live per-message AI call jahan avoidable ho, wahan avoid** — rule-based logic hi core selection chalata hai.

---

## 9. Subscription & Payments

- `/start` pe `trial_start_date` set hota hai — 7 din free
- Daily job check karta hai: `trial_start_date + 7 days > today`
- Trial khatam hone par daily messages pause → "Renew karo" button
- **Telegram Stars** native payment (`sendInvoice`, `currency: XTR`) — koi third-party gateway nahi chahiye, bank/business verification bhi nahi
- `successful_payment` webhook → `subscription_end_date` update
- Expiry se 1 din pehle auto-reminder

**Pricing:** 1 Star ≈ ₹2 (Telegram conversion), isliye plan **5 Stars = 10 din access** rakha hai → ~₹1/day, isse entry price low aur non-costly rehta hai user ke liye.

| Item | Value |
|---|---|
| Free trial | 7 days |
| Subscription price | 5 ⭐ |
| Subscription duration | 10 days |
| Effective cost | ~₹1/day |

---

## 10. Tech Stack

> **Design goal: $0 recurring cost.** Har layer intentionally open-source software + always-free infra se choose ki gayi hai — koi paid tier zaroori nahi hai launch ke liye.

| Layer | Tool | Notes |
|---|---|---|
| Bot framework | `aiogram` (or `python-telegram-bot`) | Async, open source (MIT/LGPL) |
| Scheduler | `APScheduler` | MVP ke liye kaafi; scale pe `Celery + Redis beat` |
| Database | `PostgreSQL` (self-hosted via Docker) + `SQLAlchemy` | Open source, VM pe hi chalega |
| Cache | `Redis` (self-hosted via Docker) | Bucket-wise daily question cache |
| AI Layer | Open-weight model (Qwen3 / Llama 3.1) via **Groq free API** (fallback: **OpenRouter free tier**) | Model open source hai; inference free-tier API se — self-hosting ke liye GPU chahiye, jo free nahi milta |
| Backend/Webhook | `FastAPI` | Telegram webhook + payment webhook handling |
| Payments | Telegram Bot API native Stars | No external SDK, no gateway fee |
| Migrations | `Alembic` | |
| Containerization | `Docker` + `docker-compose` | Bot, Postgres, Redis — sab ek VM pe isolated containers me |
| **Hosting (compute)** | **Oracle Cloud Free Tier VM** ("Always Free" — permanent, no time limit) | Real $0 hosting — Postgres+Redis+bot teeno isi VM pe |
| CI/CD | GitHub Actions (free tier) | Auto-deploy on push |
| Uptime monitoring | UptimeRobot (free tier, optional) | VM/bot down alert |

### Zero-Cost Notes
- Managed services (Supabase, Railway, Render paid tiers) avoid kiye gaye hain jahan possible ho — self-hosting on one free VM is the $0 path
- Agar Oracle free-tier VM na mile (region availability issue kabhi hoti hai), fallback: Fly.io free allowance ya Render free web-service (with its limits) — par primary plan Oracle VM hai

---

## 11. Project Structure

```
dsa-telegram-bot/
├── bot/
│   ├── handlers/          # onboarding, commands, callbacks
│   ├── keyboards/          # inline keyboard layouts
│   └── middlewares/
├── scheduler/
│   ├── selector_job.py     # Phase 1: pick & cache questions
│   └── sender_job.py       # Phase 2: broadcast from cache
├── services/
│   ├── question_pool.py    # CF/LeetCode fetch + cache refresh
│   ├── ai_agent.py         # hint / chat / summary generation
│   └── payments.py         # Stars invoice + webhook handling
├── db/
│   ├── models.py
│   └── migrations/
├── config/
│   └── settings.py
├── docker-compose.yml
├── requirements.txt / pyproject.toml
└── README.md
```

---

## 12. Environment Variables

```
TELEGRAM_BOT_TOKEN=
DATABASE_URL=postgresql://...
REDIS_URL=redis://...
LLM_API_KEY=              # Groq / OpenRouter key
LLM_MODEL=                # e.g. qwen3-14b / llama-3.1-8b-instant
CF_API_BASE=https://codeforces.com/api
LEETCODE_API_BASE=
MORNING_SEND_TIME=07:00
EVENING_SEND_TIME=19:00
TRIAL_DAYS=7
STARS_PRICE=5
SUBSCRIPTION_DAYS=10
```

---

## 13. Rate Limiting & Failure Handling

**Rate limiting:**
- Telegram allows ~30 messages/sec across users — large buckets ko async + throttled send (semaphore / small delay) se bhejna zaroori
- 429 response aane par Telegram ka `retry-after` respect karna

**Failure handling:**
- Message send fail (bot blocked / account deleted) → user `status=inactive`, skip, log
- Selector job fail (external API down) → fallback to backup/default question from pool; slot skip nahi hona chahiye silently — alert/log zaroor ho
- Payment webhook fail/duplicate → idempotency check before updating `subscription_end_date`

---

## 14. Setup / Getting Started

1. **Telegram Bot** — BotFather se bot banao, token lo, commands set karo
2. **Clone repo & install deps** — Python venv, `pip install -r requirements.txt`
3. **Infra** — Postgres + Redis instance ready karo (local Docker ya hosted free tier)
4. **`.env`** — Section 12 ke variables fill karo
5. **DB migrate** — Alembic se schema apply karo
6. **Seed question pool** — CF + LeetCode bulk-fetch script chalao
7. **Run bot** — polling/webhook mode start karo
8. **Run scheduler** — selector + sender jobs register karo APScheduler me

---

## 15. Deployment

- Docker image bana ke Railway/Render/Fly.io pe deploy
- Postgres + Redis managed free-tier instances use karo (ya same VPS pe Docker Compose)
- Webhook mode prefer karo polling ke bajaye production me (FastAPI endpoint)
- Logs/monitoring: `structlog` + basic file logging MVP ke liye, Grafana/Loki baad me

---

## 16. Roadmap

- [ ] MVP: onboarding + 2-phase daily send (rule-based, no AI hints)
- [ ] AI hint generation add karna
- [ ] Trial + Stars payment integration
- [ ] Weekly AI progress summary
- [ ] Admin dashboard (pool health, user stats)
- [ ] Scale sender job to Celery task queue (bade user-base ke liye)

---

## 17. Pre-Launch Checklist

- [ ] Codeforces + LeetCode API se sample data fetch verify
- [ ] 60-bucket tag/difficulty mapping spreadsheet finalize
- [ ] DB schema lock + migrations tested
- [ ] Hosting (Postgres/Redis/app) decide & provision
- [ ] LLM API key (Groq/OpenRouter) setup + fallback provider ready
- [ ] Telegram Stars invoice flow test (sandbox/test payment)
- [ ] `/privacy` command / data-usage note add karna
- [ ] Rate-limit + retry logic test with dummy user batch