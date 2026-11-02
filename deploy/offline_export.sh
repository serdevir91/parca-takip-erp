#!/usr/bin/env sh
# Run on a machine WITH internet: build the images and save everything needed for an
# offline install into dist-offline/ (copy that folder to the offline server).
#   deploy/offline_export.sh [tag]
set -eu
cd "$(dirname "$0")/.."
# Docker Compose v2 plugin or the standalone docker-compose binary
if docker compose version >/dev/null 2>&1; then DC="docker compose"; else DC="docker-compose"; fi
TAG="${1:-${ERP_TAG:-latest}}"
PREFIX="${ERP_IMAGE_PREFIX:-parca-takip}"
OUT=dist-offline
export ERP_TAG="$TAG" ERP_IMAGE_PREFIX="$PREFIX"

echo "İmajlar hazırlanıyor (etiket: $TAG)..."
$DC build --pull
docker pull postgres:16-alpine

mkdir -p "$OUT"
IMAGES="$PREFIX-backend:$TAG $PREFIX-frontend:$TAG postgres:16-alpine"
echo "Kaydediliyor: $IMAGES"
# shellcheck disable=SC2086
docker save -o "$OUT/parca-takip-images-$TAG.tar" $IMAGES

cp docker-compose.yml .env.example README.md "$OUT/"
mkdir -p "$OUT/deploy"
cp deploy/*.sh deploy/*.ps1 "$OUT/deploy/"
( cd "$OUT" && sha256sum "parca-takip-images-$TAG.tar" > "parca-takip-images-$TAG.tar.sha256" 2>/dev/null \
  || shasum -a 256 "parca-takip-images-$TAG.tar" > "parca-takip-images-$TAG.tar.sha256" )

echo "Hazır: $OUT/ ($(du -h "$OUT/parca-takip-images-$TAG.tar" | cut -f1))"
echo "Bu klasörü sunucuya kopyalayın ve orada deploy/offline_import.sh çalıştırın."
