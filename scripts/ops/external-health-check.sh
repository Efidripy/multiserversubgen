#!/usr/bin/env bash
set -euo pipefail

# Run this from an external observer (for example the Windows host or CI),
# not from the deployed VM. Local readiness and public FQDN/TLS reachability
# are separate acceptance layers.
PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-5}"
RETRY_SECONDS="${RETRY_SECONDS:-2}"

[[ -n "$PUBLIC_BASE_URL" ]] || { printf 'PUBLIC_BASE_URL is required\n' >&2; exit 2; }
[[ "$MAX_ATTEMPTS" =~ ^[1-9][0-9]*$ ]] || { printf 'MAX_ATTEMPTS must be a positive integer\n' >&2; exit 2; }
[[ "$RETRY_SECONDS" =~ ^[0-9]+$ ]] || { printf 'RETRY_SECONDS must be a non-negative integer\n' >&2; exit 2; }

if ! python3 - "$PUBLIC_BASE_URL" <<'PYTHON'
import ipaddress
import re
import sys
from urllib.parse import urlparse

value = sys.argv[1]
try:
    parsed = urlparse(value)
    hostname = parsed.hostname
    _ = parsed.port
except ValueError:
    raise SystemExit(1)

if (
    parsed.scheme != "https"
    or not hostname
    or parsed.username is not None
    or parsed.password is not None
    or parsed.query
    or parsed.fragment
):
    raise SystemExit(1)

try:
    ipaddress.ip_address(hostname)
except ValueError:
    pass
else:
    raise SystemExit(1)

labels = hostname.rstrip(".").split(".")
if (
    len(labels) < 2
    or len(hostname) > 253
    or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in labels)
):
    raise SystemExit(1)
PYTHON
then
    printf 'PUBLIC_BASE_URL must be an HTTPS FQDN without credentials, query or fragment\n' >&2
    exit 2
fi

HEALTH_URL="${PUBLIC_BASE_URL%/}/health"
for ((attempt = 1; attempt <= MAX_ATTEMPTS; attempt++)); do
    if code="$(curl --fail --silent --show-error --max-time 5 \
        --output /dev/null --write-out '%{http_code}' "$HEALTH_URL")"; then
        if [[ "$code" == "200" ]]; then
            printf 'external canonical health: ok\n'
            exit 0
        fi
    fi
    (( attempt < MAX_ATTEMPTS )) && sleep "$RETRY_SECONDS"
done

printf 'external canonical health: failed (expected HTTPS /health -> 200)\n' >&2
exit 1
