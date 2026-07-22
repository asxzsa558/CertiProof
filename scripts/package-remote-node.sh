#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
variant="${1:-online}"
version="${CERTIPROOF_VERSION:-dev-$(git -C "$root" rev-parse --short HEAD)}"
prefix="${CERTIPROOF_IMAGE_PREFIX:-ghcr.io/asxzsa558/certiproof}"
[[ "$variant" == "online" || "$variant" == "offline" ]] || { echo "Usage: $0 [online|offline]" >&2; exit 2; }
[[ "$version" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "Invalid version: $version" >&2; exit 2; }

out="$root/dist/scan-node"
name="certiproof-scan-node-${variant}-${version}"
work="$(mktemp -d "${TMPDIR:-/tmp}/certiproof-node.XXXXXX")"
trap 'rm -rf "$work"' EXIT
mkdir -p "$out" "$work/$name/keys"
cp "$root/deploy/scan-node/docker-compose.remote-node.yml" "$work/$name/"
cp "$root/deploy/scan-node/.env.example" "$work/$name/.env.example"
cp "$root/deploy/scan-node/README.md" "$root/deploy/scan-node/start-node.sh" "$work/$name/"
chmod +x "$work/$name/start-node.sh"
sed -i.bak "s|^CERTIPROOF_IMAGE_PREFIX=.*|CERTIPROOF_IMAGE_PREFIX=${prefix}|; s/^CERTIPROOF_VERSION=.*/CERTIPROOF_VERSION=${version}/" "$work/$name/.env.example"
rm "$work/$name/.env.example.bak"

if [[ "$variant" == "offline" ]]; then
  images=(backend mcp-gateway security-tools ssh-checker fast-scanner web-tools network-tools db-tools windows-tools)
  refs=()
  for image in "${images[@]}"; do
    ref="${prefix}/${image}:${version}"
    docker image inspect "$ref" >/dev/null 2>&1 || docker pull "$ref"
    refs+=("$ref")
  done
  docker save -o "$work/$name/images.tar" "${refs[@]}"
fi

tar -C "$work" -czf "$out/$name.tar.gz" "$name"
if command -v sha256sum >/dev/null 2>&1; then
  (cd "$out" && sha256sum ./*.tar.gz > SHA256SUMS)
else
  (cd "$out" && shasum -a 256 ./*.tar.gz > SHA256SUMS)
fi
echo "Remote node package written to $out/$name.tar.gz"
