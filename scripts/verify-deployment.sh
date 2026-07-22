#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if docker compose version >/dev/null 2>&1; then
  compose=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  compose=(docker-compose)
else
  echo "Docker Compose is required." >&2
  exit 1
fi

services=(
  db redis frontend backend mcp-gateway embedding-server ocr-server
  security-tools ssh-checker fast-scanner web-tools network-tools db-tools windows-tools
  interactive-worker document-worker assessment-worker verification-worker maintenance-worker
)
deadline=$((SECONDS + ${DEPLOYMENT_HEALTH_TIMEOUT_SECONDS:-300}))

while true; do
  pending=()
  for service in "${services[@]}"; do
    container_id="$("${compose[@]}" ps -q "$service")"
    if [[ -z "$container_id" ]]; then
      pending+=("$service:not-running")
      continue
    fi
    state="$(docker inspect -f '{{.State.Status}}' "$container_id")"
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id")"
    [[ "$state" == "running" && "$health" == "healthy" ]] || pending+=("$service:$state/$health")
  done
  ((${#pending[@]} == 0)) && break
  if ((SECONDS >= deadline)); then
    printf 'Deployment health timeout: %s\n' "${pending[*]}" >&2
    exit 1
  fi
  printf 'Waiting for services: %s\n' "${pending[*]}"
  sleep 5
done

"${compose[@]}" exec -T backend python -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)"
"${compose[@]}" exec -T frontend python -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:80/health', timeout=5)"

edge_id="$("${compose[@]}" ps -q edge 2>/dev/null || true)"
if [[ -n "$edge_id" ]]; then
  edge_state="$(docker inspect -f '{{.State.Status}}' "$edge_id")"
  [[ "$edge_state" == "running" ]] || {
    echo "Production edge is not running: $edge_state" >&2
    exit 1
  }
  domain="${CERTIPROOF_DOMAIN:-$(sed -n 's/^CERTIPROOF_DOMAIN=//p' .env 2>/dev/null | tail -1)}"
  if [[ -n "$domain" && "$domain" != "localhost" && "$domain" != "certiproof.example.com" ]]; then
    curl --fail --silent --show-error --retry 3 --max-time 15 "https://${domain}/health" >/dev/null
  fi
fi

if [[ "${VERIFY_DEEP_DEPLOYMENT:-true}" == "true" ]]; then
  if command -v timeout >/dev/null 2>&1; then
    timeout "${DEPLOYMENT_DEEP_TIMEOUT_SECONDS:-900}" \
      "${compose[@]}" exec -T backend python -m app.deployment_check
  else
    "${compose[@]}" exec -T backend python -m app.deployment_check
  fi
fi

version="$(sed -n 's/^CERTIPROOF_VERSION=//p' .env 2>/dev/null | tail -1)"
printf 'Deployment verified: version=%s services=%d deep=%s\n' \
  "${version:-source-build}" "${#services[@]}" "${VERIFY_DEEP_DEPLOYMENT:-true}"
