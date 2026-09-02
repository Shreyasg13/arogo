#!/usr/bin/env bash
# GCE startup script — runs once on first boot, root. Templated by Terraform
# (see main.tf's templatefile() call) from this file. Reuses provision.sh as
# the single source of truth for package/user/venv setup, then wires up the
# app-specific config that only Terraform knows (secrets, domain).
set -euo pipefail

REPO_URL="${repo_url}"
DOMAIN="${domain}"
SECRET_KEY="${secret_key}"
DATABASE_URL="${database_url}"

apt-get update -y
apt-get install -y git

BOOTSTRAP_DIR=/tmp/arogo-bootstrap
rm -rf "$BOOTSTRAP_DIR"
git clone "$REPO_URL" "$BOOTSTRAP_DIR"

AROGO_REPO_URL="$REPO_URL" bash "$BOOTSTRAP_DIR/deploy/gcp/provision.sh"

APP_DIR=/home/arogo/arogo

cat > "$APP_DIR/arogo.env" <<ENV
SECRET_KEY=$SECRET_KEY
FLASK_DEBUG=0
COOKIE_SECURE=1
CSP_ENABLED=1
APP_BASE_URL=https://$DOMAIN
DATABASE_URL=$DATABASE_URL
ENV
chown arogo:arogo "$APP_DIR/arogo.env"
chmod 600 "$APP_DIR/arogo.env"

cp "$APP_DIR/deploy/gcp/arogo-web.service" "$APP_DIR/deploy/gcp/arogo-scheduler.service" /etc/systemd/system/
sed "s/arogo.yourdomain.com/$DOMAIN/" "$APP_DIR/deploy/gcp/Caddyfile" > /etc/caddy/Caddyfile

systemctl daemon-reload
systemctl enable --now arogo-web arogo-scheduler caddy

echo "arogo startup script: done. Point DNS at this instance's static IP if you haven't already."
