# TokenForge — LLM Token Ingestion Optimizer

## Original Problem Statement
Build an "LLM Token Ingestion Optimizer": pure-code tool that processes each piece of data once, deduplicates/compresses raw data into a token-minimized dataset (no data loss), works with the largest files possible, fast and accurate. Includes user login via API key, account login, and an admin login for the owner to manage users. Reference: an uploaded TypeScript pipeline (tokenizer → corpus → BM25 clusterer → resolver).

## User Choices
- Core goal: Deduplicate & compress raw data into a token-minimized dataset (each piece kept once, no loss) to reduce tokens before an LLM. **Pure algorithm, no LLM.**
- Auth: Email/password account login AND per-user API keys + Admin panel.
- Inputs: TXT, CSV, JSON, PDF, DOCX. Max ~50 MB.

## Architecture
- **Backend**: FastAPI + MongoDB (motor). Modules: `server.py` (routes), `auth.py` (JWT cookies + bcrypt + API-key auth), `optimizer.py` (engine), `parsers.py` (file→fragments), `models.py`.
- **Optimizer engine**: token count (tiktoken cl100k) → exact dedup (normalized hashing) → near-dup via **MinHash + LSH** (O(n)) + union-find clustering → canonical selection folding counts + preserved variants. Zero data loss.
- **Auth**: JWT access(60m)/refresh(7d) in httpOnly cookies (samesite=none, secure), bcrypt hashing, idempotent admin seed. Per-user API keys (`tio_` prefix, sha256-hashed) for `POST /api/v1/optimize` via `X-API-Key`.
- **Jobs**: multipart upload → background asyncio task → poll status; fragments stored separately, paginated + searchable; JSON export.
- **Frontend**: React (CRA), Swiss/brutalist design (Chivo + IBM Plex Mono, Klein blue / signal red, hard shadows). Pages: Landing, Login, Register, Dashboard (upload + threshold + jobs), JobResult (KPIs + recharts + fragments table), ApiKeys, Admin.

## Implemented (2026-06-07)
- Email/password auth, session persistence, logout; admin seeding.
- Per-user API key generate/list/revoke + usage docs + programmatic `/v1/optimize`.
- File upload (txt/csv/json/pdf/docx, 50MB), background optimization, polling, job history + delete.
- Results: token-savings KPIs, before/after chart, breakdown, paginated/searchable deduped dataset with preserved variant audit, JSON export & copy.
- Admin console: KPIs + users table, activate/deactivate, delete (with self/admin protection).
- Verified: backend 20/20 pytest; frontend flows pass.

## Personas
- **Developer/ML engineer**: cuts LLM token cost by deduping datasets via UI or API.
- **Owner/Admin**: monitors users, jobs, total tokens saved; manages accounts.

## Backlog
- P1: StreamingResponse for very large exports; stale-job reaper for interrupted background jobs.
- P2: split server.py into routers; suppress bootstrap /auth/me 401 console noise; CSV/JSON column-aware export formats; API usage rate limiting.

## Next Tasks
- Gather user feedback on dedup aggressiveness defaults; consider char-shingle mode for code/log files.
