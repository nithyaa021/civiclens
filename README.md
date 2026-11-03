# CivicLens AI

**A municipal complaint intelligence platform.** Citizens file civic complaints;
the system authenticates them with JWT/OAuth2, runs asynchronous AI jobs
(embeddings, image analysis, notifications) through Celery, and exposes a
versioned, documented REST API designed for ward-level governance workflows.

> **Status:** Phase 1 — backend foundations — is complete and verified end to
> end (see [Roadmap](#roadmap)). The NLP classification, semantic duplicate
> detection, location clustering and prioritisation engines are scheduled for
> later phases on top of this foundation.

---

## Architecture

```text
                 ┌─────────────────────────────────────────────────────┐
                 │                     clients                        │
                 │        (Flutter app / web console / curl)           │
                 └──────────────────────────┬──────────────────────────┘
                                            │ HTTPS + Bearer JWT
                 ┌──────────────────────────▼──────────────────────────┐
                 │  api  — FastAPI (uvicorn)                           │
                 │  • /api/v1 versioned routes  • /docs (OpenAPI)      │
                 │  • JWT auth + RBAC (citizen/ward_officer/admin)     │
                 │  • sliding-window rate limiting (Redis Lua)         │
                 │  • structured JSON logs + request-id propagation    │
                 │  • centralised error envelope                       │
                 └───────────┬────────────────────────────┬────────────┘
                             │ Motor (async)              │ .delay()
                             ▼                            ▼
                 ┌───────────────────┐        ┌───────────────────────┐
                 │      MongoDB      │        │        Redis          │
                 │ users, media,     │◄───────┤ broker + results +    │
                 │ embeddings, jobs  │ worker │ rate-limit buckets    │
                 └─────────▲─────────┘        └───────────▲───────────┘
                           │ pymongo (sync)               │
                 ┌─────────┴──────────────────────────────┴───────────┐
                 │  worker — Celery                                   │
                 │  jobs.generate_embedding  (feature-hash vectors)   │
                 │  jobs.analyze_image       (Pillow + NumPy metrics) │
                 │  jobs.send_notification   (DB + optional SMTP)     │
                 └───────────────────────────────────────────────────┘
```

### Tech stack

| Layer | Choice |
|---|---|
| API framework | FastAPI + Pydantic v2 (typed everywhere) |
| Auth | PyJWT HS256 access tokens + single-use rotating refresh tokens, Argon2id password hashing |
| Database | MongoDB 7 via Motor (async) in the API, pymongo in workers |
| Cache / broker | Redis 7 — Celery broker & result backend, rate limiting, token revocation |
| Async jobs | Celery 5 (queue `civiclens`) |
| Observability | structlog (JSON in production), request-id middleware, `/health` probes |
| Testing | pytest + pytest-asyncio + httpx ASGI transport, 55 tests |
| Packaging | Docker + docker-compose (api, worker, mongo, redis) |

---

## Quick start

### Option A — Docker Compose (recommended)

```bash
cp .env.example .env          # edit JWT_SECRET for anything non-local
docker compose up --build
```

| Service | Address |
|---|---|
| API + OpenAPI docs | http://localhost:8000/docs |
| Health | http://localhost:8000/health |
| MongoDB | localhost:27017 |
| Redis | localhost:6379 |

### Option B — local processes (no Docker)

Requires Python ≥ 3.11, MongoDB ≥ 6, Redis ≥ 6 (`HELLO`/RESP3 support).

```bash
# 1. infrastructure
mongod --dbpath <data-dir>          # localhost:27017
redis-server                        # localhost:6379

# 2. API
cd backend
python -m venv .venv && .venv/bin/activate
pip install ".[dev]"
uvicorn app.main:app --reload

# 3. worker (separate shell)
celery -A app.workers.celery_app worker --loglevel=info
```

---

## API overview (`/api/v1`)

Interactive documentation: **`/docs`** (Swagger) · `/redoc` · `/openapi.json`

| Method & path | Access | Purpose |
|---|---|---|
| `GET /health` | public | Liveness (unversioned) |
| `GET /api/v1/health` | public | Readiness: Mongo + Redis probes, `503` when degraded |
| `POST /auth/register` | public | Citizen self-registration |
| `POST /auth/login` | public | Credentials → access + refresh token pair |
| `POST /auth/refresh` | refresh token | Rotate the pair (old refresh is revoked) |
| `POST /auth/logout` | refresh token | Revoke a refresh token |
| `GET /auth/me` | any token | Current account |
| `POST /users` | admin | Provision ward officers / admins |
| `GET /users` | admin | Paginated directory with filters |
| `PATCH /users/{id}/role` | admin | Change role (last-admin guarded) |
| `PATCH /users/{id}/status` | admin | Activate / deactivate (revokes tokens) |
| `POST /jobs/embeddings` | any token | Queue embedding generation |
| `POST /jobs/image-analysis` | any token | Queue image analysis (multipart upload ≤ 8 MB) |
| `POST /jobs/notifications` | any token | Queue a notification |
| `GET /jobs/{task_id}` | owner/admin | Poll job state + result |
| `GET /jobs/notifications` | any token | Your notifications |

### Authentication flow

```bash
curl -X POST localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"ananya@example.com","full_name":"Ananya Rao","password":"Str0ngPass!2026"}'

curl -X POST localhost:8000/api/v1/auth/login \
  -d 'username=ananya@example.com&password=Str0ngPass!2026'
# → {"access_token":"…","refresh_token":"…","expires_in":1800, …}

curl localhost:8000/api/v1/auth/me -H "Authorization: Bearer <access_token>"
```

**Roles:** `citizen` (file complaints) · `ward_officer` (manage assigned ward)
· `admin` (everything, incl. user administration — implicit permission on all
role guards).

**Refresh rotation:** refresh tokens are single use. Refreshing deletes the
old `jti` server-side (Redis), so a replayed token returns
`401 refresh_revoked`. Deactivating or demoting a user revokes their outstanding
refresh tokens.

### Error envelope

Every non-2xx response has the same shape:

```json
{"error": {"code": "not_found", "message": "User 'x' not found.", "details": {}}}
```

Rate-limited responses additionally carry `Retry-After`.

---

## Asynchronous jobs

The API never does AI work inline — it enqueues (`202 Accepted` + `task_id`)
and the Celery worker executes:

| Task | What it really does |
|---|---|
| `jobs.generate_embedding` | Signed feature-hashing (word + bigram + char-trigram) → L2-normalised 256-d vector, persisted to `embeddings`. Deterministic; cosine similarity ranks near-duplicates above unrelated text. |
| `jobs.analyze_image` | Pillow + NumPy: dimensions/format/EXIF, mean brightness, **Laplacian-variance blur score**, dominant colours → persisted to `job_results`. |
| `jobs.send_notification` | Recipient validation → persisted notification; real SMTP send when configured, honestly reported as `skipped_no_smtp` otherwise. |

Poll results at `GET /api/v1/jobs/{task_id}` (owner-scoped; admins may read any).

---

## Development

```bash
cd backend
ruff check app tests scripts        # lint (ruff is configured in pyproject)
pytest                              # 55 tests, needs MongoDB + Redis running
python scripts/smoke.py             # end-to-end check against a running stack
```

- **Tests** use a dedicated Mongo database (`civiclens_test_*`, dropped before
  and after) and Redis DB 15; auth rate limits are relaxed by default and
  re-limited inside the rate-limit tests.
- **Smoke test** requires all four processes up (Mongo, Redis, API, worker) and
  exercises the *real* broker/worker path — no eager mode.

### Configuration

All settings come from the environment (or `.env`); see
[`.env.example`](.env.example). Production refuses to boot with the
development `JWT_SECRET`.

### Repository layout

```text
civiclens/
├── docker-compose.yml          # api + worker + mongo + redis
├── .env.example
└── backend/
    ├── Dockerfile
    ├── pyproject.toml          # deps, pytest, ruff
    ├── app/
    │   ├── main.py             # app factory, OpenAPI metadata, middleware
    │   ├── core/               # config, logging, security, errors, rate limit, deps
    │   ├── db/                 # async (Motor) + sync (pymongo) clients, indexes
    │   ├── models/             # Pydantic schemas
    │   ├── api/v1/             # auth, users, health, jobs routers
    │   ├── services/           # business logic
    │   └── workers/            # Celery app + tasks
    ├── scripts/smoke.py        # live end-to-end verification
    └── tests/                  # 55 unit + integration tests
```

---

## Roadmap

- [x] **Phase 1 — Backend foundations:** JWT auth (rotation + RBAC), Docker
  compose (api/mongo/redis/worker), Redis + Celery async jobs, structured
  logging, error handling, validation, rate limiting, `/health`, `/api/v1`,
  OpenAPI with descriptions & examples, test suite, live smoke verification.
- [ ] **Phase 2:** Complaint domain — filing, ward assignment, status workflow.
- [ ] **Phase 3:** AI engines — NLP classification, semantic duplicate detection
  (embeddings built here), computer-vision triage.
- [ ] **Phase 4:** Geo-clustering, prioritisation scoring, ward dashboards.
- [ ] **Phase 5:** Flutter client + deployment polish.

## License

MIT
