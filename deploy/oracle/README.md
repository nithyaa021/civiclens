# Deploy CivicLens on Oracle Cloud Always Free

This is the zero-cost production profile used by the live demo. It runs the
**full** CivicLens stack on one Oracle Ampere A1 VM:

- FastAPI API + Celery worker + Celery beat
- MongoDB, Redis and Qdrant in private Docker volumes
- Caddy for automatic HTTPS
- The same multilingual MiniLM embedder, CLIP resolution check, NLLB
  translation, Whisper ASR, classifier and forecaster as local development

The only public ports are 80/443. MongoDB, Redis, Qdrant and the API port stay on
the private Compose network (the API is also bound to `127.0.0.1:8000` for host
health checks). The frontend is deployed separately to Vercel Hobby.

> **Always Free, not a trial:** the Ampere A1 allowance is 4 OCPU / 24 GB RAM,
> 200 GB of block storage and 10 TB/month of outbound transfer. Oracle asks for
> a card at signup and may place a temporary authorization hold, but Always Free
> resources are not charged. Do not upgrade the account or add paid resources.

## What you need

| Account | Cost | Card? | Purpose |
|---|---|---|---|
| Oracle Cloud | $0 | Card verification | The VM |
| Vercel Hobby | $0 | No | Static frontend |
| GitHub | $0 | No | Source + Actions CI/CD |
| Domain | $0 | No | `sslip.io` maps a hostname to the VM IP |

No Atlas or Qdrant Cloud account is needed in this profile. They remain an
optional managed-services path in `docs/DEPLOY.md`.

## 1. Create the VM

In Oracle Cloud Console:

1. **Compute → Instances → Create instance**.
2. Name: `civiclens`.
3. Image: **Canonical Ubuntu 24.04**.
4. Shape: **Ampere → VM.Standard.A1.Flex**.
   - Recommended: **4 OCPU / 24 GB RAM** (the full Always Free allowance).
   - If capacity is unavailable: try another availability domain, or use
     **2 OCPU / 12 GB**. The stack fits, but set the worker concurrency to `1`
     in `docker-compose.prod.yml` and expect slower first-time seeding.
5. Boot volume: **100 GB** (Always Free includes 200 GB total; 100 GB is ample).
6. Networking: assign a **public IPv4 address**.
7. SSH keys: paste the public key you will deploy with. On the machine that will
   run `ssh`, create one if needed:
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/civiclens_oracle -C civiclens-oracle
   cat ~/.ssh/civiclens_oracle.pub
   ```
8. **Advanced options → Initialization script**: paste
   [`cloud-init.yaml`](./cloud-init.yaml). If you skip this, run
   [`setup-host.sh`](./setup-host.sh) after SSHing in.
9. Create the instance.

After it is running:

- Reserve the public IP (**Networking → Reserved public IPs**) so a stop/start
  does not change the API hostname.
- Open the VCN security list:
  - TCP **22** from your own IP (or a narrow range)
  - TCP **80** from `0.0.0.0/0` (Let's Encrypt HTTP-01)
  - TCP **443** from `0.0.0.0/0`
  - Do **not** open 27017, 6379, 6333 or 8000.

If the A1 shape shows "out of capacity", retry later or in another availability
domain; this is an Oracle regional-capacity issue, not a CivicLens error.

## 2. SSH in and clone

```bash
ssh -i ~/.ssh/civiclens_oracle ubuntu@<public-ip>
```

Then:

```bash
sudo mkdir -p /opt/civiclens
sudo chown ubuntu:ubuntu /opt/civiclens
git clone https://github.com/nithyaa021/civiclens.git /opt/civiclens
cd /opt/civiclens/deploy/oracle
chmod +x ./*.sh
```

## 3. Pick the API hostname

`sslip.io` resolves any hostname containing an IPv4 address back to that address,
so no DNS account is required:

```text
api.<public-ip>.sslip.io
```

Examples: `api.203.0.113.10.sslip.io` or `api.203-0-113-10.sslip.io`.

Verify from your machine:

```bash
getent hosts api.<public-ip>.sslip.io
```

It must return the VM's public IP. If it does not, fix the IP/hostname before
starting Caddy; Let's Encrypt cannot issue a certificate otherwise.

## 4. Generate secrets and deploy

Replace `<public-ip>` and `<vercel-url>`:

```bash
cd /opt/civiclens/deploy/oracle
./generate-env.sh \
  "api.<public-ip>.sslip.io" \
  "https://<vercel-url>" \
  "you@example.com"
```

`generate-env.sh` writes a `0600` `.env` with independent random Mongo, Redis,
Qdrant and JWT secrets. It refuses to overwrite an existing file.

> If Vercel is not deployed yet, pass `https://civiclens.vercel.app` for now and
> update `CORS_ORIGINS` after step 6.

Start the stack:

```bash
./deploy.sh
```

The first deploy:

1. builds the API/worker image;
2. downloads the ONNX/Whisper/NLLB artifacts into a persistent cache volume;
3. installs the bundled classifier/comparator/forecaster artifacts;
4. seeds 3,458 complaints across 25 wards into MongoDB and Qdrant;
5. starts the API, worker, beat and Caddy;
6. waits for `/health` and `/api/v1/health`.

This can take 5–15 minutes on first boot. Follow along with:

```bash
docker compose --env-file .env -f docker-compose.prod.yml logs -f warmup bootstrap
docker compose --env-file .env -f docker-compose.prod.yml logs -f caddy api
```

## 5. Verify the backend

From the VM:

```bash
curl -fsS https://api.<public-ip>.sslip.io/health
curl -fsS https://api.<public-ip>.sslip.io/api/v1/health
curl -fsS https://api.<public-ip>.sslip.io/api/v1/public/stats
```

Then open:

- `https://api.<public-ip>.sslip.io/docs`
- `https://api.<public-ip>.sslip.io/openapi.json`

If Caddy is still retrying the certificate, confirm that ports 80 and 443 are
open in **both** the Oracle security list and UFW, and that the hostname resolves
to the VM's current public IP. `docker compose ... logs caddy` prints the ACME
error verbatim.

## 6. Deploy the frontend to Vercel

1. Sign in to [Vercel](https://vercel.com) with GitHub (Hobby plan, no card).
2. **Add New → Project → Import** `nithyaa021/civiclens`.
3. Set **Root Directory** to `web`.
4. Framework preset: **Vite**.
5. Build command: `npm run build`; output directory: `dist`.
6. Add environment variable:
   - `VITE_API_BASE_URL` = `https://api.<public-ip>.sslip.io`
7. Deploy. Copy the production URL, e.g. `https://civiclens.vercel.app`.

Update CORS on the VM with the exact URL:

```bash
cd /opt/civiclens/deploy/oracle
sed -i 's|^CORS_ORIGINS=.*|CORS_ORIGINS=["https://civiclens.vercel.app"]|' .env
docker compose --env-file .env -f docker-compose.prod.yml up -d api
```

Redeploy the frontend if you change `VITE_API_BASE_URL`; Vite inlines it at
build time. Preview deployments have different origins and are not allowed by
default; add each origin you actually need to `CORS_ORIGINS`.

## 7. Wire CI/CD

The GitHub Actions workflow already runs lint/tests/builds. The deploy job is
guarded by repository secrets, so it stays green and skipped until they exist.

On the VM, the deploy user is `ubuntu` and the repository lives at
`/opt/civiclens`. Add these repository secrets:

```bash
gh secret set ORACLE_HOST --body "<public-ip>"
gh secret set ORACLE_USER --body "ubuntu"
gh secret set ORACLE_SSH_KEY < ~/.ssh/civiclens_oracle
# Optional if SSH is not on 22:
# gh secret set ORACLE_SSH_PORT --body "2222"
```

The private key is the same one whose public key you pasted into Oracle. Never
commit it.

For frontend CLI deploys, also set:

```bash
gh secret set VERCEL_TOKEN --body "<vercel-token>"
gh secret set VERCEL_ORG_ID --body "<vercel-org-id>"
gh secret set VERCEL_PROJECT_ID --body "<vercel-project-id>"
```

If you use Vercel's Git integration instead, omit the Vercel secrets; the
workflow skips the CLI deploy and Vercel builds on every push.

After the secrets are set, push any commit to `main` (or run the workflow
manually). The backend job SSHes to the VM and executes
`/opt/civiclens/deploy/oracle/deploy.sh`; the frontend job deploys to Vercel if
the Vercel secrets are present.

## 8. Backups and operations

`setup-host.sh` installs a nightly cron entry:

```text
15 2 * * * ubuntu /opt/civiclens/deploy/oracle/backup.sh
```

It writes gzipped `mongodump` archives to `/opt/civiclens/backups` and keeps
seven days. Qdrant is a derived index; MongoDB is the source of truth.

Manual backup and restore:

```bash
cd /opt/civiclens/deploy/oracle
./backup.sh

# Restore (stop API/worker first):
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

The stack uses per-service memory limits (worker 10 GB, API 3 GB, Mongo and
Qdrant 3 GB each). These are caps, not reservations; steady-state usage is much
lower. On a 12 GB fallback VM, set worker concurrency to `1` and keep an eye on
`docker stats`.

## 9. Updating and rollback

CI/CD updates from `main` automatically. To deploy manually:

```bash
cd /opt/civiclens/deploy/oracle
./deploy.sh
```

The script fetches `origin/main`, resets the checkout, rebuilds, and restarts.
`.env` is untracked and survives. If a release is bad, reset the VM checkout to
the previous commit and re-run the Compose build/up commands; the image is
tagged `civiclens-api:latest`, so keep a note of the last known-good commit.

## 10. Cost and failure modes

- **Oracle Always Free:** no charge for the A1 VM, 200 GB block storage or
  outbound transfer within the allowance. The signup card is for verification.
- **Vercel Hobby:** free for this static site.
- **GitHub Actions:** free for a public repository.
- **No managed database fees:** Mongo, Redis and Qdrant run on the VM.

Known constraints:

- A1 capacity is regional and can be temporarily unavailable.
- Oracle may reclaim an Always Free instance that is genuinely idle for a long
  period. This stack keeps several GB resident (models, Mongo, Qdrant), so it is
  not an idle micro-instance; monitor it if the demo is unused for weeks.
- The VM is a single point of failure. The backup cron covers MongoDB; a real
  production deployment would use managed MongoDB/Qdrant and at least two API
  instances.
- `sslip.io` is a convenience, not a brand domain. For a long-lived deployment,
  point a real domain at the reserved IP and update `API_DOMAIN` and
  `VITE_API_BASE_URL`.
- Caddy's HTTP-01 challenge requires port 80. If port 80 is blocked, switch to a
  DNS-01 setup with a real domain.

## Troubleshooting

| Symptom | Check |
|---|---|
| `docker: permission denied` | Log out/in after `usermod -aG docker`, or `newgrp docker` |
| Caddy cannot get a certificate | DNS resolves to the IP; Oracle security list + UFW allow 80/443; logs |
| API 503 on `/api/v1/health` | `docker compose ... ps`; Mongo/Redis health; logs |
| Empty dashboard after deploy | `docker compose ... logs bootstrap`; Mongo volume; `docker compose ... run --rm bootstrap` |
| Worker OOM / restart loop | `docker stats`; lower `--concurrency` to 1; check NLLB peak |
| Frontend CORS error | `CORS_ORIGINS` exactly matches the Vercel origin; restart `api` |
| Oracle shape out of capacity | Retry another AD or use 2 OCPU / 12 GB |
