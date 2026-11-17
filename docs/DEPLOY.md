# Deployment runbook - Oracle Always Free + Vercel

This is the production path used by the live demo:

```text
Vercel Hobby (static React SPA)
        |  HTTPS + Bearer JWT
        v
Oracle Ampere A1 VM (Ubuntu 24.04, Docker Compose)
  Caddy :80/:443  ->  FastAPI :8000
                       Celery worker + beat
                       MongoDB 7   Redis 7   Qdrant
```

One Always Free VM hosts the complete stack. The only public ports are 80 and
443; MongoDB, Redis, Qdrant and the API port stay on the private Compose network.
Caddy obtains and renews the TLS certificate for an `sslip.io` hostname derived
from the VM's reserved IPv4 address, so no domain purchase or DNS account is
needed.

> **Always Free, not a trial:** Oracle asks for a card at signup and may place a
> temporary authorization hold, but Always Free resources are not charged. Do
> not upgrade the account or add paid resources. Vercel Hobby and GitHub Actions
> for a public repository are also free.

Estimated time: 20-30 minutes, plus 5-15 minutes for the first boot (model
downloads and the 3,458-complaint seed). The full VM-level walkthrough, including
troubleshooting, is in [`deploy/oracle/README.md`](../deploy/oracle/README.md).

---

## 0. Prerequisites

| Account | Cost | Card? | Purpose |
|---|---|---|---|
| [Oracle Cloud](https://www.oracle.com/cloud/free/) | $0 | Verification only | Ampere A1 VM |
| [Vercel](https://vercel.com) Hobby | $0 | No | Static frontend |
| [GitHub](https://github.com) | $0 | No | Source + Actions |

You need an SSH key pair. On the machine that will run `ssh`:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/civiclens_oracle -C civiclens-oracle
cat ~/.ssh/civiclens_oracle.pub
```

The public key is pasted into Oracle at instance creation. The private key stays
local and is later added to GitHub Actions as `ORACLE_SSH_KEY`.

---

## 1. Create the Oracle VM

In Oracle Cloud Console:

1. **Compute -> Instances -> Create instance**.
2. Name: `civiclens`. Image: **Canonical Ubuntu 24.04**.
3. Shape: **Ampere -> VM.Standard.A1.Flex**.
   - Recommended: **4 OCPU / 24 GB RAM** (the full Always Free allowance).
   - If capacity is unavailable: retry another availability domain, or use
     **2 OCPU / 12 GB**. The stack fits, but set worker concurrency to `1` in
     `deploy/oracle/docker-compose.prod.yml`.
4. Boot volume: **100 GB** (Always Free includes 200 GB total).
5. Networking: assign a **public IPv4 address**.
6. SSH keys: paste the public key from step 0.
7. **Advanced options -> Initialization script**: paste
   [`deploy/oracle/cloud-init.yaml`](../deploy/oracle/cloud-init.yaml). If you
   skip this, run `setup-host.sh` after SSHing in.
8. Create the instance.

After it is running:

- **Reserve the public IP** (Networking -> Reserved public IPs) so the API
  hostname survives a stop/start.
- Open the VCN security list:
  - TCP **22** from your own IP (or a narrow range)
  - TCP **80** from `0.0.0.0/0` for Let's Encrypt HTTP-01
  - TCP **443** from `0.0.0.0/0`
  - Do **not** open 27017, 6379, 6333 or 8000.

`cloud-init.yaml` also configures UFW, Docker, a 4 GB swap file and the nightly
Mongo backup cron entry. If you used the initialization script, log out and back
in before using Docker so the `ubuntu` user picks up the `docker` group.

---

## 2. Clone and generate secrets

```bash
ssh -i ~/.ssh/civiclens_oracle ubuntu@<public-ip>

sudo mkdir -p /opt/civiclens
sudo chown ubuntu:ubuntu /opt/civiclens
git clone https://github.com/nithyaa021/civiclens.git /opt/civiclens
cd /opt/civiclens/deploy/oracle
chmod +x ./*.sh
```

Pick the API hostname. `sslip.io` resolves any hostname containing an IPv4
address back to that address:

```text
api.<public-ip>.sslip.io
```

Verify it from your machine before starting Caddy:

```bash
getent hosts api.<public-ip>.sslip.io
```

Then generate the production `.env`:

```bash
cd /opt/civiclens/deploy/oracle
./generate-env.sh \
  "api.<public-ip>.sslip.io" \
  "https://<vercel-project>.vercel.app" \
  "you@example.com"
```

`generate-env.sh` writes a `0600` file with independent random Mongo, Redis,
Qdrant and JWT secrets. It refuses to overwrite an existing `.env`. If Vercel is
not deployed yet, use `https://civiclens.vercel.app` as a temporary CORS origin
and update it in step 5.

Start the stack:

```bash
./deploy.sh
```

The first deploy:

1. builds the shared API/worker image;
2. downloads the ONNX/Whisper/NLLB artifacts into a persistent cache volume;
3. installs the bundled classifier, comparator and forecaster artifacts;
4. seeds 3,458 complaints across 25 wards into MongoDB and Qdrant;
5. starts the API, worker, beat and Caddy;
6. waits for `/health` and `/api/v1/health`.

Follow along with:

```bash
docker compose --env-file .env -f docker-compose.prod.yml logs -f warmup bootstrap
docker compose --env-file .env -f docker-compose.prod.yml logs -f caddy api
```

---

## 3. Verify the backend

From the VM:

```bash
curl -fsS https://api.<public-ip>.sslip.io/health
curl -fsS https://api.<public-ip>.sslip.io/api/v1/health
curl -fsS https://api.<public-ip>.sslip.io/api/v1/public/stats
```

Open `https://api.<public-ip>.sslip.io/docs` and confirm Swagger UI lists all
tags. The OpenAPI schema is at `/openapi.json`.

If Caddy is still retrying the certificate, confirm that ports 80 and 443 are
open in **both** the Oracle security list and UFW, and that the hostname resolves
to the VM's current public IP. `docker compose ... logs caddy` prints the ACME
error verbatim.

---

## 4. Deploy the frontend to Vercel

1. Sign in to Vercel with GitHub (Hobby plan, no card).
2. **Add New -> Project -> Import** `nithyaa021/civiclens`.
3. Set **Root Directory** to `web`.
4. Framework preset: **Vite**. Build command: `npm run build`. Output: `dist`.
5. Add a Production environment variable:

   ```text
   VITE_API_BASE_URL=https://api.<public-ip>.sslip.io
   ```

   No trailing slash. Vite inlines this at build time, so changing it requires a
   redeploy.
6. Deploy and copy the production URL, for example
   `https://civiclens.vercel.app`.

Return to the VM and set the exact CORS origin:

```bash
cd /opt/civiclens/deploy/oracle
sed -i 's|^CORS_ORIGINS=.*|CORS_ORIGINS=["https://civiclens.vercel.app"]|' .env
docker compose --env-file .env -f docker-compose.prod.yml up -d api
```

Preview deployments have different origins and are not allowed by default. Add
each origin you actually need to `CORS_ORIGINS`; no wildcards.

`web/vercel.json` handles SPA rewrites and one-year immutable caching for hashed
assets.

---

## 5. Wire GitHub Actions CI/CD

The workflow at [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) always
runs:

- **Backend** - `ruff check app tests scripts` and `pytest` against Mongo 7 and
  Redis 7 service containers with an isolated embedded Qdrant path.
- **Frontend** - `npm ci`, `npm run build` (`tsc --noEmit` + Vite) and
  `npm test` (Vitest).

The **Deploy production** job runs only on pushes to `main`. It checks for its
secrets step by step, so the run stays green and skips deployment until they are
configured. Set these repository secrets:

```bash
gh secret set ORACLE_HOST --body "<public-ip>"
gh secret set ORACLE_USER --body "ubuntu"
gh secret set ORACLE_SSH_KEY < ~/.ssh/civiclens_oracle
# Optional when SSH is not on port 22:
# gh secret set ORACLE_SSH_PORT --body "2222"
# Optional host-key pinning (recommended):
# ssh-keyscan -H <public-ip> | gh secret set ORACLE_SSH_HOST_KEY
```

The backend step SSHes to the VM and executes
`/opt/civiclens/deploy/oracle/deploy.sh`. That script fetches `origin/main`,
rebuilds the image, rolls the stack forward and waits for health.

For CLI-driven frontend deploys, also set:

```bash
gh secret set VERCEL_TOKEN --body "<vercel-token>"
gh secret set VERCEL_ORG_ID --body "<vercel-org-id>"
gh secret set VERCEL_PROJECT_ID --body "<vercel-project-id>"
```

The Vercel job runs `vercel pull`, `vercel build` and `vercel deploy --prebuilt`
from `web/`; `vercel pull` supplies `VITE_API_BASE_URL` from the project's
Production environment. If you use Vercel's Git integration instead, omit the
three Vercel secrets and let Vercel build on every push. Do not enable both paths
for the same project unless duplicate deployments are acceptable.

After the secrets exist, push any commit to `main` or run the workflow manually.

---

## 6. Post-deploy verification

Run these in order:

1. `GET https://api.<ip>.sslip.io/health` returns `200`.
2. `GET https://api.<ip>.sslip.io/api/v1/health` returns `200`, with Mongo and
   Redis `ok`.
3. `https://api.<ip>.sslip.io/docs` loads Swagger UI.
4. Open the Vercel URL and sign in as
   `admin@civiclens.dev / Admin#12345`. The overview should show non-zero KPIs
   and a 180-day trend.
5. Open **Complaint queue**, filter to an open case, add an internal note and
   transition it.
6. Sign in as `officer12@civiclens.dev / Officer#12345`, open a ward-12 case
   with before-photo evidence, upload an after photo and submit it for
   verification. The detail page should show a confidence score.
7. Sign in as `citizen1@civiclens.dev / Citizen#12345` to confirm the resolution;
   the case should move to `closed` and the audit trail should record the
   confirmation. The staff console redirects citizens, so use the API or the
   citizen client for this step.
8. Open `/public` in a private window: it must load without a token and show
   aggregate ward performance.
9. Submit a complaint through `POST /api/v1/complaints/similar` before filing,
   and confirm nearby candidates are returned for a seeded locality.

From a terminal:

```bash
curl -fsS https://api.<ip>.sslip.io/health
curl -fsS https://api.<ip>.sslip.io/api/v1/health
SMOKE_BASE_URL=https://api.<ip>.sslip.io python backend/scripts/smoke.py
```

The smoke script creates a complaint, drives it through assignment and
resolution, confirms it and checks the Whisper path. It leaves two extra
complaints behind; do not run it against a database you care about.

---

## 7. Lighthouse

Run Lighthouse against the deployed console **after** signing in, on the
overview route. Use Chrome DevTools -> Lighthouse -> **Desktop**, Performance
and Accessibility, with extensions disabled.

Targets:

- Performance **> 90**
- Accessibility **> 90**
- No console errors and no failed network requests

Because the API is on a single VM, the first dashboard request after a model
cache clear can be slower. Warm the service before measuring, and measure the
SPA rather than the cold-start penalty. If performance drops, check that the map
route is still code-split, that Vercel serves hashed assets with immutable
caching, and that the browser is not throttled to Slow 3G for a desktop run.

---

## 8. Operations and backups

`setup-host.sh` / `cloud-init.yaml` installs this cron entry:

```text
15 2 * * * ubuntu /opt/civiclens/deploy/oracle/backup.sh
```

It writes gzipped `mongodump` archives to `/opt/civiclens/backups` and keeps
seven days. Qdrant is a derived index: MongoDB is the source of truth, so a
restore only needs MongoDB plus a reindex/recompute.

Manual backup and restore:

```bash
cd /opt/civiclens/deploy/oracle
./backup.sh

# Restore (stop writers first):
docker compose --env-file .env -f docker-compose.prod.yml stop api worker beat
docker compose --env-file .env -f docker-compose.prod.yml exec -T mongo \
  mongorestore --uri="mongodb://civiclens:<password>@localhost:27017/civiclens?authSource=admin" \
  --gzip --archive < /opt/civiclens/backups/mongo-<timestamp>.archive.gz
docker compose --env-file .env -f docker-compose.prod.yml start api worker beat
```

Useful commands:

```bash
cd /opt/civiclens/deploy/oracle
docker compose --env-file .env -f docker-compose.prod.yml ps
docker compose --env-file .env -f docker-compose.prod.yml logs -f api worker caddy
docker stats --no-stream
free -h
df -h
```

Memory caps (worker 10 GB, API 3 GB, Mongo and Qdrant 3 GB each) are limits, not
reservations; steady-state usage is much lower. On the 12 GB fallback shape, set
worker concurrency to `1` and watch `docker stats`.

### Updating and rollback

CI/CD updates from `main` automatically. To deploy manually:

```bash
cd /opt/civiclens/deploy/oracle
./deploy.sh
```

The script resets the VM checkout to `origin/main`; `.env` is untracked and
survives. If a release is bad, reset the checkout to the previous commit and
rerun the Compose build/up commands. Images are tagged `civiclens-api:latest`,
so keep a note of the last known-good commit.

### Cost and failure modes

- **Oracle Always Free:** no charge for the A1 VM, 100 GB boot volume or
  outbound transfer within the allowance. The card is for identity verification.
- **Vercel Hobby / GitHub Actions:** free for this static site and public repo.
- **A1 capacity** is regional and can be temporarily unavailable. Retry another
  availability domain or fall back to 2 OCPU / 12 GB.
- **Always Free reclamation:** Oracle may reclaim an instance that is genuinely
  idle for a long period. This stack keeps several GB resident, but monitor it if
  the demo is unused for weeks.
- **Single point of failure:** one VM runs the API and databases. The backup cron
  covers MongoDB; a real production deployment would use managed MongoDB/Qdrant
  and at least two API instances.
- **`sslip.io` is a convenience**, not a brand domain. For a long-lived
  deployment, point a real domain at the reserved IP and update `API_DOMAIN`,
  `VITE_API_BASE_URL` and `CORS_ORIGINS`.
- **Caddy HTTP-01 requires port 80.** If port 80 is blocked, switch to DNS-01
  with a real domain.

---

## Appendix - optional paid Render path

[`render.yaml`](../render.yaml) remains in the repository as an alternative
topology: Render web service + paid worker + Render Redis, with MongoDB Atlas and
Qdrant Cloud free tiers. It is **not** the live demo. The Celery worker requires
Render's smallest paid instance (`0.5c-512mb`, $7/month) because free compute
plans are web-only, and 512 MB is too small for the measured NLLB and CLIP peaks.
Use this path only if you deliberately accept that cost or replace the worker
with a larger instance.

Required external services for that path: MongoDB Atlas M0, Qdrant Cloud free
tier, Render (API + worker + Redis) and Vercel. Set `MONGO_URI`, `QDRANT_URL`,
`QDRANT_API_KEY`, `JWT_SECRET` and `CORS_ORIGINS` in the Render dashboard. The
first boot runs `backend/scripts/bootstrap_deploy.py`, which seeds the corpus
when the database is empty and installs the bundled model artifacts. See the
comments in `render.yaml` for the service list.
