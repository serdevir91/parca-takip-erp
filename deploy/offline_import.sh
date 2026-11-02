#!/usr/bin/env sh
# Run on the OFFLINE server inside the copied dist-offline folder (or the repo root):
# loads the images and starts the system without internet.
#   deploy/offline_import.sh [images.tar]
set -eu
cd "$(dirname "$0")/.."
# Docker Compose v2 plugin or the standalone docker-compose binary
if docker compose version >/dev/null 2>&1; then DC="docker compose"; else DC="docker-compose"; fi
TAR="${1:-}"
if [ -z "$TAR" ]; then
  TAR=$(ls -1t parca-takip-images-*.tar dist-offline/parca-takip-images-*.tar 2>/dev/null | head -n1 || true)
fi
[ -n "$TAR" ] && [ -f "$TAR" ] || { echo "İmaj dosyası bulunamadı (parca-takip-images-*.tar)"; exit 1; }

if [ -f "$TAR.sha256" ]; then
  ( cd "$(dirname "$TAR")" && (sha256sum -c "$(basename "$TAR").sha256" 2>/dev/null \
    || shasum -a 256 -c "$(basename "$TAR").sha256") ) || { echo "Sağlama toplamı tutmuyor, dosya bozuk"; exit 1; }
fi

echo "İmajlar yükleniyor: $TAR"
docker load -i "$TAR"

TAG=$(basename "$TAR" .tar | sed 's/^parca-takip-images-//')
if [ ! -f .env ]; then
  cp .env.example .env
  echo ".env oluşturuldu. Şifreleri değiştirip bu betiği tekrar çalıştırın."
  exit 0
fi
if grep -q '^ERP_TAG=' .env; then
  sed -i.bak "s/^ERP_TAG=.*/ERP_TAG=$TAG/" .env && rm -f .env.bak
else
  echo "ERP_TAG=$TAG" >> .env
fi

$DC up -d --no-build
$DC ps
echo "Kurulum tamam. Tarayıcıdan http://SUNUCU_IP:$(grep '^ERP_HTTP_PORT=' .env | cut -d= -f2 || echo 80) adresini açın."
