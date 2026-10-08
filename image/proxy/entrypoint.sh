#!/bin/sh
# Generates a deny-by-default tinyproxy config from ALLOW_HOSTS (space/comma separated hostnames).
# api.anthropic.com is always allowed. With CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 set in the
# agent container, Claude Code needs no other hosts (statsig, sentry, updater, ...).
# Reachable only from the --internal network, hence "Allow 0.0.0.0/0".
set -eu

CONF_DIR=/etc/tinyproxy
mkdir -p "$CONF_DIR"
FILTER="$CONF_DIR/filter"
: > "$FILTER"

HOSTS="api.anthropic.com $(printf '%s' "${ALLOW_HOSTS:-}" | tr ',' ' ')"
for h in $HOSTS; do
  # escape regex dots; allow exact host and any subdomain
  esc=$(printf '%s' "$h" | tr 'A-Z' 'a-z' | sed 's/\./\\./g')
  printf '(^|\\.)%s$\n' "$esc" >> "$FILTER"
done

cat > "$CONF_DIR/tinyproxy.conf" <<EOF
Port 3128
Listen 0.0.0.0
Timeout 600
MaxClients 100
LogLevel Connect
FilterDefaultDeny Yes
FilterExtended On
FilterURLs Off
Filter "$FILTER"
ConnectPort 443
Allow 0.0.0.0/0
EOF

echo "tinyproxy allowlist:" >&2
cat "$FILTER" >&2
exec tinyproxy -d -c "$CONF_DIR/tinyproxy.conf"
