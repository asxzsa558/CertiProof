#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
variant="${1:-all}"
version="${CERTIPROOF_VERSION:-latest}"
out="$root/dist/cloud"
[[ "$version" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "Invalid image version: $version" >&2; exit 2; }

case "$variant" in
  cpu|gpu) variants=("$variant") ;;
  all) variants=(cpu gpu) ;;
  *) echo "Usage: $0 [cpu|gpu|all]" >&2; exit 2 ;;
esac

mkdir -p "$out"
work="$(mktemp -d "${TMPDIR:-/tmp}/certiproof-cloud.XXXXXX")"
trap 'rm -rf "$work"' EXIT

for item in "${variants[@]}"; do
  name="certiproof-cloud-${item}-${version}"
  dir="$work/$name"
  mkdir -p "$dir/docker" "$dir/scripts"
  cp "$root/docker-compose.yml" "$dir/"
  cp "$root/docker/Caddyfile" "$dir/docker/"
  cp -R "$root/reference" "$dir/"
  cp "$root/deploy/cloud/README.md" "$dir/"
  cp "$root/deploy/cloud/.env.${item}.example" "$dir/.env.example"
  sed -i.bak "s/^CERTIPROOF_VERSION=.*/CERTIPROOF_VERSION=${version}/" "$dir/.env.example"
  rm "$dir/.env.example.bak"
  cp "$root/scripts/start-production.sh" "$root/scripts/cloud-preflight.sh" "$root/scripts/backup-production.sh" "$dir/scripts/"
  chmod +x "$dir/scripts/"*.sh
  tar -C "$work" -czf "$out/$name.tar.gz" "$name"
done

if command -v sha256sum >/dev/null 2>&1; then
  (cd "$out" && sha256sum ./*.tar.gz > SHA256SUMS)
else
  (cd "$out" && shasum -a 256 ./*.tar.gz > SHA256SUMS)
fi
printf 'Cloud packages written to %s\n' "$out"
