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
USE_HTTPS="${use_https}"

apt-get update -y
apt-get install -y git

BOOTSTRAP_DIR=/tmp/arogo-bootstrap
rm -rf "$BOOTSTRAP_DIR"
git clone "$REPO_URL" "$BOOTSTRAP_DIR"

AROGO_REPO_URL="$REPO_URL" bash "$BOOTSTRAP_DIR/deploy/gcp/provision.sh"

APP_DIR=/home/arogo/arogo

# use_https=false is for a temporary bare-IP test before a domain exists —
# forces plain HTTP so COOKIE_SECURE (which needs real TLS) doesn't lock you
# out, and gives Caddy an explicit http:// address instead of relying on its
# IP-address auto-detection.
if [ "$USE_HTTPS" = "true" ]; then
  SCHEME=https
  COOKIE_SECURE_VAL=1
  CADDY_ADDR="$DOMAIN"
else
  SCHEME=http
  COOKIE_SECURE_VAL=0
  CADDY_ADDR="http://$DOMAIN"
fi

cat > "$APP_DIR/arogo.env" <<ENV
SECRET_KEY=$SECRET_KEY
FLASK_DEBUG=0
COOKIE_SECURE=$COOKIE_SECURE_VAL
CSP_ENABLED=1
APP_BASE_URL=$SCHEME://$DOMAIN
DATABASE_URL=$DATABASE_URL
ENV
chown arogo:arogo "$APP_DIR/arogo.env"
chmod 600 "$APP_DIR/arogo.env"

cp "$APP_DIR/deploy/gcp/arogo-web.service" "$APP_DIR/deploy/gcp/arogo-scheduler.service" /etc/systemd/system/
sed "s#arogo.yourdomain.com#$CADDY_ADDR#" "$APP_DIR/deploy/gcp/Caddyfile" > /etc/caddy/Caddyfile

systemctl daemon-reload
systemctl enable --now arogo-web arogo-scheduler
# Debian's caddy package auto-starts on install with its own stock config
# (a static file server) — enable --now is a no-op if it's already running,
# so it would silently never pick up the Caddyfile written above. restart
# forces it to reload regardless of prior state.
systemctl enable caddy
systemctl restart caddy

echo "arogo startup script: done. Point DNS at this instance's static IP if you haven't already."
