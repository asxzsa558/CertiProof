#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
warn() { printf 'WARN: %s\n' "$*" >&2; }

[[ "$(uname -s)" == "Linux" ]] || fail "Published cloud images require Linux."
case "$(uname -m)" in
  x86_64|amd64) ;;
  *) fail "Published cloud images currently target linux/amd64." ;;
esac
[[ -f .env ]] || fail "Copy .env.example to .env and configure it first."
docker info >/dev/null 2>&1 || fail "Docker Engine is not running or current user cannot access it."

if docker compose version >/dev/null 2>&1; then
  compose=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  compose=(docker-compose)
else
  fail "Docker Compose plugin is required."
fi

env_value() {
  local key="$1"
  sed -n "s/^${key}=//p" .env | tail -1 | sed 's/^['"'\''']//;s/['"'\''']$//'
}

password="$(env_value POSTGRES_PASSWORD)"
secret="$(env_value SECRET_KEY)"
domain="$(env_value CERTIPROOF_DOMAIN)"
policy="$(env_value LLM_RUNTIME_POLICY)"

[[ ${#password} -ge 20 && "$password" != replace-with-* ]] || fail "POSTGRES_PASSWORD must be at least 20 characters."
[[ "$password" =~ ^[A-Za-z0-9._~-]+$ ]] || fail "POSTGRES_PASSWORD must use URL-safe characters: letters, digits, dot, underscore, tilde or hyphen."
[[ ${#secret} -ge 32 && "$secret" != replace-with-* ]] || fail "SECRET_KEY must be at least 32 non-placeholder characters."
[[ -n "$domain" && "$domain" != *.example.com ]] || fail "Set the real CERTIPROOF_DOMAIN and matching DNS record."

profiles=(--profile production)
case "$policy" in
  cloud)
    [[ -n "$(env_value OPENAI_MODEL)" && "$(env_value OPENAI_MODEL)" != replace-with-* ]] || fail "Set OPENAI_MODEL."
    [[ -n "$(env_value OPENAI_API_KEY)" && "$(env_value OPENAI_API_KEY)" != replace-with-* ]] || fail "Set OPENAI_API_KEY."
    ;;
  vllm|auto)
    command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1 || fail "GPU deployment requires a working NVIDIA driver."
    docker info --format '{{json .Runtimes}}' | grep -q nvidia || fail "Configure nvidia-container-toolkit for Docker."
    profiles+=(--profile gpu)
    ;;
  *) fail "Cloud package supports LLM_RUNTIME_POLICY=cloud or vllm." ;;
esac

memory_kb="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
(( memory_kb >= 30 * 1024 * 1024 )) || warn "Less than 30 GB RAM detected; document and tool concurrency will be constrained."
available_kb="$(df -Pk . | awk 'NR==2 {print $4}')"
(( available_kb >= 100 * 1024 * 1024 )) || warn "Less than 100 GB free disk detected; images, uploads and model caches may fill it."

"${compose[@]}" "${profiles[@]}" config --quiet
printf 'Preflight passed: policy=%s architecture=%s compose=%s\n' "$policy" "$(uname -m)" "${compose[*]}"
