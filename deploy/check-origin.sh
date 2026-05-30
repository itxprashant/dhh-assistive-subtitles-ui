#!/usr/bin/env bash
# Quick checks before certbot (run locally or on VM).
set -euo pipefail
DOMAIN=dhh-ui.itxprashant.app
ORIGIN=20.244.42.13

echo "DNS A (should be $ORIGIN if DNS-only, or Cloudflare IPs if proxied):"
dig +short "$DOMAIN" A

echo ""
echo "Origin port 80 (must succeed for certbot + Cloudflare proxy):"
if nc -z -w 5 "$ORIGIN" 80 2>/dev/null; then
  echo "  OK: $ORIGIN:80 reachable"
else
  echo "  FAIL: $ORIGIN:80 not reachable — open TCP 80 (and 443) in Azure NSG"
fi

echo ""
echo "HTTP via domain:"
curl -sI --connect-timeout 10 "http://$DOMAIN/" | head -5 || true
