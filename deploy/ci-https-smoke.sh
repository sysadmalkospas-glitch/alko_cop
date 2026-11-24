#!/usr/bin/env bash
set -euo pipefail

# Dedicated, disposable CI stack (never a production database).
: "${RUNNER_TEMP:?CI temporary directory required}"
: "${SCREENSHOT_PATH:?CI screenshot directory required}"
: "${ALKOCOP_CERTS_DIR:?CI certificate directory required}"
: "${ALKOCOP_HOST:?CI hostname required}"
: "${ALKOCOP_HTTPS_PORT:?CI HTTPS port required}"

compose=(docker compose -p alkocop-migration-ci)
base_url="https://${ALKOCOP_HOST}:${ALKOCOP_HTTPS_PORT}"
root_ca="$RUNNER_TEMP/alkocop-ci-root.crt"
cookie_jar="$RUNNER_TEMP/alkocop-ci-cookies"
headers_file="$RUNNER_TEMP/alkocop-ci-headers"
cabinet_html="$RUNNER_TEMP/alkocop-ci-cabinet.html"

check_no_h3() {
    if grep -qi '^alt-svc:.*h3' "$headers_file"; then
        echo "Unexpected HTTP/3 advertisement" >&2
        exit 1
    fi
}

check_cabinet() {
    local asset
    local -a assets
    curl --silent --show-error --fail --cacert "$1" "$base_url/" > "$cabinet_html"
    grep -q '<div id="root"></div>' "$cabinet_html"
    curl --silent --show-error --fail --cacert "$1" "$base_url/reports/day-structure?period=week" |
        cmp -s "$cabinet_html" -
    mapfile -t assets < <(grep -oE '/assets/[^"]+\.(js|css)' "$cabinet_html")
    test "${#assets[@]}" -ge 2
    for asset in "${assets[@]}"; do
        curl --silent --show-error --fail --cacert "$1" "$base_url$asset" > /dev/null
    done
    test "$(curl --silent --show-error --cacert "$1" --output /dev/null --write-out '%{http_code}' "$base_url/assets/missing.js")" = 404
    test "$(curl --silent --show-error --cacert "$1" --output /dev/null --write-out '%{http_code}' "$base_url/api/missing")" = 404
    echo "Verified cabinet, report deep link, static assets and API routing"
}

install -d -m 0777 "$SCREENSHOT_PATH"
install -d -m 0700 "$ALKOCOP_CERTS_DIR"
"${compose[@]}" up -d --build

# The CA is created on the first Caddy startup.
for attempt in $(seq 1 30); do
    if "${compose[@]}" exec -T caddy test -s /data/caddy/pki/authorities/local/root.crt; then
        break
    fi
    sleep 2
done
"${compose[@]}" cp caddy:/data/caddy/pki/authorities/local/root.crt "$root_ca"

curl_tls=(curl --silent --show-error --fail --cacert "$root_ca")
"${curl_tls[@]}" --retry 30 --retry-all-errors --retry-delay 2 --max-time 5 --dump-header "$headers_file" "$base_url/health"
check_no_h3
echo
check_cabinet "$root_ca"

# Only the Caddy container may publish a host port.
for service in server db; do
    docker inspect --format '{{json .NetworkSettings.Ports}}' "$("${compose[@]}" ps -q "$service")" |
        python -c 'import json, sys; assert not any((json.load(sys.stdin) or {}).values())'
done
echo "Verified server and database have no published ports"

"${compose[@]}" logs --no-color server | grep -E 'Running upgrade .*0001'
"${compose[@]}" exec -T server alembic check
"${compose[@]}" exec -T server python -c "from app.cli import create_first_admin; from app.config import get_settings; assert create_first_admin('ci-admin', 'ci-password-only', get_settings())"

# A same-origin browser request must succeed without disabling Secure cookies.
"${curl_tls[@]}" --cookie-jar "$cookie_jar" \
    -H 'Content-Type: application/json' -H "Origin: $base_url" \
    --data '{"login":"ci-admin","password":"ci-password-only"}' "$base_url/api/v1/auth/login" > /dev/null
awk '$6 == "alkocop_session" && $4 == "TRUE" { found=1 } END { exit !found }' "$cookie_jar"
"${curl_tls[@]}" --cookie "$cookie_jar" "$base_url/api/v1/auth/me" > /dev/null

# Exercise PostgreSQL observation upserts and the historical backfill over real agent data.
enroll_payload="$(python -c 'import json, os; print(json.dumps({"enroll_key": os.environ["ALKOCOP_ENROLL_KEY"], "machine_id": "ci-machine", "hostname": "CI-PC"}))')"
agent_token="$("${curl_tls[@]}" -H 'Content-Type: application/json' --data "$enroll_payload" \
    "$base_url/api/agent/v1/enroll" | python -c 'import json, sys; print(json.load(sys.stdin)["token"])')"
"${curl_tls[@]}" -H "Authorization: Bearer $agent_token" -H 'Content-Type: application/json' \
    --data '{"events":[{"id":"ci-first","login":"CI\\Observer","occurred_at":"2026-11-20T09:00:00Z","kind":"logon"}]}' \
    "$base_url/api/agent/v1/activity" > /dev/null
"${compose[@]}" exec -T server alembic downgrade 0003
"${compose[@]}" exec -T server alembic upgrade head
"${curl_tls[@]}" -H "Authorization: Bearer $agent_token" -H 'Content-Type: application/json' \
    --data '{"events":[{"id":"ci-last","login":"ci\\observer","occurred_at":"2026-11-20T10:00:00Z","kind":"logoff"}]}' \
    "$base_url/api/agent/v1/activity" > /dev/null
"${curl_tls[@]}" --cookie "$cookie_jar" "$base_url/api/v1/logins/unknown" |
    python -c 'import json, sys; row, = json.load(sys.stdin)["items"]; assert row["login"].casefold() == "ci\\observer"; assert row["first_seen_at"] == "2026-11-20T09:00:00Z"; assert row["last_seen_at"] == "2026-11-20T10:00:00Z"; assert row["last_computer_id"] is not None'
echo "Verified PostgreSQL observed login migration and case-insensitive updates"

# The throttle must use the client address supplied by the trusted proxy, not
# the proxy container's address shared by all clients.
"${compose[@]}" exec -T server python -c "import os; from sqlalchemy import create_engine, select; from sqlalchemy.orm import Session; from app.config import get_settings; from app.models import LoginThrottle; from app.security import hash_token; db = Session(create_engine(get_settings().database_url)); keys = list(db.scalars(select(LoginThrottle.key).where(LoginThrottle.key.like('ip:%')))); assert len(keys) == 1 and 'ip:' + hash_token(os.environ['FORWARDED_ALLOW_IPS']) not in keys; db.close()"
"${curl_tls[@]}" --cookie "$cookie_jar" -H "Origin: $base_url" -X POST "$base_url/api/v1/auth/logout" > /dev/null
test "$(curl --silent --show-error --cacert "$root_ca" --output /dev/null --write-out '%{http_code}' --cookie "$cookie_jar" "$base_url/api/v1/auth/me")" = 401
echo "Verified HTTPS login, Secure cookie, client IP and logout revocation"

# The alternate mode uses a dedicated test CA and a certificate from files.
custom_ca="$RUNNER_TEMP/alkocop-custom-ca.crt"
custom_key="$RUNNER_TEMP/alkocop-custom-ca.key"
custom_csr="$RUNNER_TEMP/alkocop-custom.csr"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -sha256 \
    -keyout "$custom_key" -out "$custom_ca" -subj '/CN=AlkoCop CI CA'
openssl req -new -newkey rsa:2048 -nodes -keyout "$ALKOCOP_CERTS_DIR/tls.key" \
    -out "$custom_csr" -subj "/CN=$ALKOCOP_HOST" -addext "subjectAltName=DNS:$ALKOCOP_HOST"
openssl x509 -req -in "$custom_csr" -CA "$custom_ca" -CAkey "$custom_key" -CAcreateserial \
    -out "$ALKOCOP_CERTS_DIR/tls.crt" -days 1 -sha256 -copy_extensions copy
ALKOCOP_TLS_MODE=custom "${compose[@]}" up -d --no-deps --force-recreate caddy
curl --silent --show-error --fail --cacert "$custom_ca" --retry 30 --retry-all-errors \
    --retry-delay 2 --max-time 5 --dump-header "$headers_file" "$base_url/health"
check_no_h3
echo
check_cabinet "$custom_ca"
echo "Verified custom TLS certificate and no HTTP/3 advertisement"
