#!/usr/bin/env bash
# One-time provisioning for Arogo on a GCP e2-micro VM (Debian).
# Run once via SSH after the VM exists. See ../../DEPLOY.md for the gcloud
# commands that create the VM itself — this script only sets up what runs
# on top of it. Safe to re-run (each step is a no-op if already done).
set -euo pipefail

REPO_URL="${AROGO_REPO_URL:?Set AROGO_REPO_URL to your repo clone URL, e.g. https://github.com/you/arogo.git}"
APP_USER="${AROGO_USER:-arogo}"
APP_DIR="/home/$APP_USER/arogo"

echo "== Installing system packages =="
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip git curl gnupg debian-keyring debian-archive-keyring apt-transport-https

echo "== Installing Caddy (official apt repo) =="
if ! command -v caddy >/dev/null 2>&1; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | sudo tee /etc/apt/sources.list.d/caddy-stable.list
  sudo apt-get update -y
  sudo apt-get install -y caddy
fi

echo "== Creating dedicated user =="
if ! id "$APP_USER" >/dev/null 2>&1; then
  sudo useradd --create-home --shell /usr/sbin/nologin "$APP_USER"
fi

echo "== Cloning / updating the app =="
if [ -d "$APP_DIR/.git" ]; then
  sudo -u "$APP_USER" git -C "$APP_DIR" pull
else
  sudo -u "$APP_USER" git clone "$REPO_URL" "$APP_DIR"
fi

echo "== Building the virtualenv =="
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

cat <<EOF

Provisioning done. Next steps (see DEPLOY.md):
  1. cp deploy/gcp/arogo.env.example $APP_DIR/arogo.env
     — fill in SECRET_KEY, DATABASE_URL, APP_BASE_URL, then: chmod 600 $APP_DIR/arogo.env
  2. Copy deploy/gcp/arogo-web.service and arogo-scheduler.service to /etc/systemd/system/
  3. Copy deploy/gcp/Caddyfile to /etc/caddy/Caddyfile (edit the domain), then: sudo systemctl reload caddy
  4. sudo systemctl daemon-reload && sudo systemctl enable --now arogo-web arogo-scheduler caddy
EOF
