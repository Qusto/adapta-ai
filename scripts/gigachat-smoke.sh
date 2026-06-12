#!/usr/bin/env bash
# GigaChat smoke: OAuth (Authorization Key → access_token) → GET /models.
# Requires infra/.env loaded (or env vars exported by caller).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${REPO_ROOT}/infra/.env"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
  set +a
fi

: "${GIGACHAT_AUTHORIZATION_KEY:?GIGACHAT_AUTHORIZATION_KEY missing}"
: "${GIGACHAT_OAUTH_URL:?GIGACHAT_OAUTH_URL missing}"
: "${GIGACHAT_BASE_URL:?GIGACHAT_BASE_URL missing}"
: "${GIGACHAT_SCOPE:=GIGACHAT_API_PERS}"

CA_BUNDLE="${REPO_ROOT}/infra/certs/russian_trusted_root_ca.pem"
RQUID="$(uuidgen 2>/dev/null || python3 -c 'import uuid; print(uuid.uuid4())')"

echo "==> OAuth: POST ${GIGACHAT_OAUTH_URL} (scope=${GIGACHAT_SCOPE})"
TOKEN=$(curl -fsSL -X POST "${GIGACHAT_OAUTH_URL}" \
  --cacert "${CA_BUNDLE}" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -H 'Accept: application/json' \
  -H "RqUID: ${RQUID}" \
  -H "Authorization: Basic ${GIGACHAT_AUTHORIZATION_KEY}" \
  --data-urlencode "scope=${GIGACHAT_SCOPE}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo "Access token: ${TOKEN:0:30}..."

echo "==> GET ${GIGACHAT_BASE_URL}/models"
curl -fsSL "${GIGACHAT_BASE_URL}/models" \
  --cacert "${CA_BUNDLE}" \
  -H "Authorization: Bearer ${TOKEN}" \
  | python3 -m json.tool | head -30

echo "OK: GigaChat smoke passed."
