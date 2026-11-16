# Deployment runbook — Render + Vercel

This is the production path used by the checked-in configuration:

```text
Vercel (static React SPA)
        │  HTTPS + Bearer JWT
        ▼
Render web service  civiclens-api   ──► MongoDB Atlas
        │  Redis (broker)                  Qdrant Cloud
        ▼
Render worker       civiclens-worker
Render Redis        civiclens-redis
```

Render does not offer managed MongoDB or Qdrant, so those two come from free
tiers elsewhere. Everything else is defined in [`render.yaml`](../render.yaml)
and [`web/vercel.json`](../web/vercel.json).

Estimated time: 15–20 minutes, plus 2–3 minutes for the first Render boot
(seed + install bundled model artifacts).

---

## 0. Prerequisites

- A GitHub repository containing this project (Render and Vercel both deploy
  from Git).
- Accounts on [Render](https://render.com), [Vercel](https://vercel.com),
  [MongoDB Atlas](https://www.mongodb.com/atlas) and
  [Qdrant Cloud](https://cloud.qdrant.io).
- No secrets belong in this repository. Every credential below is entered in a
  provider dashboard.

---

## 1. MongoDB Atlas (database)

1. Create a **free M0** cluster (any region close to Singapore is fine).
2. **Database Access** → add a user with a strong password. This becomes part
   of `MONGO_URI`.
3. **Network Access** → allow `0.0.0.0/0`. Render free instances do not have
   stable egress IPs, so an allow-list is not practical without a paid static
   egress add-on.
4. **Connect → Drivers** → copy the `mongodb+srv://...` string. Replace
   `<password>` and add a database name, for example:

   ```text
   mongodb+srv://civiclens:<password>@cluster0.xxxxx.mongodb.net/civiclens?retryWrites=true&w=majority
   ```

The free tier is enough for the 3,458-complaint demo corpus (a few MB) plus
media uploaded during a demo.

---

## 2. Qdrant Cloud (vector store)

1. Create a **free-tier cluster** in the same broad region as the API.
2. Copy the cluster URL, for example
   `https://xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.eu-central.aws.cloud.qdrant.io:6333`.
3. Create an **API key** for the cluster and copy it once.

The API creates the `complaints` collection and payload indexes on first use.
The same collection is shared by the API and worker.

---

## 3. Render (API + worker + Redis)

### 3.1 Create the Blueprint

1. Render dashboard → **New → Blueprint**.
2. Connect the GitHub repository. Render reads `render.yaml` from the default
   branch (`main`).
3. Review the three services:
   - `civiclens-api` — Docker web service on the free plan, health check `/health`.
   - `civiclens-worker` — Docker worker on `0.5c-512mb` ($7/month). Render's
     free compute plans are web-only, so the worker is the one paid component.
   - `civiclens-redis` — Render-managed Redis on the free plan (no eviction).
4. Fill the `sync: false` secrets when prompted:

| Variable | Value |
|---|---|
| `MONGO_URI` | Atlas SRV string from step 1 |
| `QDRANT_URL` | Qdrant Cloud URL from step 2 |
| `QDRANT_API_KEY` | Qdrant Cloud API key |
| `JWT_SECRET` | `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `CORS_ORIGINS` | `["https://<project>.vercel.app"]` — update after step 4 |

`REDIS_URL` is wired automatically from the Render Redis service. `MONGO_DB`,
`WHISPER_MODEL=tiny`, `ENVIRONMENT=production` and `RATE_LIMIT_ENABLED=true`
come from the blueprint.

5. **Apply**. The API and worker build the shared `backend/Dockerfile` and run:

   ```text
   python scripts/bootstrap_deploy.py && <serve or celery>
   ```

   On the first boot the script:
   - acquires a Mongo-based `deploy_state` lock;
   - seeds 3,458 complaints (180 days, 25 wards) if the database is empty;
   - installs the deterministic model artifacts bundled in `app/data/models`;
   - releases the lock. The second service sees existing data and skips
     seeding, then installs its own copy of the artifacts. Each Render service
     has its own filesystem, so artifacts are intentionally per-service.

   Watch both service logs. First boot is complete when the API logs
   `Application startup complete` and the worker registers the `civiclens` queue.

6. Copy the API URL, for example `https://civiclens-api.onrender.com`.

### 3.2 Free-tier caveats

- Free web services **spin down after inactivity**. The first request after a
  pause can take 30–60 seconds. The paid worker stays up, but jobs wait until
  the API wakes. This is expected.
- The API container has **512 MB RAM**. First boot no longer trains models, so
  it is much lighter than earlier builds. The worker downloads the 335 MB CLIP
  vision model the first time it verifies an after-photo; on a 512 MB worker
  that can be tight. If the worker is OOM-killed on the first verification,
  upgrade `civiclens-worker` to `1c-2g` (2 GB) and redeploy.
- To reseed and retrain after changing the corpus, set
  `CIVICLENS_FORCE_BOOTSTRAP=1` on both services and trigger a deploy. Set it
  back to `0` afterwards.
- To attach an existing, externally seeded database, set
  `CIVICLENS_SKIP_BOOTSTRAP=1`.

---

## 4. Vercel (frontend)

1. Vercel dashboard → **Add New → Project** → import the same repository.
2. Configure:
   - **Root Directory:** `web`
   - **Framework Preset:** Vite (detected)
   - **Build Command:** `npm run build`
   - **Output Directory:** `dist`
   - **Install Command:** `npm ci`
3. Add an environment variable for **Production** (and Preview if desired):

   ```text
   VITE_API_BASE_URL=https://civiclens-api.onrender.com
   ```

   No trailing slash. This value is baked in at build time, so changing it
   requires a redeploy.
4. **Deploy**, then copy the production URL, for example
   `https://civiclens.vercel.app`.
5. Return to Render → `civiclens-api` → **Environment** → set:

   ```text
   CORS_ORIGINS=["https://civiclens.vercel.app"]
   ```

   Use a JSON array. Add the Vercel preview wildcard only if you need preview
   builds to call production:
   `["https://civiclens.vercel.app","https://civiclens-*.vercel.app"]`.
   Save; Render restarts the API.
6. Open the Vercel URL. The sign-in page should show the three demo accounts.

`web/vercel.json` already handles SPA rewrites (any non-`/api` path serves
`index.html`) and sets one-year immutable caching for hashed assets.

---

## 5. GitHub Actions (CI/CD)

The workflow at [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) always
runs:

- **Backend** — `ruff check app tests scripts` and `pytest` against Mongo 7 and
  Redis 7 service containers with an isolated embedded Qdrant path.
- **Frontend** — `npm ci`, `npm run build` (`tsc --noEmit` + Vite) and
  `npm test` (Vitest).

The **Deploy** job runs only on pushes to `main` and is skipped step-by-step
when its secrets are absent. You can use either provider-native Git deployments
or the workflow, not both:

| Secret | Where to get it | Used for |
|---|---|---|
| `RENDER_DEPLOY_HOOK` | Render service → Settings → Deploy Hook | Rebuild API + worker from CI |
| `VERCEL_TOKEN` | Vercel → Account Settings → Tokens | `vercel deploy --prod` |
| `VERCEL_ORG_ID` | `web/.vercel/project.json` after `vercel link` | Vercel CLI |
| `VERCEL_PROJECT_ID` | `web/.vercel/project.json` after `vercel link` | Vercel CLI |

If Render's Blueprint auto-deploy and Vercel's Git integration are already on,
leave these secrets unset; the deploy steps will be skipped and both providers
will deploy on push themselves.

The Render deploy hook rebuilds one service. The Blueprint still keeps the
worker in sync on Git-based deploys; if you rely only on the hook, trigger a
Blueprint sync when worker code changes.

---

## 6. Post-deploy verification

Run these in order. The first four can be done with a browser.

1. `GET https://<api>/health` → `200`.
2. `GET https://<api>/api/v1/health` → `200` with Mongo and Redis `ok`.
3. Open `https://<api>/docs` — Swagger UI loads with all tags.
4. Open the Vercel URL and sign in as `admin@civiclens.dev / Admin#12345`.
   The overview should show non-zero KPIs and a 180-day trend.
5. Open **Complaint queue**, filter to an open case, add an internal note and
   transition it.
6. Sign in as `officer12@civiclens.dev / Officer#12345` and open a case in ward
   12 with before-photo evidence. Upload an after photo and submit for
   verification. The detail page should show a confidence score.
7. Sign in as `citizen1@civiclens.dev / Citizen#12345` (console redirects
   citizens) or use the API/Flutter client to confirm the resolution. The case
   should move to `closed` and the audit trail should show the confirmation.
8. Open `/public` in a private window — it must load without a token and show
   aggregate ward performance.
9. Submit a complaint through `POST /api/v1/complaints/similar` before filing
   and confirm at least one nearby candidate is returned for a seeded locality.

From a terminal:

```bash
curl -fsS https://<api>/health
curl -fsS https://<api>/api/v1/health
SMOKE_BASE_URL=https://<api> python backend/scripts/smoke.py
```

The smoke script creates a complaint, drives it through assignment and
resolution, confirms it, and checks the Whisper path. It needs the demo accounts
that the bootstrap seeds. Do not run it against a database you care about; it
leaves two extra complaints behind.

---

## 7. Lighthouse

Run Lighthouse against the deployed console **after** signing in, on the
overview route. Use Chrome DevTools → Lighthouse → **Desktop**, categories
Performance and Accessibility, and disable browser extensions. Targets:

- Performance **> 90**
- Accessibility **> 90**
- No console errors and no failed network requests.

Because the API is on a free Render instance, the first dashboard request may
take 30–60 seconds after a cold start. Warm the service before measuring, and
measure the SPA's own performance rather than the cold-start penalty. If
Performance is below target, check:

- the map route is code-split and not downloaded on the overview;
- `docs/screenshots` assets are not part of the web bundle (they are not);
- Vercel is serving hashed assets with `Cache-Control: immutable`;
- the browser is not throttled to Slow 3G for a desktop run.

---

## 8. Updating the demo

| Change | Action |
|---|---|
| UI or backend code | Push to `main`; CI runs, Render/Vercel redeploy |
| Corpus content | Bump `CORPUS_VERSION` in `backend/app/data/corpus.py`, push, then set `CIVICLENS_FORCE_BOOTSTRAP=1` on both Render services and redeploy |
| Model artifacts | Retrain locally with `python scripts/train_models.py`, copy the three files from `backend/var/models` into `backend/app/data/models`, commit, and push; on Render, set `CIVICLENS_FORCE_BOOTSTRAP=1` to retrain instead |
| API URL changes | Update `VITE_API_BASE_URL` on Vercel and `CORS_ORIGINS` on Render |
| Demo credentials | `backend/scripts/seed_dataset.py` creates them; changing passwords requires a reseed |

### Rollback

- Vercel keeps every deployment; **Deployments → Promote** an earlier build.
- Render keeps the previous image; **Events → Rollback** on the service.
- Database changes are not versioned. The corpus is deterministic, so the
  safest rollback is `CIVICLENS_FORCE_BOOTSTRAP=1` with the previous commit.
