#!/usr/bin/env bash
# LAB ERP server install / update on Linux, run as root by the desktop app's "Sunucuma kur" option
# (desktop/remote_install.py uploads this file and laberp-server.tgz to $WORK first).
#   server_install.sh <work dir> <port> <open firewall: 1|0>
# Lines starting with "## " are progress steps shown in the app. Safe to run again: updates the code,
# keeps /var/lib/laberp (database, files, backups) and the admin password.
set -euo pipefail
exec 2>&1

WORK=$1
PORT=$2
FIREWALL=${3:-1}
APP=/opt/laberp
DATA=/var/lib/laberp
ENVF=/etc/laberp.env
export DEBIAN_FRONTEND=noninteractive
# The admin password file never outlives the run, whatever happens
trap 'rm -f "$WORK/admin_password"' EXIT

step() { echo "## $*"; }
fail() { echo "!! $*"; exit 1; }

[ "$(id -u)" = 0 ] || fail "Kurulum yönetici (root/sudo) yetkisi gerektirir"
command -v systemctl >/dev/null || fail "Bu sunucuda systemd yok; desteklenen sistemler: Ubuntu, Debian, Rocky/Alma/RHEL, Fedora"

good_python() {
  "$1" -c 'import sys, venv, ensurepip; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 13) else 1)' 2>/dev/null
}

step "Gerekli paketler kuruluyor (Python)"
if command -v apt-get >/dev/null; then
  apt-get update -qq
  apt-get install -y -qq python3 python3-venv python3-pip curl ca-certificates >/dev/null
elif command -v dnf >/dev/null; then
  dnf install -y -q python3 python3-pip curl >/dev/null
elif command -v yum >/dev/null; then
  yum install -y -q python3 python3-pip curl >/dev/null
elif command -v zypper >/dev/null; then
  zypper --non-interactive -q install python3 python3-pip curl >/dev/null
else
  echo "Paket yöneticisi bulunamadı; sistemdeki Python kullanılacak"
fi

PY=""
for c in python3.12 python3.13 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null && good_python "$(command -v "$c")"; then PY=$(command -v "$c"); break; fi
done

step "Uygulama dosyaları kopyalanıyor"
systemctl stop laberp 2>/dev/null || true
id laberp >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin laberp 2>/dev/null \
  || useradd -r -d "$DATA" -s /sbin/nologin laberp
mkdir -p "$APP" "$DATA" "$DATA/backups"
rm -rf "$APP/backend" "$APP/frontend"
tar -xzf "$WORK/laberp-server.tgz" -C "$APP"

step "Python ortamı hazırlanıyor"
if [ -z "$PY" ]; then
  # No Python 3.10-3.13 from the system: a standalone 3.12 through uv
  echo "Uygun Python yok, uv ile Python 3.12 indiriliyor"
  export UV_INSTALL_DIR=/usr/local/bin UV_PYTHON_INSTALL_DIR=/opt/laberp/python
  command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
  rm -rf "$APP/venv"
  uv venv -q -p 3.12 "$APP/venv"
  VIRTUAL_ENV="$APP/venv" uv pip install -q -r "$APP/backend/requirements.txt"
else
  echo "Python: $PY ($("$PY" -V 2>&1))"
  if [ ! -x "$APP/venv/bin/python" ] || ! good_python "$APP/venv/bin/python"; then
    rm -rf "$APP/venv"
    "$PY" -m venv "$APP/venv"
  fi
  "$APP/venv/bin/python" -m pip install -q --disable-pip-version-check --upgrade pip
  step "Python paketleri yükleniyor (internet gerekir, birkaç dakika sürebilir)"
  "$APP/venv/bin/python" -m pip install -q --disable-pip-version-check -r "$APP/backend/requirements.txt"
fi

step "Ayarlar yazılıyor"
if [ ! -f "$ENVF" ]; then
  cat > "$ENVF" <<EOF
ERP_DATABASE_URL=sqlite:///$DATA/erp.db
ERP_DATA_DIR=$DATA
ERP_BACKUP_DIR=$DATA/backups
EOF
fi
chmod 600 "$ENVF"
NEW_DB=0
[ -f "$DATA/erp.db" ] || NEW_DB=1
set -a; . "$ENVF"; set +a
cd "$APP/backend"
"$APP/venv/bin/python" -m app.cli migrate
if [ -s "$WORK/admin_password" ]; then
  step "Yönetici (admin) şifresi ayarlanıyor"
  "$APP/venv/bin/python" - "$WORK/admin_password" <<'EOF'
import sys
from pathlib import Path
from app.cli import create_admin
create_admin("admin", Path(sys.argv[1]).read_text(encoding="utf-8").strip())
EOF
elif [ "$NEW_DB" = 1 ]; then
  fail "Yeni kurulum için yönetici şifresi gerekli"
fi
chown -R laberp:laberp "$DATA"
chmod 750 "$DATA"

step "Sistem hizmeti kuruluyor (açılışta kendiliğinden başlar)"
cat > /etc/systemd/system/laberp.service <<EOF
[Unit]
Description=LAB ERP server
After=network-online.target
Wants=network-online.target

[Service]
User=laberp
Group=laberp
WorkingDirectory=$APP/backend
EnvironmentFile=$ENVF
Environment=ERP_SUPERVISED=1
ExecStart=$APP/venv/bin/python -m app.cli serve --host 0.0.0.0 --port $PORT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now laberp >/dev/null 2>&1
systemctl restart laberp

if [ "$FIREWALL" = 1 ]; then
  step "Güvenlik duvarında port $PORT açılıyor"
  if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw allow "$PORT/tcp" >/dev/null && echo "ufw: $PORT/tcp açıldı"
  fi
  if command -v firewall-cmd >/dev/null && firewall-cmd --state >/dev/null 2>&1; then
    firewall-cmd -q --permanent --add-port="$PORT/tcp" && firewall-cmd -q --reload && echo "firewalld: $PORT/tcp açıldı"
  fi
  # LAN discovery (Ağda sunucu ara) uses UDP 47811
  if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then ufw allow 47811/udp >/dev/null || true; fi
  if command -v firewall-cmd >/dev/null && firewall-cmd --state >/dev/null 2>&1; then
    firewall-cmd -q --permanent --add-port=47811/udp && firewall-cmd -q --reload || true
  fi
fi

step "Sunucu başlatılıyor"
for _ in $(seq 1 60); do
  if "$APP/venv/bin/python" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$PORT/api/health', timeout=2)" 2>/dev/null; then
    rm -rf "$WORK"
    echo "OK http://0.0.0.0:$PORT"
    exit 0
  fi
  sleep 1
done
journalctl -u laberp -n 30 --no-pager || true
fail "Sunucu 60 saniyede yanıt vermedi (günlük yukarıda)"
