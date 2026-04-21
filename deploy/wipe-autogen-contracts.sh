#!/usr/bin/env bash
# Wipe auto-generated contracts that predate the probe_url convention so the
# verifier daemon regenerates them on the next run. Hand-written contracts
# (the original corpus + manually-corrected ones) are listed in KEEP and
# stay untouched.
#
# Run on the VM as root. Lists what it deleted to stdout.

set -eu
CONTRACTS_DIR="${CONTRACTS_DIR:-/opt/onlybots/verifier/contracts}"

KEEP=(
  agentmail-to agentmail-echo browser-use clawtasks coinos here-now
  httpbin humblytics memoryvault moltbook moltmail nevermined
  placeholdermcp signbee skyfire twilio-echo actors
  e2b-the-enterprise-ai-agent-cloud fetch-ai
)

is_keep() {
  local s="$1"
  for k in "${KEEP[@]}"; do
    [ "$s" = "$k" ] && return 0
  done
  return 1
}

cd "$CONTRACTS_DIR"
for f in *.json; do
  slug="${f%.json}"
  if is_keep "$slug"; then
    continue
  fi
  # Heuristic: keep contracts that already use <slug>_probe_url in their
  # signup produces (i.e. already conform to the new generator prompt).
  probe_key="${slug//-/_}_probe_url"
  if grep -q "\"$probe_key\"" "$f" 2>/dev/null; then
    continue
  fi
  echo "RM $f"
  rm -f "$f"
done
