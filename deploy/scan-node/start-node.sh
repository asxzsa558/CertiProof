#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
[[ -f .env ]] || { echo "Missing .env; copy .env.example and configure it" >&2; exit 2; }
grep -Eq '^CONTROL_PLANE_URL=https://' .env || grep -Eq '^ALLOW_INSECURE_CONTROL_PLANE=true$' .env || {
  echo "CONTROL_PLANE_URL must use HTTPS" >&2
  exit 2
}
if docker compose version >/dev/null 2>&1; then
  compose=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  compose=(docker-compose)
else
  echo "Docker Compose plugin is required" >&2
  exit 2
fi
if [[ -f images.tar ]]; then
  docker load -i images.tar
  "${compose[@]}" -f docker-compose.remote-node.yml up -d --pull never
else
  "${compose[@]}" -f docker-compose.remote-node.yml pull
  "${compose[@]}" -f docker-compose.remote-node.yml up -d
fi
