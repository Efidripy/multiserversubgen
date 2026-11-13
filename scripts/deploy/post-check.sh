#!/usr/bin/env bash
set -euo pipefail
project="${PROJECT_NAME:-sub-manager}"
dir="${PROJECT_DIR:-/opt/${project}}"
fail() { printf '%s\n' "post-check: $1" >&2; exit 1; }
systemctl is-active --quiet "$project" || fail 'service is not active'
start="$(systemctl show "$project" -p ActiveEnterTimestamp --value)" || fail 'cannot read service start time'
[[ -n "$start" && "$start" != n/a ]] || fail 'service start time is unavailable'
# Count only; log content may contain sensitive data.
logs="$(journalctl -u "$project" --since "$start" --no-pager -q -o cat 2>/dev/null)" || fail 'cannot read journal'
count="$(printf '%s\n' "$logs" | awk '/ERROR|Traceback/ {n++} END {print n+0}')"
printf 'service: active\nERROR/Traceback lines since start: %s\n' "$count"
version="$(cat "$dir/.deploy-source-commit")" || fail 'code version is unavailable'
[[ "$version" =~ ^[0-9a-f]{40,64}$ ]] || fail 'invalid code version'
printf 'code version: %s\n' "$version"
[[ -f "$dir/admin.db" ]] || fail 'database is missing'
free="$(df -Pk "$dir" | awk 'NR==2 {print $4}')"
[[ "$free" =~ ^[0-9]+$ ]] || fail 'cannot read free space'
printf 'free space KiB: %s\ndatabase bytes: %s\n' "$free" "$(stat -c %s "$dir/admin.db")"
if [[ -e "$dir/admin.db-wal" ]]; then
  printf 'WAL bytes: %s\n' "$(stat -c %s "$dir/admin.db-wal")"
else
  printf 'WAL bytes: 0\n'
fi
(( free >= 3145728 )) || fail 'free space is below 3 GiB'
(( count == 0 )) || fail 'errors found since service start'
