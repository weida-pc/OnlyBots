#!/usr/bin/env bash
# Batch-submit URLs to the OnlyBots registry via /api/admin/quick-submit.
#
# Reads URLs from stdin (one per line, blank lines and # comments ignored)
# and posts each as a URL-only submission. The server fills in the rest
# from the landing page and queues a verification run.
#
# Usage:
#   export ONLYBOTS_ADMIN_KEY=$(ssh ... 'sudo grep ^ADMIN_API_KEY /opt/onlybots/.env | cut -d= -f2')
#   cat urls.txt | ./deploy/batch-submit.sh
#   # or inline:
#   ./deploy/batch-submit.sh <<'URLS'
#   https://fetch.ai
#   https://zeroid.io
#   URLS
#
# Each submission is throttled to 2s to stay well under any rate limits
# and give the daemon breathing room. The verifier processes runs
# serially anyway, so firing them off in a burst wouldn't help.

set -euo pipefail

BASE="${ONLYBOTS_BASE:-http://34-28-191-224.sslip.io}"
KEY="${ONLYBOTS_ADMIN_KEY:?set ONLYBOTS_ADMIN_KEY env}"

submitted=0
dupes=0
errors=0

while IFS= read -r url; do
  # Strip comments and blank lines
  url="${url%%#*}"
  url="$(echo "$url" | tr -d '[:space:]')"
  [ -z "$url" ] && continue

  resp=$(curl -sS -w "\n%{http_code}" \
    -X POST "$BASE/api/admin/quick-submit" \
    -H "Content-Type: application/json" \
    -H "X-Admin-Key: $KEY" \
    -d "{\"url\":\"$url\"}" 2>&1 || echo "CURL_FAIL")

  code=$(echo "$resp" | tail -n1)
  body=$(echo "$resp" | sed '$d')

  case "$code" in
    201)
      slug=$(echo "$body" | python -c "import sys,json; print(json.load(sys.stdin).get('service',{}).get('slug','?'))" 2>/dev/null || echo "?")
      echo "OK   $url -> $slug"
      submitted=$((submitted+1))
      ;;
    409)
      echo "DUPE $url (already submitted)"
      dupes=$((dupes+1))
      ;;
    *)
      echo "ERR  $url -> HTTP $code: $(echo "$body" | head -c 200)"
      errors=$((errors+1))
      ;;
  esac

  sleep 2
done

echo "---"
echo "submitted: $submitted    duplicates: $dupes    errors: $errors"
