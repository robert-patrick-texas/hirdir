#!/bin/bash
# Install the package in a clean Ubuntu 26.04 container that runs systemd, and exercise
# it through nginx over HTTPS under a URL prefix. "make package-test" runs this, and
# "make e2e" runs it with --e2e. It needs docker, curl, python3 and make on the host.
#
# Usage: packaging/package-test.sh [--e2e]
#   --e2e          after the checks under /hirdir/, run the browser scenarios of web/
#                  against the container (npm --prefix web run e2e). The browser runs
#                  in Playwright's container image unless E2E_HOST_BROWSER=1 asks for
#                  the host's, or PW_TEST_CONNECT_WS_ENDPOINT already names one.
# Environment:
#   DEB            the package to test (default: dist/hirdir_<version>_amd64.deb)
#   PREVIOUS_DEB   an older package: it is installed first and upgraded to DEB
#
# Every check prints a line that starts with PASS, FAIL or SKIP. A failed check is
# counted and the run goes on, so that one run reports every problem. The exit status
# is 0 only when no check failed. The container and its image are always removed.
#
# A check that belongs to scenario S01 or S02 of docs/build-plan.md carries its number.
# The others, marked pkg, are about the package alone.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

e2e=0
for argument in "$@"; do
    case $argument in
        --e2e) e2e=1 ;;
        *)
            echo "usage: packaging/package-test.sh [--e2e]" >&2
            exit 2
            ;;
    esac
done

version=$(make -s version)
deb=${DEB:-dist/hirdir_${version}_amd64.deb}
previous=${PREVIOUS_DEB:-}
for file in "$deb" ${previous:+"$previous"}; do
    if [ ! -f "$file" ]; then
        echo "package-test: there is no $file. Build the package first: make deb" >&2
        exit 2
    fi
done

# Names of this run alone, so that two runs at once do not collide.
run_id=$$-$RANDOM
image=hirdir-package-test:$run_id
container=hirdir-package-test-$run_id
work=$(mktemp -d)
admin=package-test-admin
failures=0
responses=0
status=""
port=""

browser=hirdir-package-test-browser-$run_id

cleanup() {
    docker rm --force "$container" >/dev/null 2>&1 || true
    docker rm --force "$browser" >/dev/null 2>&1 || true
    docker image rm --force "$image" >/dev/null 2>&1 || true
    rm -rf "$work"
}
trap cleanup EXIT

# ---- helpers --------------------------------------------------------------------------

section() { printf '\n== %s\n' "$*"; }
pass() { printf 'PASS  %s\n' "$*"; }
skip() { printf 'SKIP  %s\n' "$*"; }
fail() {
    printf 'FAIL  %s\n' "$*"
    failures=$((failures + 1))
}

# check DESCRIPTION COMMAND...: pass when the command succeeds.
check() {
    local what=$1
    shift
    if "$@" >/dev/null 2>&1; then pass "$what"; else fail "$what"; fi
}

# expect DESCRIPTION GOT WANTED: pass when the two are equal, and show GOT when not.
expect() {
    if [ "$2" = "$3" ]; then pass "$1"; else fail "$1 (got '$2', wanted '$3')"; fi
}

contains() { case $1 in *"$2"*) return 0 ;; *) return 1 ;; esac; }

# Run a command in the container, as root.
inside() { docker exec --env DEBIAN_FRONTEND=noninteractive "$container" "$@"; }

# request METHOD PATH [curl options]: one request from the host through nginx. It sets
# $status, leaves the body in $work/body, and keeps the headers of every response of
# the run in $work/headers.all for the check that none of them set a cookie.
request() {
    local method=$1 path=$2
    shift 2
    status=$(curl --silent --insecure --max-time 20 --request "$method" \
        --dump-header "$work/headers" --output "$work/body" --write-out '%{http_code}' \
        "$@" "https://127.0.0.1:$port$path") || status=000
    if [ -s "$work/headers" ]; then
        cat "$work/headers" >>"$work/headers.all"
        responses=$((responses + 1))
    fi
}

# Send a request with the session token in $token.
authorized() {
    local method=$1 path=$2
    shift 2
    request "$method" "$path" --header "Authorization: Bearer $token" "$@"
}

# json_field KEY: the value of a top-level key of the JSON in $work/body. A string is
# printed as it is, anything else as JSON.
json_field() {
    python3 -c '
import json, sys
try:
    value = json.load(open(sys.argv[1], encoding="utf-8")).get(sys.argv[2])
except (OSError, ValueError, AttributeError):
    value = None
print(value if isinstance(value, str) else json.dumps(value, sort_keys=True))' "$work/body" "$1"
}

# The value of the header named $1 in the last response.
header() { tr -d '\r' <"$work/headers" | sed -n "s/^$1: //Ip" | tail -n 1; }

# sign_in USERNAME ACCESS_CODE: ask for a session. Sets $status and, on 200, $token.
sign_in() {
    local body
    body=$(python3 -c 'import json, sys; print(json.dumps({"username": sys.argv[1], "access_code": sys.argv[2]}))' "$1" "$2")
    request POST "$prefix/api/v1/auth/sign-in" --header 'Content-Type: application/json' --data "$body"
    if [ "$status" = 200 ]; then token=$(json_field token); fi
}

# Wait until the health probe under $prefix answers 200, for at most 30 seconds.
wait_ready() {
    for _ in $(seq 30); do
        request GET "$prefix/api/v1/health/ready"
        if [ "$status" = 200 ]; then return 0; fi
        sleep 1
    done
    return 1
}

# wait_status WANTED METHOD PATH: repeat a request until it has the wanted status, for
# at most 15 seconds. nginx takes up a new configuration in the background, so the
# first request after a reload may still be answered under the old one.
wait_status() {
    local wanted=$1
    shift
    for _ in $(seq 15); do
        request "$@"
        if [ "$status" = "$wanted" ]; then return 0; fi
        sleep 1
    done
    return 1
}

# create_user NAME: create an Admin with hirdir admin. Sets $code to its access code.
create_user() {
    inside hirdir admin create-user --role admin "$1" >"$work/create-user.log" 2>&1 || true
    code=$(sed -n 's/^access code: //p' "$work/create-user.log")
}

# ---- the container --------------------------------------------------------------------

section "container"
check "S01 the package ships no byte-code from the build" \
    bash -c "! dpkg-deb -c '$deb' | grep -Eq '__pycache__|\\.pyc\$'"

docker build --quiet --tag "$image" - <packaging/container/Dockerfile.systemd >/dev/null
# systemd as init needs a privileged container with a cgroup tree of its own. HTTPS is
# published on the loopback address of the host only, on a port docker chooses.
start=(docker run --detach --name "$container" --privileged --cgroupns=private
    --tmpfs /run --tmpfs /run/lock --publish 127.0.0.1::443 "$image")
if ! "${start[@]}" >/dev/null 2>"$work/docker-run.log"; then
    echo "package-test: docker refused to start the systemd container. The command was:" >&2
    printf '   ' >&2
    printf ' %q' "${start[@]}" >&2
    printf '\n' >&2
    cat "$work/docker-run.log" >&2
    echo "package-test: systemd-nspawn is the other runner named in docs/architecture.md;" >&2
    echo "package-test: this script does not drive it. Nothing was tested." >&2
    exit 2
fi
state=starting
for _ in $(seq 60); do
    state=$(docker exec "$container" systemctl is-system-running 2>/dev/null || true)
    case $state in running | degraded) break ;; esac
    sleep 1
done
case $state in
    running | degraded) pass "systemd is the init of an ubuntu:26.04 container (state: $state)" ;;
    *)
        fail "systemd is the init of an ubuntu:26.04 container (state: $state)"
        echo "package-test: systemd did not come up, so nothing else can be tested." >&2
        exit 1
        ;;
esac
port=$(docker port "$container" 443/tcp | sed -n 's/^127\.0\.0\.1://p' | head -n 1)
[ -n "$port" ] || {
    echo "package-test: docker published no port on 127.0.0.1 for the container." >&2
    exit 1
}

# apt's sandbox user must be able to read the packages, so they are copied in.
inside mkdir -p /srv/debs
docker cp --quiet "$deb" "$container:/srv/debs/hirdir-new.deb"
if [ -n "$previous" ]; then docker cp --quiet "$previous" "$container:/srv/debs/hirdir-previous.deb"; fi
inside chmod -R a+rX /srv/debs

# The version of hirdir that dpkg has installed, or nothing.
installed_version() { inside dpkg-query -W -f "\${Version}" hirdir 2>/dev/null || true; }

apt_get() { inside apt-get -o Dpkg::Use-Pty=0 --yes "$@" >"$work/apt.log" 2>&1; }

# ---- install --------------------------------------------------------------------------

section "install"
if apt_get update && apt_get install nginx; then
    pass "S01 nginx installs with apt"
else
    fail "S01 nginx installs with apt"
    tail -n 20 "$work/apt.log"
fi

witness_code=""
if [ -n "$previous" ]; then
    if apt_get install /srv/debs/hirdir-previous.deb; then
        pass "pkg the previous package installs ($(basename "$previous"))"
    else
        fail "pkg the previous package installs ($(basename "$previous"))"
        tail -n 20 "$work/apt.log"
    fi
    previous_version=$(installed_version)
    create_user upgrade-witness
    witness_code=$code
    check "pkg an account is created with the previous version ($previous_version)" test -n "$witness_code"
else
    skip "pkg upgrade from the previous release: there is no previous release yet (PREVIOUS_DEB=path tests it)"
fi

if apt_get install /srv/debs/hirdir-new.deb; then
    pass "S01 the package installs with apt"
else
    fail "S01 the package installs with apt"
    tail -n 30 "$work/apt.log"
fi
cp "$work/apt.log" "$work/install.log"
expect "S01 the installed version is $version" "$(installed_version)" "$version"
expect "S01 the hirdir command runs and says its version" "$(inside hirdir version 2>&1)" "$version"

if [ -n "$previous" ]; then
    backup=$(sed -n 's/^hirdir: the database as it was before this upgrade is kept at //p' "$work/install.log")
    check "pkg the upgrade says where it kept a backup of the database" test -n "$backup"
    check "pkg that backup exists" inside test -s "${backup:-/nonexistent}"
    check "pkg the upgrade prints no first-install hints" \
        bash -c "! grep -q 'hirdir admin create-user' '$work/install.log'"
else
    check "S01 the install says how to create the first Admin" \
        grep -q 'sudo hirdir admin create-user --role admin NAME' "$work/install.log"
    check "S01 the install says how to add the site" grep -q 'sudo hirdir-setup' "$work/install.log"
fi
expect "S01 hirdir.service is enabled" "$(inside systemctl is-enabled hirdir.service 2>&1)" enabled
expect "S01 hirdir.service is running" "$(inside systemctl is-active hirdir.service 2>&1)" active
main_pid=$(inside systemctl show --property MainPID --value hirdir.service)
expect "S01 the service runs as user hirdir" "$(inside ps -o user= -p "$main_pid" 2>&1)" hirdir
expect "S01 /var/lib/hirdir belongs to hirdir, mode 0750" \
    "$(inside stat -c '%a %U:%G' /var/lib/hirdir 2>&1)" "750 hirdir:hirdir"
check "S01 the install compiled the byte-code, so nothing writes under /opt later" \
    inside bash -c 'test -d /opt/hirdir/venv/lib/python3.*/site-packages/hirdir/__pycache__'

# ---- hirdir-setup ---------------------------------------------------------------------

section "hirdir-setup --self-signed --prefix /hirdir"
prefix=/hirdir
if inside hirdir-setup --self-signed --prefix /hirdir --yes >"$work/setup.log" 2>&1; then
    pass "S01 hirdir-setup --self-signed --prefix /hirdir --yes succeeds"
else
    fail "S01 hirdir-setup --self-signed --prefix /hirdir --yes succeeds"
    cat "$work/setup.log"
fi
check "S01 it says plainly that the certificate is not for production" \
    grep -q 'not for production' "$work/setup.log"
tree_sum() { inside bash -c 'find /etc/nginx /etc/hirdir -type f -print0 | sort -z | xargs -0 sha256sum; ls -l /etc/nginx/sites-enabled'; }
before=$(tree_sum)
inside hirdir-setup --self-signed --prefix /hirdir --yes >"$work/setup-again.log" 2>&1 || true
check "S01 run a second time, it says there is nothing to change" \
    grep -q 'Nothing to change' "$work/setup-again.log"
expect "S01 run a second time, it changes no file" "$(tree_sum | sha256sum)" "$(printf '%s\n' "$before" | sha256sum)"
check "S01 nginx accepts its configuration" inside nginx -t

# ---- through nginx, over HTTPS, under the prefix -----------------------------------------

section "through nginx over HTTPS under /hirdir/ (https://127.0.0.1:$port)"
if wait_ready; then
    pass "S01 GET /hirdir/api/v1/health/ready is 200"
else
    fail "S01 GET /hirdir/api/v1/health/ready is 200 (got $status)"
fi
request GET /hirdir/api/v1/auth/me
expect "S02 GET /hirdir/api/v1/auth/me without a token is refused" "$status" 401

create_user "$admin"
admin_code=$code
check "S02 hirdir admin create-user --role admin prints an access code" test -n "$admin_code"
token=""
sign_in "$admin" "$admin_code"
expect "S02 POST /hirdir/api/v1/auth/sign-in is 200" "$status" 200
check "S02 the sign-in returns a token" test -n "$token"
first_token=$token
authorized GET /hirdir/api/v1/auth/me
expect "S02 GET /hirdir/api/v1/auth/me with the token says admin" "$status $(json_field role)" "200 admin"
authorized GET /hirdir/api/v1/openapi.json
expect "S01 GET /hirdir/api/v1/openapi.json has servers == [{\"url\": \"/hirdir\"}]" \
    "$status $(json_field servers)" '200 [{"url": "/hirdir"}]'

if inside bash -c 'test -f /opt/hirdir/venv/lib/python3.*/site-packages/hirdir/static/index.html'; then
    web_ui=yes
    request GET /hirdir/
    expect "S02 GET /hirdir/ is 200" "$status" 200
    check "S02 GET /hirdir/ is HTML" contains "$(header content-type)" text/html
    check "S02 GET /hirdir/ contains <base href=\"/hirdir/\" />" \
        grep -qF '<base href="/hirdir/" />' "$work/body"
    # The first script or stylesheet the page names, taken from the page's base.
    asset=$(grep -oE '(src|href)="[^"]*assets/[^"]+"' "$work/body" | head -n 1 | sed -E 's/^[a-z]+="//; s/"$//')
    case $asset in
        "") fail "S02 the page names a script or stylesheet under assets/" ;;
        /*) fail "S02 the page names its assets relative to its base (it names $asset)" ;;
        *)
            request GET "/hirdir/${asset#./}"
            expect "S02 GET /hirdir/${asset#./} is 200" "$status" 200
            ;;
    esac
else
    web_ui=no
    skip "S02 GET /hirdir/ is HTML with <base href=\"/hirdir/\" />: this package has NO WEB UI (build it with make deb)"
fi
request GET /hirdir
expect "S01 GET /hirdir redirects to /hirdir/" "$status $(header location)" "301 /hirdir/"

if [ -n "$witness_code" ]; then
    sign_in upgrade-witness "$witness_code"
    expect "pkg the account created before the upgrade still signs in" "$status" 200
    token=$first_token
fi

# ---- on the host: files, restart, backup ---------------------------------------------

section "state, restart and backup"
check "S01 hirdir admin check exits 0" inside hirdir admin check
expect "S01 every file in /var/lib/hirdir is owned by hirdir" \
    "$(inside find /var/lib/hirdir ! -user hirdir 2>&1)" ""
for name in hirdir.db secret.key; do
    mode=$(inside stat -c '%a' "/var/lib/hirdir/$name" 2>&1)
    case $mode in
        [0-7][0-7]0) pass "S01 /var/lib/hirdir/$name is not readable by other users (mode $mode)" ;;
        *) fail "S01 /var/lib/hirdir/$name is not readable by other users (mode $mode)" ;;
    esac
done
expect "S01 nothing under /var/lib/hirdir is readable by other users" \
    "$(inside find /var/lib/hirdir -perm /o=rwx 2>&1)" ""
# Root has run hirdir admin by now. Apart from the byte-code that postinst compiled and
# prerm removes, every file under /opt/hirdir must be one dpkg installed.
expect "S01 nothing is under /opt/hirdir that the package did not install" \
    "$(inside bash -c 'comm -23 <(find /opt/hirdir ! -type d ! -path "*/__pycache__/*" | sort) <(dpkg -L hirdir | sort) | head -n 3' 2>&1)" ""

check "S02 systemctl restart hirdir succeeds" inside systemctl restart hirdir.service
if wait_ready; then
    pass "S02 after the restart the health probe answers again"
else
    fail "S02 after the restart the health probe answers again (got $status)"
fi
authorized GET /hirdir/api/v1/auth/me
expect "S02 after the restart the earlier token is still good" "$status" 200
sign_in "$admin" "$admin_code"
expect "S02 after the restart the account still signs in" "$status" 200

backup=$(inside hirdir admin backup 2>"$work/backup.log" || true)
check "pkg hirdir admin backup prints the file it wrote" contains "$backup" /var/lib/hirdir/backups/hirdir-
expect "pkg the backup belongs to hirdir and is its alone" \
    "$(inside stat -c '%a %U' "${backup:-/nonexistent}" 2>&1)" "600 hirdir"
expect "pkg hirdir-backup.timer is enabled" "$(inside systemctl is-enabled hirdir-backup.timer 2>&1)" enabled
expect "pkg hirdir-backup.timer is waiting" "$(inside systemctl is-active hirdir-backup.timer 2>&1)" active
sleep 1 # A backup is named by the second it was made in.
count=$(inside bash -c 'ls /var/lib/hirdir/backups | wc -l')
check "pkg hirdir-backup.service runs" inside systemctl start hirdir-backup.service
expect "pkg and writes one more backup" "$(inside bash -c 'ls /var/lib/hirdir/backups | wc -l')" "$((count + 1))"

# ---- the browser scenarios --------------------------------------------------------------

if [ "$e2e" = 1 ]; then
    section "browser scenarios (npm --prefix web run e2e)"
    if [ -f web/package.json ] && python3 -c '
import json, sys
sys.exit(0 if "e2e" in json.load(open("web/package.json", encoding="utf-8")).get("scripts", {}) else 1)'; then
        create_user e2e-admin
        # The browser runs in Playwright's own container image, at the version of the
        # Playwright package in web/, so the test does not depend on which libraries
        # the host happens to have. E2E_HOST_BROWSER=1 uses the host's browser instead,
        # and a PW_TEST_CONNECT_WS_ENDPOINT already set is left alone.
        if [ -z "${PW_TEST_CONNECT_WS_ENDPOINT:-}" ] && [ "${E2E_HOST_BROWSER:-0}" != 1 ]; then
            playwright=$(python3 -c '
import json
print(json.load(open("web/node_modules/@playwright/test/package.json", encoding="utf-8"))["version"])')
            browser_port=$(python3 -c '
import socket
with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    print(probe.getsockname()[1])')
            docker run --detach --name "$browser" --network host --ipc host \
                "mcr.microsoft.com/playwright:v$playwright" \
                npx --yes "playwright@$playwright" run-server \
                --host 127.0.0.1 --port "$browser_port" >/dev/null
            for _ in $(seq 1 120); do
                if curl --silent --output /dev/null "http://127.0.0.1:$browser_port/"; then break; fi
                sleep 1
            done
            export PW_TEST_CONNECT_WS_ENDPOINT="ws://127.0.0.1:$browser_port/"
        fi
        if E2E_BASE_URL="https://localhost:$port/hirdir/" E2E_USERNAME=e2e-admin \
            E2E_ACCESS_CODE="$code" npm --prefix web run e2e; then
            pass "S02 npm --prefix web run e2e against https://localhost:$port/hirdir/"
        else
            fail "S02 npm --prefix web run e2e against https://localhost:$port/hirdir/"
        fi
    else
        skip "S02 browser scenarios: web/package.json defines no \"e2e\" script"
    fi
fi

# ---- another prefix -------------------------------------------------------------------

section "hirdir-setup --prefix /inventory"
if inside hirdir-setup --prefix /inventory --yes >"$work/setup-prefix.log" 2>&1; then
    pass "S01 hirdir-setup --prefix /inventory --yes succeeds"
else
    fail "S01 hirdir-setup --prefix /inventory --yes succeeds"
    cat "$work/setup-prefix.log"
fi
prefix=/inventory
if wait_ready; then
    pass "S01 GET /inventory/api/v1/health/ready is 200"
else
    fail "S01 GET /inventory/api/v1/health/ready is 200 (got $status)"
fi
wait_status 404 GET /hirdir/api/v1/health/ready || true
expect "S01 GET /hirdir/api/v1/health/ready no longer answers" "$status" 404
sign_in "$admin" "$admin_code"
expect "S01 POST /inventory/api/v1/auth/sign-in is 200" "$status" 200
authorized GET /inventory/api/v1/openapi.json
expect "S01 GET /inventory/api/v1/openapi.json has servers == [{\"url\": \"/inventory\"}]" \
    "$status $(json_field servers)" '200 [{"url": "/inventory"}]'
request GET /inventory
expect "S01 GET /inventory redirects to /inventory/" "$status $(header location)" "301 /inventory/"
if [ "$web_ui" = yes ]; then
    request GET /inventory/
    check "S02 GET /inventory/ contains <base href=\"/inventory/\" />" \
        grep -qF '<base href="/inventory/" />' "$work/body"
fi

# ---- a site of the host's own -------------------------------------------------------------

section "hirdir-setup on a site that already terminates TLS"
check "pkg hirdir-setup --remove --yes succeeds" inside hirdir-setup --remove --yes
wait_status 000 GET /inventory/api/v1/health/ready || true
expect "pkg after --remove nothing listens on port 443" "$status" 000
check "pkg --remove takes the self-signed site and its certificate away" inside bash -c \
    '! ls -d /etc/nginx/sites-*/hirdir-self-signed /etc/hirdir/self-signed 2>/dev/null | grep -q .'

# What an operator has before hirdir arrives: a site with a certificate of its own.
site=/etc/nginx/sites-available/package-test
inside openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 2 \
    -subj /CN=localhost -keyout /etc/ssl/private/package-test.key \
    -out /etc/ssl/certs/package-test.pem >/dev/null 2>&1 || true
docker exec --interactive "$container" tee "$site" >/dev/null <<'SITE'
server {
    listen 443 ssl;
    server_name localhost;
    ssl_certificate     /etc/ssl/certs/package-test.pem;
    ssl_certificate_key /etc/ssl/private/package-test.key;

    location = /status { return 204; }
}
SITE
inside ln -s "$site" /etc/nginx/sites-enabled/package-test
inside systemctl reload nginx.service || true
wait_status 204 GET /status || true
expect "pkg a TLS site of the host's own answers" "$status" 204

if inside hirdir-setup --site /etc/nginx/sites-enabled/package-test --yes >"$work/setup-site.log" 2>&1; then
    pass "pkg hirdir-setup --site FILE --yes succeeds"
else
    fail "pkg hirdir-setup --site FILE --yes succeeds"
    cat "$work/setup-site.log"
fi
check "pkg it shows the change as a diff before making it" \
    grep -qF '+    include snippets/hirdir.conf;  # added by hirdir-setup' "$work/setup-site.log"
if wait_ready; then
    pass "pkg GET /inventory/api/v1/health/ready is 200 on that site"
else
    fail "pkg GET /inventory/api/v1/health/ready is 200 on that site (got $status)"
fi
request GET /status
expect "pkg the site's own location still answers" "$status" 204
before=$(inside sha256sum "$site")
inside hirdir-setup --site /etc/nginx/sites-enabled/package-test --yes >"$work/setup-again.log" 2>&1 || true
check "pkg run a second time, it says there is nothing to change" \
    grep -q 'Nothing to change' "$work/setup-again.log"
expect "pkg run a second time, it leaves the site as it is" "$(inside sha256sum "$site")" "$before"

check "pkg hirdir-setup --prefix / --yes succeeds" inside hirdir-setup --prefix / --yes
prefix=""
if wait_ready; then
    pass "pkg served at the root, GET /api/v1/health/ready is 200"
else
    fail "pkg served at the root, GET /api/v1/health/ready is 200 (got $status)"
fi
sign_in "$admin" "$admin_code"
authorized GET /api/v1/openapi.json --header 'X-Forwarded-Prefix: /chosen-by-the-client'
expect "pkg served at the root, a prefix header sent by the client is not passed on" \
    "$status $(json_field servers)" "200 null"
if [ "$web_ui" = yes ]; then
    request GET /
    check "pkg served at the root, GET / contains <base href=\"/\" />" \
        grep -qF '<base href="/" />' "$work/body"
fi
check "pkg hirdir-setup --prefix /hirdir --yes puts the packaged prefix back" \
    inside hirdir-setup --prefix /hirdir --yes
check "pkg the snippet is again as the package installed it" \
    inside bash -c 'dpkg --verify hirdir | grep -q snippets/hirdir.conf; test $? -eq 1'
prefix=/hirdir

# A site that hirdir cannot be added to: it has the same location already.
inside hirdir-setup --remove --yes >/dev/null 2>&1 || true
inside sed -i 's|^    location = /status .*|&\n    location ^~ /hirdir/ { return 204; }|' "$site"
inside systemctl reload nginx.service || true
before=$(inside sha256sum "$site")
if inside hirdir-setup --site "$site" --yes >"$work/setup-refused.log" 2>&1; then
    fail "pkg hirdir-setup fails when nginx -t refuses the result"
else
    pass "pkg hirdir-setup fails when nginx -t refuses the result"
fi
check "pkg it says that every file was put back, with what nginx said" \
    grep -q 'every file was put back' "$work/setup-refused.log"
expect "pkg and the site is as it was before" "$(inside sha256sum "$site")" "$before"
check "pkg nginx still accepts its configuration" inside nginx -t
inside sed -i '\|location ^~ /hirdir/ { return 204; }|d' "$site"
check "pkg with the clash gone, hirdir-setup --site FILE --yes succeeds" \
    inside hirdir-setup --site "$site" --yes
if wait_ready; then
    pass "pkg GET /hirdir/api/v1/health/ready is 200 again"
else
    fail "pkg GET /hirdir/api/v1/health/ready is 200 again (got $status)"
fi

cookies=$(grep -ci '^set-cookie:' "$work/headers.all" || true)
expect "S02 none of the $responses responses of this run set a cookie" "$cookies" 0

# ---- purge ----------------------------------------------------------------------------

section "apt-get purge hirdir"
if apt_get purge hirdir; then
    pass "S01 the package purges"
else
    fail "S01 the package purges"
    tail -n 20 "$work/apt.log"
fi
for path in /opt/hirdir /var/lib/hirdir /etc/hirdir /usr/bin/hirdir /etc/nginx/snippets/hirdir.conf; do
    check "S01 the purge leaves no $path" inside test ! -e "$path"
done
check "S01 the purge leaves no hirdir user" bash -c "! docker exec '$container' getent passwd hirdir"
check "S01 the purge leaves no hirdir group" bash -c "! docker exec '$container' getent group hirdir"
check "S01 the purge leaves no unit enabled" \
    inside bash -c '! find /etc/systemd/system -name "hirdir*" | grep -q .'
check "S01 after the purge nginx still accepts its configuration" inside nginx -t
check "pkg the purge took the include out of the site hirdir-setup had edited" \
    inside bash -c "! grep -q hirdir '$site'"
request GET /status
expect "pkg and that site still answers" "$status" 204
expect "S01 after the purge nginx is still running" "$(inside systemctl is-active nginx.service 2>&1)" active

# ---- summary --------------------------------------------------------------------------

section "summary"
echo "package-test: $(basename "$deb"), web UI in the package: $web_ui"
if [ "$failures" -gt 0 ]; then
    echo "package-test: $failures check(s) FAILED"
    echo "--- journal of hirdir.service"
    inside journalctl --unit hirdir.service --no-pager --lines 30 2>&1 || true
    echo "--- /var/log/nginx/error.log"
    inside tail -n 20 /var/log/nginx/error.log 2>&1 || true
    exit 1
fi
echo "package-test: all checks passed"
