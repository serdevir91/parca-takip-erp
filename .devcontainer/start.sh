#!/usr/bin/env bash
# Start the app on every codespace start (port 8000 opens in the browser). Log: .demo/erp.log
cd "$(dirname "$0")/../backend"
pkill -f "app.cli serve" 2>/dev/null || true
mkdir -p ../.demo
DETACH=""; command -v setsid > /dev/null && DETACH=setsid
$DETACH nohup .venv/bin/python -m app.cli serve --port 8000 --no-backup > ../.demo/erp.log 2>&1 < /dev/null &
for _ in $(seq 1 30); do
  curl -sf http://localhost:8000/api/health > /dev/null && { echo "Parça Takip ERP hazır: port 8000 (admin / admin)"; exit 0; }
  sleep 1
done
echo "Sunucu açılmadı, günlük: .demo/erp.log"
