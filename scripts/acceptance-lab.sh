#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

if docker compose version >/dev/null 2>&1; then
  compose=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  compose=(docker-compose)
else
  echo "Docker Compose is required." >&2
  exit 1
fi

profile=(--profile acceptance)

wait_healthy() {
  local deadline=$((SECONDS + 120)) id health
  while ((SECONDS < deadline)); do
    id="$("${compose[@]}" "${profile[@]}" ps -q e2e-target)"
    if [[ -n "$id" ]]; then
      health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id")"
      [[ "$health" == "healthy" ]] && return 0
    fi
    sleep 2
  done
  "${compose[@]}" "${profile[@]}" logs e2e-target
  echo "Acceptance target did not become healthy." >&2
  return 1
}

start() {
  "${compose[@]}" "${profile[@]}" up -d --build e2e-target
  wait_healthy
  echo "Acceptance target is ready as Docker-network asset: e2e-target"
  echo "Use chat, quick actions, or / commands in a project containing that asset."
}

case "${1:-status}" in
  start)
    start
    ;;
  reset)
    "${compose[@]}" "${profile[@]}" rm -sf e2e-target >/dev/null 2>&1 || true
    start
    ;;
  stop)
    "${compose[@]}" "${profile[@]}" stop e2e-target
    ;;
  status)
    "${compose[@]}" "${profile[@]}" ps e2e-target
    id="$("${compose[@]}" "${profile[@]}" ps -q e2e-target)"
    [[ -n "$id" ]] || exit 1
    docker inspect -f 'state={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$id"
    ;;
  list)
    python3 backend/scripts/check_security_tools_acceptance.py --list
    ;;
  matrix)
    start
    mode="${2:-quick}"
    [[ "$mode" == "quick" || "$mode" == "full" ]] || { echo "matrix profile must be quick or full" >&2; exit 2; }
    mkdir -p artifacts
    "${compose[@]}" run --rm -T --no-deps \
      -v "$root/backend:/app:ro" \
      -v "$root/artifacts:/workspace/artifacts" \
      -e MCP_GATEWAY_URL=http://mcp-gateway:9000 \
      -e CP_ACCEPTANCE_TARGET=e2e-target \
      backend python scripts/check_security_tools_acceptance.py \
      --profile "$mode" --output "/workspace/artifacts/security-tools-${mode}-acceptance.json"
    ;;
  *)
    echo "Usage: $0 {start|reset|stop|status|list|matrix [quick|full]}" >&2
    exit 2
    ;;
esac
