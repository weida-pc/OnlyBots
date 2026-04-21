#!/bin/bash
# Scan t1_signup evidence logs to categorize per-run agent_task outcome.
# Run on the VM as root (sudo) since /opt/onlybots/evidence is chown'd onlybots.
#
# Output columns: run=ID agent=<status> probe=<probe http stat> art=<artifact>

set -u

for d in /opt/onlybots/evidence/*/; do
  log="${d}t1_signup_http_raw.log"
  [ -f "$log" ] || continue
  rid=$(basename "$d")
  # Only look at runs from this batch (138+)
  case "$rid" in
    1[3-9][0-9]|18[0-9]) ;;
    *) continue ;;
  esac

  status=$(grep -oE '"status": "[a-z_]+"' "$log" | head -1 | sed 's/.*"status": "//' | tr -d '"')
  art=$(grep -oE '"[a-z_]+_api_key": "[A-Za-z0-9_:.-]+' "$log" | head -1)
  probe=$(grep -oE 'HTTP [0-9]+ \([0-9]+ms\)' "$log" | sed -n '2p')
  echo "run=$rid agent=$status probe=$probe art=$art"
done
