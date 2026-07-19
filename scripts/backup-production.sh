#!/bin/sh
set -eu

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
destination="${1:-./backups/$stamp}"
mkdir -p "$destination"

docker-compose exec -T db sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "$destination/certiproof.dump"

docker-compose exec -T backend \
  tar -C /app -czf - uploads > "$destination/uploads.tar.gz"

if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$destination/certiproof.dump" "$destination/uploads.tar.gz" > "$destination/SHA256SUMS"
else
  shasum -a 256 "$destination/certiproof.dump" "$destination/uploads.tar.gz" > "$destination/SHA256SUMS"
fi
printf 'Backup written to %s\n' "$destination"
