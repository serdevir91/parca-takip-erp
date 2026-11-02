#!/usr/bin/env sh
# Manual backup (the "backup" service already takes one every day).
#   deploy/backup.sh                 -> new backup in the backups volume
#   deploy/backup.sh /mnt/usb        -> also copy the new backup file to /mnt/usb
#   deploy/backup.sh --list          -> list backups
set -eu
cd "$(dirname "$0")/.."
# Docker Compose v2 plugin or the standalone docker-compose binary
if docker compose version >/dev/null 2>&1; then DC="docker compose"; else DC="docker-compose"; fi

if [ "${1:-}" = "--list" ]; then
  exec $DC exec -T backend sh -c 'ls -lh /backups/erp_*.tar 2>/dev/null || echo "Yedek yok"'
fi

$DC exec -T backend python -m app.cli backup
if [ -n "${1:-}" ]; then
  mkdir -p "$1"
  name=$($DC exec -T backend sh -c 'ls -1t /backups/erp_*.tar | head -n1' | tr -d '\r')
  $DC cp "backend:$name" "$1/"
  echo "Kopyalandı: $1/$(basename "$name")"
fi
