#!/usr/bin/env bash
# Pull the current main branch and roll the production stack forward.
#
# Run from the VM:
#   cd /opt/civiclens/deploy/oracle
#   ./deploy.sh
#
# The script is safe to re-run.  warmup/bootstrap are idempotent; the API is
# only restarted after the corpus and model artifacts are present.
set -euo pipefail

cd "$(dirname "$0")"
REPO_ROOT="$(cd ../.. && pwd)"
SCRIPT_PATH="$PWD/$(basename "$0")"

if [ ! -f .env ]; then
  echo "Missing deploy/oracle/.env. Run ./generate-env.sh first." >&2
  exit 1
fi
if grep -Eq '^(MONGO_ROOT_PASSWORD|REDIS_PASSWORD|QDRANT_API_KEY|JWT_SECRET)=replace-' .env; then
  echo "deploy/oracle/.env still contains placeholder secrets. Run ./generate-env.sh." >&2
  exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "docker is not installed. Run ./setup-host.sh first." >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose v2 is not available. Run ./setup-host.sh first." >&2
  exit 1
fi

API_DOMAIN="$(sed -n 's/^API_DOMAIN=//p' .env | head -n1)"
echo "==> Deploying CivicLens to https://${API_DOMAIN}"

echo "==> Updating source"
BEFORE_REV="$(git -C "$REPO_ROOT" rev-parse HEAD)"
git -C "$REPO_ROOT" fetch --prune origin main
git -C "$REPO_ROOT" reset --hard FETCH_HEAD
AFTER_REV="$(git -C "$REPO_ROOT" rev-parse HEAD)"
echo "    ${BEFORE_REV:0:7} -> ${AFTER_REV:0:7}"

# `git reset --hard` above rewrote this very script on disk.  bash reads a
# script incrementally by byte offset, so continuing would execute a mixture of
# the old and new file.  Re-exec the updated script once, then carry on.
if [ "${CIVICLENS_DEPLOY_REEXEC:-0}" != "1" ] && [ "$BEFORE_REV" != "$AFTER_REV" ]; then
  echo "==> Deploy script changed; re-executing the updated copy"
  export CIVICLENS_DEPLOY_REEXEC=1
  exec "$SCRIPT_PATH" "$@"
fi

COMPOSE=(docker compose --env-file .env -f docker-compose.prod.yml)

echo "==> Building API/worker image"
"${COMPOSE[@]}" build

echo "==> Starting stack (first boot seeds the ~3,400-3,500 complaint corpus)"
"${COMPOSE[@]}" up -d --remove-orphans

echo "==> Waiting for the API to become healthy (first boot downloads ~1.5 GB of models)"
for attempt in $(seq 1 360); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "API liveness is up after $((attempt * 5))s."
    break
  fi
  if [ "$attempt" -eq 360 ]; then
    echo "API did not become healthy within 30 minutes. Recent logs:" >&2
    "${COMPOSE[@]}" logs --tail=120 api bootstrap warmup caddy >&2 || true
    exit 1
  fi
  sleep 5
done

echo "==> Checking dependency readiness"
if ! curl -fsS http://127.0.0.1:8000/api/v1/health; then
  echo "Dependency readiness failed. Recent API logs:" >&2
  "${COMPOSE[@]}" logs --tail=120 api >&2 || true
  exit 1
fi
echo

"${COMPOSE[@]}" ps
docker image prune -f >/dev/null 2>&1 || true

echo
echo "Deployment complete:"
echo "  API:   https://${API_DOMAIN}"
echo "  Docs:  https://${API_DOMAIN}/docs"
echo "  Health: https://${API_DOMAIN}/api/v1/health"
