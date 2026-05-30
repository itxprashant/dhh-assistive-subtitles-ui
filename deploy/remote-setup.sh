#!/usr/bin/env bash
# Run on the VM as azureuser (uses sudo for system packages).
set -euo pipefail

APP_DIR=/opt/dhh-assistive-device
DOMAIN=dhh-ui.itxprashant.app

echo "==> Installing system packages..."
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  python3-venv python3-pip nginx certbot python3-certbot-nginx \
  build-essential ffmpeg

echo "==> Python virtualenv and dependencies..."
cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip wheel
.venv/bin/pip install -r requirements.txt

echo "==> systemd unit..."
sudo cp deploy/dhh-ui.service /etc/systemd/system/dhh-ui.service
sudo systemctl daemon-reload
sudo systemctl enable dhh-ui
sudo systemctl restart dhh-ui

echo "==> nginx site..."
sudo cp deploy/nginx-dhh-ui.conf /etc/nginx/sites-available/dhh-ui
sudo ln -sf /etc/nginx/sites-available/dhh-ui /etc/nginx/sites-enabled/dhh-ui
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx

echo "==> App status..."
sleep 2
sudo systemctl --no-pager status dhh-ui || true
curl -sf -o /dev/null http://127.0.0.1:8501/_stcore/health && echo "Streamlit health: OK" || echo "Streamlit health: waiting..."

if getent hosts "$DOMAIN" | grep -q .; then
  echo "==> DNS resolves; requesting Let's Encrypt certificate..."
  sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
    --register-unsafely-without-email --redirect || {
    echo "certbot failed; run manually after DNS points to this VM:"
    echo "  sudo certbot --nginx -d $DOMAIN"
  }
else
  echo "==> Skipping certbot: $DOMAIN does not resolve yet."
  echo "After adding an A record to this server's public IP, run:"
  echo "  sudo certbot --nginx -d $DOMAIN"
fi

echo "==> Done."
