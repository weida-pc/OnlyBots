#!/usr/bin/env bash
# Push the Next.js frontend to the VM and restart onlybots-web.
#
# Companion to push-verifier.sh. Handles the TypeScript/Node side:
#   - `npm run build` produces .next/standalone + .next/static
#   - bundle those + public/ + the top-level package.json
#   - scp to VM, rsync into /opt/onlybots preserving .env
#   - restart onlybots-web systemd unit
#
# Usage:
#   ./deploy/push-web.sh [--skip-build]

set -euo pipefail

VM_USER="t"
VM_HOST="34.28.191.224"
SSH_KEY="$HOME/.ssh/google_compute_engine"
REMOTE_TMP="/tmp/onlybots-web-push"
REMOTE_DST="/opt/onlybots"

SKIP_BUILD=0
for arg in "$@"; do
  case "$arg" in
    --skip-build) SKIP_BUILD=1 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if [ "$SKIP_BUILD" -eq 0 ]; then
  echo "==> Building Next.js standalone output"
  npm run build
fi

if [ ! -d .next/standalone ]; then
  echo "ERROR: .next/standalone not found. Ensure next.config has output:'standalone'." >&2
  exit 1
fi

echo "==> Staging bundle"
STAGING=$(mktemp -d)
# Standalone server is the root; next expects .next/static + public alongside it
cp -r .next/standalone/. "$STAGING/"
mkdir -p "$STAGING/.next"
cp -r .next/static "$STAGING/.next/static"
if [ -d public ]; then cp -r public "$STAGING/public"; fi

tar -czf /tmp/onlybots-web.tgz -C "$STAGING" .
rm -rf "$STAGING"

echo "==> Copying to VM"
scp -i "$SSH_KEY" /tmp/onlybots-web.tgz "$VM_USER@$VM_HOST:/tmp/onlybots-web.tgz"

echo "==> Extracting + rsync (preserving .env + evidence + verifier)"
ssh -i "$SSH_KEY" "$VM_USER@$VM_HOST" "
  sudo rm -rf $REMOTE_TMP
  sudo mkdir -p $REMOTE_TMP
  sudo tar -xzf /tmp/onlybots-web.tgz -C $REMOTE_TMP
  sudo rsync -a \
    --exclude='.env' \
    --exclude='evidence' \
    --exclude='verifier' \
    $REMOTE_TMP/ $REMOTE_DST/
  sudo chown -R onlybots:onlybots $REMOTE_DST
  sudo rm -rf $REMOTE_TMP /tmp/onlybots-web.tgz
  sudo systemctl restart onlybots-web
  sleep 2
  sudo systemctl is-active onlybots-web
"

echo "==> Done"
