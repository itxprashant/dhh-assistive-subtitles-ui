#!/usr/bin/env bash
# Run on the VM after DNS A record points to this host.
set -euo pipefail
DOMAIN=dhh-ui.itxprashant.app
sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
  --register-unsafely-without-email --redirect
echo "HTTPS enabled for https://$DOMAIN"
