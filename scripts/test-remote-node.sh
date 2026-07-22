#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
project="certiproof-remote-acceptance"
compose=(docker-compose -p "$project" -f "$root/deploy/scan-node/docker-compose.remote-node.yml" -f "$root/tests/remote-node-compose.acceptance.yml")

# The source tree is not mounted into production containers, so run the checked-in
# acceptance module through a temporary read-only mount using the current backend image.
acceptance_python() {
  docker-compose -f "$root/docker-compose.yml" run --rm -T --no-deps \
    -v "$root/backend:/app:ro" -v "$root/scripts:/workspace/scripts:ro" \
    -w /workspace -e PYTHONPATH=/app backend python scripts/remote_node_acceptance.py "$@"
}

cleanup() {
  "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  acceptance_python cleanup >/dev/null 2>&1 || true
}
trap cleanup EXIT

setup_json="$(acceptance_python setup | tail -n 1)"
read -r project_id user_id node_id enroll_token < <(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["project_id"], d["user_id"], d["node_id"], d["enrollment_token"])' <<<"$setup_json")

export CERTIPROOF_IMAGE_PREFIX=certiproof
export CERTIPROOF_VERSION=latest
export CONTROL_PLANE_URL=http://backend:8000
export ENROLL_TOKEN="$enroll_token"
export NODE_LOCAL_SECRET=remote-acceptance-secret-with-32-characters
export ALLOW_INSECURE_CONTROL_PLANE=true
"${compose[@]}" up -d --pull never

for _ in {1..60}; do
  if "${compose[@]}" logs node 2>&1 | grep -q "节点注册完成"; then break; fi
  sleep 2
done
"${compose[@]}" logs node 2>&1 | grep -q "节点注册完成" || { "${compose[@]}" logs node; exit 1; }

acceptance_python run --project-id "$project_id" --user-id "$user_id" --node-id "$node_id"
