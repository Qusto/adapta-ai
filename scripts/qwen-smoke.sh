#!/usr/bin/env bash
# Qwen via OpenRouter smoke: small chat completion request.
# Robust: saves response to temp file, checks HTTP code, tolerates leading
# whitespace some OpenRouter providers (DeepInfra) prepend before the JSON body.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${REPO_ROOT}/infra/.env"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
  set +a
fi

: "${OPENROUTER_API_KEY:?OPENROUTER_API_KEY missing}"
: "${OPENROUTER_BASE_URL:=https://openrouter.ai/api/v1}"
: "${QWEN_MODEL:=qwen/qwen-2.5-72b-instruct}"

# strip trailing slash from base url to avoid //chat/completions
BASE="${OPENROUTER_BASE_URL%/}"
RESP="$(mktemp)"
trap 'rm -f "${RESP}"' EXIT

echo "==> POST ${BASE}/chat/completions (model=${QWEN_MODEL})"
HTTP=$(curl -sS -o "${RESP}" -w "%{http_code}" -X POST "${BASE}/chat/completions" \
  -H "Authorization: Bearer ${OPENROUTER_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"model":"'"${QWEN_MODEL}"'","messages":[{"role":"user","content":"Translate to Russian: Hello"}],"max_tokens":20}')

if [[ "${HTTP}" != "200" ]]; then
  echo "FAIL: HTTP ${HTTP}"
  cat "${RESP}"
  exit 1
fi

# json.load tolerates leading whitespace; read from file (not pipe) for robustness
python3 -c "import json,sys; d=json.load(open('${RESP}')); print('OK:', d['choices'][0]['message']['content'].strip())"
