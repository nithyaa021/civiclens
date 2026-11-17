#!/usr/bin/env bash
# Nightly logical MongoDB backup for the single-VM demo.
#
# Qdrant is a derived index: it can be rebuilt from MongoDB by rerunning the
# seeding/enrichment pipeline.  MongoDB is the source of truth, so it is the
# backup target here.
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "Missing deploy/oracle/.env" >&2
  exit 1
fi

get_env() {
  sed -n "s/^$1=//p" .env | head -n1
}

MONGO_ROOT_USER="$(get_env MONGO_ROOT_USER)"
MONGO_ROOT_PASSWORD="$(get_env MONGO_ROOT_PASSWORD)"
MONGO_DB="$(get_env MONGO_DB)"
BACKUP_DIR="${BACKUP_DIR:-/opt/civiclens/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

if [ -z "$MONGO_ROOT_USER" ] || [ -z "$MONGO_ROOT_PASSWORD" ] || [ -z "$MONGO_DB" ]; then
  echo "Mongo credentials are incomplete in deploy/oracle/.env" >&2
  exit 1
fi

install -d -m 0700 "$BACKUP_DIR"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="$BACKUP_DIR/mongo-$timestamp.archive.gz"

docker compose --env-file .env -f docker-compose.prod.yml exec -T mongo \
  mongodump \
  --uri="mongodb://${MONGO_ROOT_USER}:${MONGO_ROOT_PASSWORD}@localhost:27017/${MONGO_DB}?authSource=admin" \
  --gzip \
  --archive >"$target"

chmod 0600 "$target"
find "$BACKUP_DIR" -type f -name 'mongo-*.archive.gz' -mtime "+${RETENTION_DAYS}" -delete

echo "Mongo backup written to $target ($(du -h "$target" | cut -f1))"
