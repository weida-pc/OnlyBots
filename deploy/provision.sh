#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="onlybots-388132"
INSTANCE_NAME="onlybots-vm"
ZONE="us-central1-a"
ARCHIVE="/tmp/onlybots-deploy.tgz"

if [ ! -f "$ARCHIVE" ]; then
  echo "ERROR: Archive not found at $ARCHIVE. Run deploy/build_deploy_bundle.sh first."
  exit 1
fi

echo "==> Uploading archive to VM"
gcloud compute scp "$ARCHIVE" "$INSTANCE_NAME:/tmp/onlybots-deploy.tgz" \
  --zone="$ZONE" --project="$PROJECT_ID"

echo "==> Extracting and running setup on VM"
gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" --project="$PROJECT_ID" --command="
  sudo rm -rf /tmp/onlybots-src
  sudo mkdir -p /tmp/onlybots-src
  sudo tar -xzf /tmp/onlybots-deploy.tgz -C /tmp/onlybots-src
  sudo bash /tmp/onlybots-src/deploy/setup.sh /tmp/onlybots-src
  sudo rm -f /tmp/onlybots-deploy.tgz
"

echo "==> Deployment complete!"
EXTERNAL_IP=$(gcloud compute instances describe "$INSTANCE_NAME" \
  --zone="$ZONE" --project="$PROJECT_ID" \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)')
SSLIP_HOST=$(echo "$EXTERNAL_IP" | tr '.' '-').sslip.io
echo "==> Site: http://$SSLIP_HOST"
