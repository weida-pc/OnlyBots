#!/usr/bin/env bash
# Push verifier changes to the VM and restart the daemon.
#
# Symptom this prevents: deploy files without restart → daemon runs stale
# code while new code sits on disk. This actually happened mid-session and
# caused a failed verification run; by the time we realized, we'd been
# running old code for hours.
#
# Usage:
#   ./deploy/push-verifier.sh [--no-restart]
#
# Copies verifier/*.py + verifier/contract/ + verifier/contracts/ +
# verifier/agent/ to the VM, chowns to onlybots:onlybots, and restarts
# the systemd service unless --no-restart is passed.

set -euo pipefail

VM_USER="t"
VM_HOST="34.28.191.224"
SSH_KEY="$HOME/.ssh/google_compute_engine"
REMOTE_TMP="/tmp/onlybots-verifier-push"
REMOTE_DST="/opt/onlybots/verifier"

SKIP_RESTART=0
for arg in "$@"; do
  case "$arg" in
    --no-restart) SKIP_RESTART=1 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT/verifier"

echo "==> Packaging verifier (excluding venv, __pycache__, .env)"
tar -czf /tmp/onlybots-verifier.tgz \
  --exclude='venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.env' \
  --exclude='evidence' \
  .

echo "==> Copying to VM"
scp -i "$SSH_KEY" /tmp/onlybots-verifier.tgz "$VM_USER@$VM_HOST:/tmp/onlybots-verifier.tgz"

echo "==> Extracting + chowning"
ssh -i "$SSH_KEY" "$VM_USER@$VM_HOST" "
  sudo rm -rf $REMOTE_TMP
  sudo mkdir -p $REMOTE_TMP
  sudo tar -xzf /tmp/onlybots-verifier.tgz -C $REMOTE_TMP
  # Rsync but PRESERVE .env files and evidence directory
  sudo rsync -a --exclude='.env' --exclude='evidence' $REMOTE_TMP/ $REMOTE_DST/
  sudo chown -R onlybots:onlybots $REMOTE_DST
  sudo rm -rf $REMOTE_TMP /tmp/onlybots-verifier.tgz
"

if [ "$SKIP_RESTART" -eq 1 ]; then
  echo "==> Skipping daemon restart (--no-restart)"
else
  echo "==> Restarting verifier daemon"
  ssh -i "$SSH_KEY" "$VM_USER@$VM_HOST" "
    sudo systemctl restart onlybots-verifier
    sleep 2
    sudo systemctl is-active onlybots-verifier
  "
fi

echo "==> Done"
