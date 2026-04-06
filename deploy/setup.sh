#!/usr/bin/env bash
set -euo pipefail

APP_USER="onlybots"
APP_DIR="/opt/onlybots"
EVIDENCE_DIR="/opt/onlybots/evidence"
SRC_DIR="${1:-/tmp/onlybots-src}"

echo "==> Installing system packages"
apt-get update -qq
apt-get install -y -qq nodejs npm python3 python3-venv python3-pip postgresql postgresql-contrib nginx certbot python3-certbot-nginx curl

# Install Node.js 20 via NodeSource if system node is too old
NODE_MAJOR=$(node --version 2>/dev/null | cut -d. -f1 | tr -d 'v' || echo "0")
if [ "$NODE_MAJOR" -lt 20 ]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y -qq nodejs
fi

echo "==> Creating app user"
id -u "$APP_USER" &>/dev/null || useradd -r -m -s /bin/bash "$APP_USER"

echo "==> Deploying code"
mkdir -p "$APP_DIR"
rsync -a --delete "$SRC_DIR/" "$APP_DIR/" --exclude=deploy

echo "==> Setting up PostgreSQL"
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='$APP_USER'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE USER $APP_USER WITH PASSWORD '$APP_USER';"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='$APP_USER'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE DATABASE $APP_USER OWNER $APP_USER;"

echo "==> Running database migrations"
sudo -u postgres psql -d onlybots -f "$SRC_DIR/deploy/schema.sql"
sudo -u postgres psql -d onlybots -c "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO $APP_USER;"
sudo -u postgres psql -d onlybots -c "GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO $APP_USER;"

echo "==> Setting up Python verifier"
python3 -m venv "$APP_DIR/verifier/venv"
"$APP_DIR/verifier/venv/bin/pip" install -r "$APP_DIR/verifier/requirements.txt" 2>/dev/null || true
"$APP_DIR/verifier/venv/bin/playwright" install chromium --with-deps 2>/dev/null || true

echo "==> Creating .env"
if [ ! -f "$APP_DIR/.env" ]; then
  ADMIN_KEY=$(openssl rand -hex 24)
  cat > "$APP_DIR/.env" << EOF
DATABASE_URL=postgresql://onlybots:onlybots@localhost:5432/onlybots
ADMIN_API_KEY=$ADMIN_KEY
NODE_ENV=production
PORT=3000
EOF
  chmod 600 "$APP_DIR/.env"
  echo "==> Admin API key: $ADMIN_KEY (save this!)"
fi

echo "==> Creating evidence directory"
mkdir -p "$EVIDENCE_DIR"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "==> Installing systemd services"
cp "$SRC_DIR/deploy/onlybots-web.service" /etc/systemd/system/
cp "$SRC_DIR/deploy/onlybots-verifier.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable onlybots-web
systemctl enable onlybots-verifier

echo "==> Configuring nginx"
EXTERNAL_IP=$(curl -s http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip -H "Metadata-Flavor: Google" 2>/dev/null || echo "34.28.191.224")
SSLIP_HOST=$(echo "$EXTERNAL_IP" | tr '.' '-').sslip.io
sed "s/__SSLIP_HOST__/$SSLIP_HOST/g" "$SRC_DIR/deploy/nginx.conf" > /etc/nginx/sites-available/onlybots
ln -sf /etc/nginx/sites-available/onlybots /etc/nginx/sites-enabled/onlybots
rm -f /etc/nginx/sites-enabled/default

echo "==> Starting services"
systemctl restart postgresql
systemctl restart onlybots-web
systemctl restart nginx

# Try to get SSL cert (may fail on first run)
certbot --nginx -d "$SSLIP_HOST" --non-interactive --agree-tos -m admin@onlybots.com 2>/dev/null || echo "==> SSL setup deferred (run certbot manually later)"

echo "==> Done! Site should be at: http://$SSLIP_HOST"
