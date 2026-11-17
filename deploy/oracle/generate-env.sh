#!/usr/bin/env bash
# Generate deploy/oracle/.env with strong, independent secrets.
#
#   ./generate-env.sh api.203.0.113.10.sslip.io https://civiclens.vercel.app you@example.com
#
# The API domain can be derived from the VM's reserved public IPv4 address:
#   api.<ip-with-dashes-or-dots>.sslip.io
# sslip.io resolves the embedded address, so no DNS provider is required.
set -euo pipefail

cd "$(dirname "$0")"

if [ -f .env ]; then
  echo ".env already exists. Move it away before generating a new one." >&2
  exit 1
fi

API_DOMAIN="${1:?usage: $0 <api-domain> <cors-origin> [acme-email]}"
CORS_ORIGIN="${2:?usage: $0 <api-domain> <cors-origin> [acme-email]}"
ACME_EMAIL="${3:-admin@example.com}"

case "$API_DOMAIN" in
  *://*) echo "API_DOMAIN must not include a scheme (http:// or https://)." >&2; exit 1 ;;
  */*)   echo "API_DOMAIN must be a hostname only." >&2; exit 1 ;;
esac
case "$CORS_ORIGIN" in
  http://*|https://*) ;;
  *) echo "CORS_ORIGIN must start with http:// or https://." >&2; exit 1 ;;
esac

CORS_ORIGIN="${CORS_ORIGIN%/}"

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required. Install it with: sudo apt-get install -y openssl" >&2
  exit 1
fi

MONGO_ROOT_PASSWORD="$(openssl rand -hex 24)"
REDIS_PASSWORD="$(openssl rand -hex 24)"
QDRANT_API_KEY="$(openssl rand -hex 24)"
JWT_SECRET="$(openssl rand -hex 48)"

sed \
  -e "s|^API_DOMAIN=.*|API_DOMAIN=${API_DOMAIN}|" \
  -e "s|^ACME_EMAIL=.*|ACME_EMAIL=${ACME_EMAIL}|" \
  -e "s|^CORS_ORIGINS=.*|CORS_ORIGINS=[\"${CORS_ORIGIN}\"]|" \
  -e "s|^MONGO_ROOT_PASSWORD=.*|MONGO_ROOT_PASSWORD=${MONGO_ROOT_PASSWORD}|" \
  -e "s|^REDIS_PASSWORD=.*|REDIS_PASSWORD=${REDIS_PASSWORD}|" \
  -e "s|^QDRANT_API_KEY=.*|QDRANT_API_KEY=${QDRANT_API_KEY}|" \
  -e "s|^JWT_SECRET=.*|JWT_SECRET=${JWT_SECRET}|" \
  .env.example > .env

chmod 600 .env

echo "Wrote deploy/oracle/.env with generated secrets."
echo "API origin: https://${API_DOMAIN}"
echo "CORS origin: ${CORS_ORIGIN}"
echo "Next: ./deploy.sh"
