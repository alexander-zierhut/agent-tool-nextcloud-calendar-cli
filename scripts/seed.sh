#!/usr/bin/env bash
# Seed the local test stack: users alex + bob (with e-mail addresses, so the
# server can schedule between them). Idempotent. Never point this at a real server.
set -euo pipefail
cd "$(dirname "$0")/.."
ready=""
for _ in $(seq 1 90); do
  if docker compose exec -T -u www-data nextcloud php occ status 2>/dev/null | grep -q "installed: true"; then ready=1; break; fi
  sleep 3
done
if [ -z "$ready" ]; then
  echo "Nextcloud did not finish installing within 270 s; see: docker compose logs nextcloud" >&2
  exit 1
fi
for u in alex bob; do
  docker compose exec -T -u www-data -e OC_PASS="test-pw-$u-123456" nextcloud \
    php occ user:add --password-from-env --display-name "$u" "$u" >/dev/null 2>&1 || true
  docker compose exec -T -u www-data nextcloud php occ user:setting "$u" settings email "$u@example.test"
done
echo "seeded: alex/test-pw-alex-123456, bob/test-pw-bob-123456 at http://127.0.0.1:${NC_PORT:-8089}"
