# CivicLens AI

**A municipal complaint intelligence platform.** Citizens file civic complaints in
English, Hindi or Kannada (text or voice); the service resolves the ward, detects
duplicates, assigns the responsible officer, starts an SLA clock, scores priority
from a transparent weighted breakdown, clusters recurring issues, verifies
before/after photo evidence and forecasts hotspot volume. A role-scoped assistant
answers questions and always cites real complaint IDs.

> **Status:** Phases 1 and 2 are complete and verified. Every AI number in this
> README was measured on the deterministic, labelled corpus in
> `backend/app/data/corpus.py` by `backend/scripts/evaluate.py` — no hand-written
> or mocked metrics.

---

## Architecture

```text
                 ┌─────────────────────────────────────────────────────┐
                 │            clients (Flutter / web / curl)           │
                 └──────────────────────────┬──────────────────────────┘
                                            │ HTTPS + Bearer JWT
                 ┌──────────────────────────▼──────────────────────────┐
                 │  api — FastAPI (uvicorn)                            │
                 │  • /api/v1 versioned routes · /docs (OpenAPI)       │
                 │  • JWT auth + RBAC (citizen / ward_officer / admin) │
                 │  • complaints, clusters, forecasts, assistant,      │
                 │    voice, media, audit trail                        │
                 │  • sliding-window rate limiting (Redis Lua)         │
                 │  • structured JSON logs + request-id propagation    │
                 └───────┬──────────────┬───────────────┬──────────────┘
                         │ Motor        │ .delay()      │ ANN / vectors
                         ▼              ▼               ▼
              ┌──────────────┐  ┌─────────────┐  ┌──────────────────┐
              │   MongoDB    │  │    Redis    │  │      Qdrant      │
              │ users,       │  │ broker +    │  │ complaint + CLIP │
              │ complaints,  │  │ results +   │  │ embeddings       │
              │ clusters,    │  │ rate limits │  │ (cosine + geo)   │
              │ media, audit │  └──────┬──────┘  └──────────────────┘
              └──────▲───────┘         │
                     │ pymongo         │
              ┌──────┴──────────────────▼─────────────────────────────┐
              │  worker — Celery (prefork)  ·  beat — Celery scheduler│
              │  • enrich: language detect → translate → classify →   │
              │    embed → index in Qdrant                            │
              │  • transcribe: faster-whisper (en / hi / kn)          │
              │  • resolution: CLIP + SSIM comparator                 │
              │  • analysis: image metrics, notifications             │
              │  • maintenance: SLA sweep + analytics recompute       │
              └───────────────────────────────────────────────────────┘
```

### Tech stack

| Layer | Choice |
|---|---|
| API framework | FastAPI + Pydantic v2 (typed everywhere) |
| Auth | PyJWT HS256 access tokens + single-use rotating refresh tokens, Argon2id password hashing |
| Database | MongoDB 7 via Motor (async) in the API, pymongo in workers |
| Cache / broker | Redis 7 — Celery broker & result backend, rate limiting, token revocation |
| Async jobs | Celery 5 (queue `civiclens`) + Celery beat |
| Vector search | Qdrant — embedded on-disk mode for dev, server in Docker Compose |
| Embeddings | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384-d, fastembed/ONNX) |
| Classification | char n-gram TF-IDF + logistic regression (scikit-learn) |
| Clustering | scikit-learn DBSCAN over a combined geo + cosine distance matrix |
| Speech-to-text | faster-whisper (CTranslate2), automatic language detection |
| Translation | NLLB-200-distilled-600M, 8-bit ONNX (no PyTorch) |
| Resolution check | CLIP ViT-B/32 vision embeddings + SSIM/defect features + logistic regression |
| Forecast | global XGBoost regressor over per-(ward, category) daily counts |
| Observability | structlog (JSON in production), request-id middleware, `/health` probes |
| Testing | pytest + pytest-asyncio + httpx ASGI transport |
| Packaging | Docker + docker-compose (api, worker, beat, mongo, redis, qdrant) |

---

## Phase 2 — intelligence layer

### Filing, duplicates and upvotes

`POST /api/v1/complaints` resolves the ward from the point geometry, auto-assigns
the oldest active ward officer (status `assigned`, otherwise `submitted`), starts
the per-category SLA clock and stores a full priority breakdown.

Before filing, the client can call `POST /api/v1/complaints/similar` with
free text + a location. Non-English text is translated to English first, then
embedded with the multilingual model and searched in Qdrant with a category
filter and a geo-radius filter (`SIMILAR_GEO_RADIUS_KM=0.2`,
`SIMILAR_MIN_SCORE=0.85`). Indexing and querying the English text matters:
raw Kannada↔English cosine similarity is ~0.02, while translated duplicates
score above 0.8. Results carry `complaint_id`, cosine score, distance in km and
a ready-to-show complaint preview. Filing with `duplicate_of` links the new
report to the original instead of creating a parallel ticket.

`POST /api/v1/complaints/{id}/vote` and `DELETE` are idempotent upvote /
retraction operations; the vote count feeds the priority formula.

### Recurring issues (DBSCAN)

`POST /api/v1/clusters/recompute` (staff only) and the beat task
`civiclens.recompute_analytics` rebuild clusters over the last
`CLUSTER_LOOKBACK_DAYS` days. Complaints are compared with a combined distance:

```text
d = geo_weight  * (haversine_km / CLUSTER_GEO_SCALE_KM)
  + semantic_weight * (1 - cosine_similarity)
```

DBSCAN (`eps`, `min_samples`) only links same-category reports. Each stored
cluster carries its members, dominant ward, centroid, affected radius, open
count, first/last reported timestamps and a collision-proof membership
fingerprint. `GET /api/v1/clusters/recurring` lists them for staff.

### Priority score (transparent breakdown)

Every complaint stores this exact computation:

```text
score = 100 × Σ weight_i × normalized_signal_i

severity             0.30   severity / 5
frequency            0.15   min(votes, 25) / 25
cluster_density      0.15   min(cluster_size, 10) / 10
age_unresolved       0.20   age_days / 30 (frozen at resolution)
sensitive_proximity  0.20   1 - distance / 1 km to a sensitive site
```

The response contains the weights, raw values, normalized values and points
contributed by each component, so a dashboard can explain the score without
recomputing it.

### SLA and escalation

Each category has a target (`roads` 72 h, `drainage` 24 h, `water_supply` 12 h,
`waste_management` 24 h, `streetlight` 48 h, …). `due_at` is fixed at filing.
The beat task `civiclens.sla_check`:

1. finds open complaints past `due_at`;
2. marks them breached, increments the breach count and moves the escalation
   rung (`city` → `command`);
3. writes an immutable `audit_events` record;
4. sends the reporter an in-app notification;
5. never double-escalates inside the same target window.

### Resolution verification

An officer uploads an after-photo (`POST /api/v1/complaints/{id}/resolution`);
the API requires a matching before-photo. Celery extracts explainable features
(CLIP scene similarity, block SSIM, brightness/dark-pixel/edge/Laplacian deltas)
and scores them with the trained comparator. Passing sets `resolved` and stores
the score, features and model version. The reporter then confirms (`closed`) or
disputes (`in_progress`); disputes write an audit event and clear `resolved_at`.
Admins may override, and every path is audited.

### Voice reports (en / hi / kn)

`POST /api/v1/voice/transcribe` accepts an audio upload, stores it as media and
runs faster-whisper with automatic language detection. The transcript keeps the
original script and, for Hindi/Kannada, adds an English translation. Language
detection uses Unicode script ranges for Devanagari/Kannada and lingua for Latin
script. Progress is observable at `GET /api/v1/voice/transcriptions/{media_id}`.

### Hotspot forecasting

A single global XGBoost regressor learns daily complaint volume per
`(ward, category)` from calendar features (day of week, month, weekend,
day index) and lag/rolling counts. Training uses a strict time-based holdout of
the last 14 days. `GET /api/v1/forecasts?ward=&category=&horizon_days=14`
returns dated predictions, and `GET /api/v1/forecasts/wards` returns the
category-level outlook for every category in a ward.

### Grounded assistant

`POST /api/v1/assistant/query` embeds the question, matches it against curated
intent examples (nearest neighbour), fills slots (ward, category, period,
complaint id), runs a structured MongoDB query and renders a deterministic
answer. Citations are scoped by role: citizens see only their own reports,
ward officers only their ward, admins see everything. The answer never invents
a complaint ID.

---

## Model evaluation (measured, not estimated)

<!-- EVAL_RESULTS_START -->
No municipal complaint dataset was available in this environment. Every number
below is measured by `backend/scripts/evaluate.py` on the deterministic,
labelled corpus generated by `backend/scripts/seed_dataset.py` (15 wards,
1,915 complaints, English/Hindi/Kannada, 120 days, labelled duplicate groups and
synthetic before/after pairs). Re-run

```bash
cd backend
python scripts/seed_dataset.py --reset
python scripts/train_models.py
python scripts/evaluate.py
```

to regenerate them; raw values are written to `backend/var/eval_results.json`.

Corpus fingerprint: `19ba147695e1`

**Category classifier** — holdout accuracy **55.0%** (22/40).

| Category | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| drainage | 0.500 | 1.000 | 0.667 | 4 |
| noise | 0.667 | 0.500 | 0.571 | 4 |
| other | 0.250 | 0.250 | 0.250 | 4 |
| parks_trees | 0.286 | 0.500 | 0.364 | 4 |
| roads | 0.667 | 0.500 | 0.571 | 4 |
| sanitation | 0.500 | 0.250 | 0.333 | 4 |
| streetlight | 0.750 | 0.750 | 0.750 | 4 |
| traffic_signal | 1.000 | 0.750 | 0.857 | 4 |
| waste_management | 1.000 | 0.250 | 0.400 | 4 |
| water_supply | 0.600 | 0.750 | 0.667 | 4 |

**Duplicate detection** (same ward + category pairs within 0.2 km)

- Candidate pairs: **923**, true duplicates: **603** (base rate 65.3%)
- Configured threshold **0.85**: precision **93.6%**, recall 100.0%, F1 0.967
- F1-optimal threshold **0.95**: precision **93.6%**, recall 100.0%, F1 0.967

**Resolution verification** (unseen synthetic before/after pairs)

- Accuracy **100.0%**, precision **100.0%**, recall 100.0% at threshold 0.6
- Mean confidence: fixed 0.961, unfixed 0.015

**14-day hotspot forecast**

- Artifact holdout MAE: **0.142** complaints/day
- Recursive 14-step backtest over 150 series: mean MAE **0.080**, median 0.071

**Language detection** (corpus templates by native script)

- Overall accuracy **100.0%** over 60 samples
- en: 100.0% (20 samples)
- hi: 100.0% (20 samples)
- kn: 100.0% (20 samples)

**Translation (NLLB-200 distilled 600M, 8-bit ONNX)**

- Non-empty English translations: 4/4 (100.0%)
- hi: सड़क पर गहरा गड्ढा -> *Deep pit on the road*
- hi: नाला बंद होने से सड़क पर पानी -> *Water on the road from drainage*
<!-- EVAL_RESULTS_END -->


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
| Qdrant | http://localhost:6333 |

### Option B — local processes (no Docker)

Requires Python ≥ 3.11, MongoDB ≥ 6, Redis ≥ 6 (`HELLO`/RESP3 support). Qdrant
runs embedded on disk by default (`QDRANT_PATH`); no separate server is needed.

```bash
# 1. infrastructure
mongod --dbpath <data-dir>          # localhost:27017
redis-server                        # localhost:6379

# 2. API
cd backend
python -m venv .venv && .venv/bin/activate
pip install ".[dev]"
uvicorn app.main:app --reload

# 3. worker + scheduler (separate shells)
celery -A app.workers.celery_app worker --loglevel=info
celery -A app.workers.celery_app beat --loglevel=info

# 4. cache models, seed the deterministic corpus, train and evaluate
python scripts/warmup_models.py
python scripts/seed_dataset.py --reset
python scripts/train_models.py
python scripts/evaluate.py
```

The seed script creates 15 wards, 10 categories in English/Hindi/Kannada,
120 days of history, labelled duplicate groups and synthetic resolution pairs.
See `scripts/seed_dataset.py --help` for the account list and reset behaviour.

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
| `POST /complaints` | any token | File a complaint (auto ward, officer, SLA, priority) |
| `GET /complaints` | any token | Filter/sort by ward, category, status, priority, mine |
| `POST /complaints/similar` | any token | Similar issues nearby (semantic + geo) |
| `GET /complaints/{id}` | any token | Detail; reporter identity hidden from strangers |
| `PATCH /complaints/{id}/status` | staff | Transition-guarded workflow |
| `POST /complaints/{id}/vote` | any token | Idempotent upvote |
| `DELETE /complaints/{id}/vote` | any token | Retract a vote |
| `POST /complaints/{id}/attachments` | owner/staff | Before/after/general photo upload |
| `POST /complaints/{id}/resolution` | officer/admin | After-photo upload + model verification |
| `POST /complaints/{id}/resolution/confirm` | reporter | Confirm the fix → `closed` |
| `POST /complaints/{id}/resolution/dispute` | reporter | Dispute the fix → `in_progress` |
| `GET /complaints/{id}/audit` | any token | Immutable audit trail |
| `POST /clusters/recompute` | officer/admin | Rebuild DBSCAN clusters + refresh priorities |
| `GET /clusters/recurring` | officer/admin | Recurring-issue list |
| `GET /clusters/recurring/{id}/members` | officer/admin | Cluster members |
| `GET /forecasts` | any token | 14-day ward/category forecast |
| `GET /forecasts/wards` | any token | Category outlook for a ward |
| `POST /assistant/query` | any token | Grounded Q&A with role-scoped citations |
| `GET /assistant/examples` | any token | Example questions |
| `POST /voice/transcribe` | any token | Upload audio → Whisper transcript + translation |
| `GET /voice/transcriptions/{media_id}` | owner/staff | Transcript status and result |
| `GET /media/{id}` · `/meta` | owner/staff | Stored photo/audio bytes and metadata |
| `GET /wards` · `GET /wards/{no}` | any token | Ward geometry and sensitive sites |
| `POST /jobs/*` · `GET /jobs/{id}` | any token | Phase-1 async job endpoints |

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

**Roles:** `citizen` (file complaints, vote, confirm/dispute) · `ward_officer`
(manage their ward, upload resolution evidence, recompute analytics) · `admin`
(everything, incl. user administration — implicit permission on all role guards).

**Refresh rotation:** refresh tokens are single use. Refreshing deletes the old
`jti` server-side (Redis), so a replayed token returns `401 refresh_revoked`.
Deactivating or demoting a user revokes their outstanding refresh tokens.

### Error envelope

Every non-2xx response has the same shape:

```json
{"error": {"code": "not_found", "message": "User 'x' not found.", "details": {}}}
```

Rate-limited responses additionally carry `Retry-After`.

---

## Development

```bash
cd backend
ruff check app tests scripts        # lint (ruff is configured in pyproject)
pytest                              # needs MongoDB + Redis running
python scripts/seed_dataset.py --reset
python scripts/train_models.py
python scripts/evaluate.py          # writes var/eval_results.json
python scripts/smoke.py             # end-to-end check against a running stack
```

- **Tests** use a dedicated Mongo database (`civiclens_test_*`, dropped before
  and after), Redis DB 15, an isolated embedded Qdrant path and a `tiny` Whisper
  model; model artifacts are trained into `var/test_models` on first run.
- **Smoke test** requires all processes up (Mongo, Redis, API, worker) and
  exercises the *real* broker/worker path — no eager mode.

### Configuration

All settings come from the environment (or `.env`); see
[`.env.example`](.env.example). Production refuses to boot with the development
`JWT_SECRET`. Phase-2 knobs (Qdrant, embedding model, SLA targets, priority
weights, clustering, forecasting, assistant) are documented inline there.

### Repository layout

```text
civiclens/
├── docker-compose.yml          # api + worker + beat + mongo + redis + qdrant
├── .env.example
└── backend/
    ├── Dockerfile
    ├── pyproject.toml          # deps, pytest, ruff
    ├── app/
    │   ├── main.py             # app factory, OpenAPI metadata, middleware
    │   ├── core/               # config, logging, security, errors, rate limit, deps
    │   ├── db/                 # async (Motor) + sync (pymongo) clients, indexes
    │   ├── models/             # Pydantic schemas (ward, complaint, voice, …)
    │   ├── ai/                 # embeddings, vector store, language, translation,
    │   │                       # classifier, clustering, priority, resolution,
    │   │                       # forecast, assistant
    │   ├── api/v1/             # auth, users, health, jobs, complaints, wards,
    │   │                       # clusters, forecasts, assistant, voice, media
    │   ├── services/           # business logic (complaints, wards, audit, …)
    │   ├── workers/            # Celery app, beat schedule + task modules
    │   └── data/corpus.py      # deterministic labelled benchmark corpus
    ├── scripts/                # seed_dataset, train_models, evaluate, smoke, warmup
    └── tests/                  # unit + integration tests
```

---

## Roadmap

- [x] **Phase 1 — Backend foundations:** JWT auth (rotation + RBAC), Docker
  compose, Redis + Celery async jobs, structured logging, error handling,
  validation, rate limiting, `/health`, `/api/v1`, OpenAPI, test suite, live
  smoke verification.
- [x] **Phase 2 — Intelligence layer:** complaint filing + ward assignment +
  workflow, multilingual embeddings and "similar issues nearby", upvote instead
  of duplicate, DBSCAN recurring clusters, transparent priority scoring,
  per-category SLA + escalation + audit, before/after resolution verification,
  Whisper STT for en/hi/kn with translation, XGBoost 14-day hotspot forecasts,
  role-scoped RAG assistant, measured model evaluation.
- [ ] **Phase 3:** Ward dashboards and operational alerting on top of the
  intelligence layer.
- [ ] **Phase 4:** Flutter client + deployment polish.

## License

MIT
