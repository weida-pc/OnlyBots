#!/usr/bin/env bash
# Fetch the <title> for every URL on a list, so we can eyeball whether
# each domain is actually the service the registry claims it is.
# Output is tab-separated: slug <TAB> url <TAB> http_code <TAB> title.
# Parked/squatter/unrelated-business pages will have titles that don't
# match the service name, making the mismatches obvious at a glance.
set -u
while IFS=$'\t' read -r slug url; do
  [ -z "$url" ] && continue
  out=$(curl -sS -L --max-time 10 -H "User-Agent: OnlyBotsBot/1.0 audit" \
    -o /tmp/audit-body -w "%{http_code}\t%{url_effective}" "$url" 2>/dev/null || echo "000	-")
  code=$(echo "$out" | awk -F'\t' '{print $1}')
  final=$(echo "$out" | awk -F'\t' '{print $2}')
  title=$(grep -oE '<title[^>]*>[^<]+' /tmp/audit-body 2>/dev/null \
    | head -1 | sed 's/<title[^>]*>//' | tr -d '\r\n' | cut -c1-80)
  printf "%s\t%s\t%s\t%s\t%s\n" "$slug" "$url" "$code" "$final" "$title"
done
