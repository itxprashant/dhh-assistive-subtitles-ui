#!/usr/bin/env bash
# Deploy from your workstation to the Azure VM.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEY="${DHH_DEPLOY_KEY:-$ROOT/myvm_key.pem}"
HOST="${DHH_DEPLOY_HOST:-azureuser@20.244.42.13}"
REMOTE_DIR=/opt/dhh-assistive-device

if [[ ! -f "$KEY" ]]; then
  echo "Missing SSH key: $KEY" >&2
  exit 1
fi
chmod 600 "$KEY"

echo "==> Syncing project to $HOST:$REMOTE_DIR ..."
ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "$HOST" "sudo mkdir -p $REMOTE_DIR && sudo chown azureuser:azureuser $REMOTE_DIR"

rsync -avz --delete \
  -e "ssh -i $KEY -o StrictHostKeyChecking=accept-new" \
  --exclude '.venv/' \
  --exclude 'venv/' \
  --exclude '__pycache__/' \
  --exclude '.git/' \
  --exclude 'models/' \
  --exclude '.cache/' \
  --exclude 'hf_cache/' \
  --exclude '*.pem' \
  --exclude '.env' \
  "$ROOT/" "$HOST:$REMOTE_DIR/"

echo "==> Remote setup..."
ssh -i "$KEY" "$HOST" "bash $REMOTE_DIR/deploy/remote-setup.sh"

echo ""
echo "Deploy finished. When DNS A record for dhh-ui.itxprashant.app points here, HTTPS:"
echo "  ssh -i $KEY $HOST 'sudo certbot --nginx -d dhh-ui.itxprashant.app'"
