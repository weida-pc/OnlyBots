#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STAGING_DIR=$(mktemp -d)
ARCHIVE="/tmp/onlybots-deploy.tgz"

echo "==> Building Next.js app"
cd "$SOURCE_DIR"
npm run build

echo "==> Staging deployment bundle"
# Copy standalone build
cp -r .next/standalone/* "$STAGING_DIR/"
cp -r .next/standalone/.next "$STAGING_DIR/.next"
mkdir -p "$STAGING_DIR/.next/static"
cp -r .next/static/* "$STAGING_DIR/.next/static/" 2>/dev/null || true
cp -r public "$STAGING_DIR/public" 2>/dev/null || true

# Copy verifier
cp -r verifier "$STAGING_DIR/verifier" 2>/dev/null || true

# Copy deploy scripts
cp -r deploy "$STAGING_DIR/deploy"

# Copy env example
cp .env.example "$STAGING_DIR/.env.example"

echo "==> Creating archive"
tar -czf "$ARCHIVE" -C "$STAGING_DIR" .
rm -rf "$STAGING_DIR"

echo "==> Bundle ready: $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"
