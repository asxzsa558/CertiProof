#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
target="${1:-}"
[[ "$target" =~ ^[A-Za-z0-9._-]+$ && "$target" != "latest" ]] || {
  echo "Usage: $0 <immutable-version>" >&2
  exit 2
}
[[ -f .env ]] || { echo ".env is required." >&2; exit 1; }

backup="$(mktemp "${TMPDIR:-/tmp}/certiproof-env.XXXXXX")"
cp .env "$backup"
previous="$(sed -n 's/^CERTIPROOF_VERSION=//p' .env | tail -1)"

set_version() {
  local version="$1"
  if grep -q '^CERTIPROOF_VERSION=' .env; then
    sed -i.bak "s/^CERTIPROOF_VERSION=.*/CERTIPROOF_VERSION=${version}/" .env
    rm -f .env.bak
  else
    printf '\nCERTIPROOF_VERSION=%s\n' "$version" >> .env
  fi
}

set_version "$target"
if CERTIPROOF_DEPLOY_MODE=images ./scripts/start-production.sh --images \
  && ./scripts/verify-deployment.sh; then
  rm -f "$backup"
  printf 'Rollback completed: %s -> %s\n' "${previous:-unknown}" "$target"
  exit 0
fi

echo "Rollback target failed verification; restoring ${previous:-previous configuration}." >&2
cp "$backup" .env
rm -f "$backup"
CERTIPROOF_DEPLOY_MODE=images ./scripts/start-production.sh --images
./scripts/verify-deployment.sh
exit 1
