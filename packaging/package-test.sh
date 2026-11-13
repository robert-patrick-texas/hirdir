#!/bin/bash
# Install the package in a clean Ubuntu 26.04 container that runs systemd, and exercise
# it through nginx over HTTPS under a URL prefix. "make package-test" runs this, and
# "make e2e" runs it with --e2e. It needs docker, curl, python3, make and dpkg-deb on
# the host.
#
# Usage: packaging/package-test.sh [--e2e] [--upgrade | --failed-upgrade | --fresh]
#
# There are three passes, each in a container of its own. With none named, all three
# run one after another and a summary of them all ends the run.
#
#   --upgrade          install the previous release, put accounts, a group, a role grant,
#                      a service token, audit events, a vendor with a catalog entry and
#                      an item, and a changed configuration into it, upgrade it with apt,
#                      and see that all of it is still there and still works, under the
#                      prefix it had; then everything the fresh pass does
#   --failed-upgrade   install the previous release and make the migration of the new
#                      one fail: the upgrade must stop and name the backup, and the way
#                      back that its message gives must work
#   --fresh            install on a system that never had hirdir, as a new
#                      installation does, and exercise it: the examples imported and
#                      exported through nginx, then the inventory made by hand
#   --e2e              in the fresh pass, also run the browser scenarios of web/
#                      against the container (npm --prefix web run e2e). The browser
#                      runs in Playwright's container image unless E2E_HOST_BROWSER=1
#                      asks for the host's, or PW_TEST_CONNECT_WS_ENDPOINT names one.
# Environment:
#   DEB            the package to test (default: dist/hirdir_<version>_amd64.deb)
#   PREVIOUS_DEB   the package of the previous release, for the two upgrade passes.
#                  Left out, it is the hirdir_*_amd64.deb beside DEB with the highest
#                  version below the one being tested.
#
# When no previous package is found, the two upgrade passes are skipped and the run
# says so with a SKIP line that names what was not tested and how to test it. The
# fresh install is tested all the same. --fresh alone asks for just that.
#
# Every check prints a line that starts with PASS, FAIL or SKIP. A failed check is
# counted and the run goes on, so that one run reports every problem. The exit status
# is 0 only when no check failed. The container and its image are always removed.
#
# A check that belongs to a scenario of docs/build-plan.md carries its number, S01 or
# S02 for the package and sign-in, S06 to S11 for the inventory, S12, S13 and S16 for
# files. The others, marked pkg, are about the package alone.
#
# The files are sent with curl, as the API takes them. The client commands of the
# command line (hirdir import, hirdir export, hirdir items) are then run in the
# container, from the package, by client_commands().
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
self=packaging/package-test.sh

usage() {
    echo "usage: $self [--e2e] [--upgrade | --failed-upgrade | --fresh]" >&2
    exit 2
}

e2e=0
mode=""
for argument in "$@"; do
    case $argument in
        --e2e) e2e=1 ;;
        --upgrade | --failed-upgrade | --fresh)
            [ -z "$mode" ] || usage
            mode=${argument#--}
            ;;
        *) usage ;;
    esac
done

version=$(make -s version)
deb=${DEB:-dist/hirdir_${version}_amd64.deb}
if [ ! -f "$deb" ]; then
    echo "package-test: there is no $deb. Build the package first: make deb" >&2
    exit 2
fi

# ---- the previous release ---------------------------------------------------------------

# The hirdir package beside $deb with the highest version below $version, or nothing.
find_previous() {
    local candidate found best="" best_version=""
    for candidate in "$(dirname "$deb")"/hirdir_*_amd64.deb; do
        [ -f "$candidate" ] || continue
        found=$(dpkg-deb -f "$candidate" Version 2>/dev/null) || continue
        dpkg --compare-versions "$found" lt "$version" || continue
        if [ -z "$best" ] || dpkg --compare-versions "$found" gt "$best_version"; then
            best=$candidate
            best_version=$found
        fi
    done
    printf '%s' "$best"
}

# The newest release with notes in docs/releases/ that is older than $version, or nothing.
earlier_release() {
    local notes found
    for notes in docs/releases/v*.md; do
        [ -f "$notes" ] || continue
        found=${notes##*/v}
        found=${found%.md}
        if dpkg --compare-versions "$found" lt "$version" 2>/dev/null; then echo "$found"; fi
    done | sort -V | tail -n 1
}

previous=${PREVIOUS_DEB:-}
if [ -n "$previous" ]; then
    if [ ! -f "$previous" ]; then
        echo "package-test: PREVIOUS_DEB names $previous, and there is no such file." >&2
        exit 2
    fi
    previous_found="named by PREVIOUS_DEB"
else
    previous=$(find_previous)
    previous_found="the highest version below $version in $(dirname "$deb")/"
fi
previous_version=""
if [ -n "$previous" ]; then previous_version=$(dpkg-deb -f "$previous" Version); fi

# ---- every pass ---------------------------------------------------------------------------

# With no pass named: run each one as a command of its own, and sum them up.
every_pass() {
    local log failed=0 code option earlier options arguments
    log=$(mktemp)
    # shellcheck disable=SC2064  # The file's name is fixed now, on purpose.
    trap "rm -f '$log'" EXIT
    if [ -n "$previous" ]; then
        options=(--upgrade --failed-upgrade --fresh)
    else
        options=(--fresh)
        earlier=$(earlier_release)
        if [ -n "$earlier" ]; then
            echo "SKIP  pkg upgrade from the previous release: hirdir $earlier was released before $version, and no package older than $version is in $(dirname "$deb")/, so no upgrade was tested by this run. Put the package of the previous release there, or name it with PREVIOUS_DEB, to test it" | tee -a "$log"
        else
            echo "SKIP  pkg upgrade from the previous release: docs/releases/ holds no release before $version, so there is nothing to upgrade from" | tee -a "$log"
        fi
    fi
    for option in "${options[@]}"; do
        arguments=("$option")
        if [ "$e2e" = 1 ] && [ "$option" = --fresh ]; then arguments+=(--e2e); fi
        code=0
        # A pass finds the previous package as this run did: by PREVIOUS_DEB when the
        # person set it, which the pass inherits, and beside the package otherwise.
        DEB=$deb PACKAGE_TEST_EVERY_PASS=1 bash "$self" "${arguments[@]}" 2>&1 |
            tee -a "$log" || code=$?
        if [ "$code" -ne 0 ]; then
            failed=1
            grep -q "^package-test: ${option#--}: " "$log" ||
                echo "FAIL  pkg the ${option#--} pass ran to its end (it stopped with status $code)" | tee -a "$log"
        fi
    done

    printf '\n== every pass\n'
    grep -E '^package-test: [a-z-]+: [0-9]+ PASS, ' "$log" || true
    echo "package-test: in all: $(grep -c '^PASS  ' "$log" || true) PASS," \
        "$(grep -c '^FAIL  ' "$log" || true) FAIL, $(grep -c '^SKIP  ' "$log" || true) SKIP"
    grep -E '^(FAIL|SKIP)  ' "$log" || true
    if [ "$failed" -ne 0 ]; then
        echo "package-test: FAILED"
        exit 1
    fi
    echo "package-test: all checks passed"
    exit 0
}

if [ -z "$mode" ]; then every_pass; fi

case $mode in
    upgrade | failed-upgrade)
        if [ -z "$previous" ]; then
            echo "package-test: --$mode needs the package of the previous release, and no" >&2
            echo "package-test: package older than $version is in $(dirname "$deb")/." >&2
            echo "package-test: Put it there, or name it with PREVIOUS_DEB." >&2
            exit 2
        fi
        ;;
esac

# Names of this run alone, so that two runs at once do not collide.
run_id=$$-$RANDOM
image=hirdir-package-test:$run_id
container=hirdir-package-test-$run_id
work=$(mktemp -d)
admin=package-test-admin
passes=0
failures=0
skips=0
responses=0
status=""
port=""
prefix=""
token=""
code=""
web_ui=no

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
note() { printf 'note  %s\n' "$*"; }
pass() {
    printf 'PASS  %s\n' "$*"
    passes=$((passes + 1))
}
skip() {
    printf 'SKIP  %s\n' "$*"
    skips=$((skips + 1))
}
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

# api METHOD PATH [JSON]: a request to the API under $prefix with the token in $token,
# and a JSON body when one is given.
api() {
    local method=$1 path=$2
    shift 2
    if [ $# -gt 0 ]; then
        authorized "$method" "$prefix/api/v1$path" --header 'Content-Type: application/json' --data "$1"
    else
        authorized "$method" "$prefix/api/v1$path"
    fi
}

# send PATH FILE [TYPE]: POST a file as the body of a request to the API under $prefix,
# which is how an import is sent. PATH carries the query. The type is text/csv unless
# given. A large file has two minutes.
send() {
    authorized POST "$prefix/api/v1$1" --header "Content-Type: ${3:-text/csv}" \
        --data-binary "@$2" --max-time 120
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

# json EXPRESSION: the value of a Python expression over the JSON in $work/body, which
# the expression calls d. A string is printed as it is, anything else as JSON.
json() {
    python3 -c '
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    value = eval(sys.argv[2])
except Exception as error:
    value = f"<{type(error).__name__}: {error}>"
print(value if isinstance(value, str) else json.dumps(value, sort_keys=True))' "$work/body" "$1"
}

# table EXPRESSION [FILE]: the value of a Python expression over a CSV file, which is the
# body of the last response when none is named. The expression calls the names of the
# columns head, and the rows, each a dict by column, rows.
table() {
    python3 -c '
import csv, json, sys
try:
    with open(sys.argv[2], encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        rows = list(reader)
        head = list(reader.fieldnames or [])
    value = eval(sys.argv[1])
except Exception as error:
    value = f"<{type(error).__name__}: {error}>"
print(value if isinstance(value, str) else json.dumps(value, sort_keys=True))' "$1" "${2:-$work/body}"
}

# job_counts: what the import job in the last response says: its status, how many rows
# it has, and how many of them create, update, find their record unchanged and are
# rejected. An apply answers with the job, and a preview with the job and its rows.
job_counts() {
    json '(lambda j: [j["status"], j["row_count"], j["created"], j["updated"], j["unchanged"], j["rejected"]])(d.get("job", d))'
}

# keep NAME: keep the JSON of the last response for unchanged to compare with.
keep() { cp "$work/body" "$work/kept-$1.json"; }

# unchanged NAME [more]: print "same" when every record kept under NAME is in the last
# response with the same HID and every field as it was, and no record was added. With
# "more", records may have been added. Otherwise print what differs.
unchanged() {
    python3 -c '
import json, sys

def records(path):
    document = json.load(open(path, encoding="utf-8"))
    return document["items"] if isinstance(document, dict) else document

try:
    before = records(sys.argv[1])
    now = {record["hid"]: record for record in records(sys.argv[2])}
except Exception as error:
    print(f"<{type(error).__name__}: {error}>")
    sys.exit()
problems = []
if len(now) != len(before) and sys.argv[3] != "more":
    problems.append(f"{len(now)} records where there were {len(before)}")
for record in before:
    hid = record["hid"]
    found = now.get(hid)
    if found is None:
        problems.append(hid + " is gone")
        continue
    changed = sorted(key for key, value in record.items() if found.get(key, "<absent>") != value)
    if changed:
        problems.append(hid + " changed in " + ", ".join(changed))
print("; ".join(problems[:3]) if problems else "same")' "$work/kept-$1.json" "$work/body" "${2:-exact}"
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

# How many hours the session of the sign-in just made lasts, to one decimal place.
session_hours() {
    python3 -c '
import json, sys
from datetime import UTC, datetime

expires = datetime.fromisoformat(json.load(open(sys.argv[1], encoding="utf-8"))["expires_at"])
if expires.tzinfo is None:
    expires = expires.replace(tzinfo=UTC)
print(f"{(expires - datetime.now(UTC)).total_seconds() / 3600:.1f}")' "$work/body" 2>&1
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

# local_status METHOD PATH [JSON]: the status of a request made inside the container,
# straight to the service on its loopback port, by the Python of the package. For the
# pass that installs no nginx.
local_status() {
    inside /opt/hirdir/python/bin/python3 -I -c '
import sys, urllib.error, urllib.request

body = sys.argv[3].encode() if len(sys.argv) > 3 else None
request = urllib.request.Request(
    "http://127.0.0.1:8715" + sys.argv[2],
    data=body,
    method=sys.argv[1],
    headers={"Content-Type": "application/json"},
)
try:
    print(urllib.request.urlopen(request, timeout=10).status)
except urllib.error.HTTPError as error:
    print(error.code)
except OSError:
    print("000")' "$@" 2>&1
}

# Wait until the service answers its health probe on the loopback port.
wait_local_ready() {
    for _ in $(seq 30); do
        if [ "$(local_status GET /api/v1/health/ready)" = 200 ]; then return 0; fi
        sleep 1
    done
    return 1
}

# past_nginx BYTES: send a CSV file of that many bytes as an import, with the token in
# $token, straight to the service on its loopback port inside the container. Prints the
# status and the content type of the answer, which is hirdir's own and not nginx's.
past_nginx() {
    inside /opt/hirdir/python/bin/python3 -I -c '
import sys, urllib.error, urllib.request

head = b"label\n"
request = urllib.request.Request(
    "http://127.0.0.1:8715/api/v1/imports/preview?entity=tags",
    data=head + b"x" * (int(sys.argv[2]) - len(head)),
    method="POST",
    headers={"Content-Type": "text/csv", "Authorization": "Bearer " + sys.argv[1]},
)
try:
    answer = urllib.request.urlopen(request, timeout=60)
except urllib.error.HTTPError as error:
    answer = error
except OSError as error:
    sys.exit(f"000 {error}")
print(answer.code, answer.headers.get("Content-Type"))' "$token" "$1" 2>&1
}

# create_user NAME: create an Admin with hirdir admin. Sets $code to its access code.
create_user() {
    inside hirdir admin create-user --role admin "$1" >"$work/create-user.log" 2>&1 || true
    code=$(sed -n 's/^access code: //p' "$work/create-user.log")
}

# sqlite_value FILE SQL: the first value of the first row, read from a SQLite file in
# the container by the Python of the package, as the hirdir user.
sqlite_value() {
    inside runuser -u hirdir -- /opt/hirdir/python/bin/python3 -I -c '
import sqlite3, sys

row = sqlite3.connect(sys.argv[1]).execute(sys.argv[2]).fetchone()
print("" if row is None else row[0])' "$1" "$2" 2>&1 | tail -n 1
}

# sqlite_run SQL: run one statement on the database of the installation, as hirdir.
sqlite_run() {
    inside runuser -u hirdir -- /opt/hirdir/python/bin/python3 -I -c '
import sqlite3, sys

connection = sqlite3.connect("/var/lib/hirdir/hirdir.db", timeout=10)
connection.execute(sys.argv[1])
connection.commit()' "$1"
}

# schema_sum FILE: one checksum of the schema of a SQLite file in the container: every
# table, index and trigger, statement for statement. A migration that was undone as a
# whole leaves it as it was, also where it changes a table and does not create one.
schema_sum() {
    inside runuser -u hirdir -- /opt/hirdir/python/bin/python3 -I -c '
import hashlib, sqlite3, sys

rows = sqlite3.connect(sys.argv[1]).execute(
    "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
).fetchall()
print(hashlib.sha256(repr(rows).encode()).hexdigest())' "$1" 2>&1 | tail -n 1
}

# The schema revision the installed hirdir finds in its database.
revision_now() { inside hirdir admin check 2>/dev/null | sed -n 's/^schema revision: *\([^ ]*\) .*/\1/p'; }

# migrations QUESTION [REVISION]: read the migrations the package under test carries.
#   head             the newest revision
#   created REVISION the table that the migrations after REVISION create last, or nothing
#   tables REVISION  every table that the migrations after REVISION create, in order
migrations() {
    dpkg-deb --fsys-tarfile "$deb" |
        tar --extract --to-stdout --wildcards '*/site-packages/hirdir/db/migrations/versions/*.py' |
        python3 -c '
import re, sys

# Each file names its revision before the tables it creates.
parts = re.split(r"^revision = \"([^\"]+)\"$", sys.stdin.read(), flags=re.M)
tables = {
    revision: re.findall(r"op\.create_table\(\s*\"([^\"]+)\"", source)
    for revision, source in zip(parts[1::2], parts[2::2])
}
if sys.argv[1] == "head":
    print(max(tables, default=""))
else:
    later = [name for revision in sorted(tables) if revision > sys.argv[2] for name in tables[revision]]
    print(" ".join(later) if sys.argv[1] == "tables" else later[-1] if later else "")' "$@"
}

# shipped_snippet PACKAGE: the nginx snippet a package ships. From 0.3.0 it is the text
# that hirdir-setup --renew writes out, and before that it was a conffile.
shipped_snippet() {
    dpkg-deb --fsys-tarfile "$1" | tar --extract --to-stdout \
        ./usr/share/hirdir/nginx/snippet.conf ./etc/nginx/snippets/hirdir.conf 2>/dev/null || true
}

# The version of hirdir that dpkg has installed, or nothing.
installed_version() { inside dpkg-query -W -f "\${Version}" hirdir 2>/dev/null || true; }

apt_get() { inside apt-get -o Dpkg::Use-Pty=0 --yes "$@" >"$work/apt.log" 2>&1; }

# What is in the two conffiles of the package, and whether dpkg left a second copy of
# either beside it, or of the nginx snippet, which was a conffile up to 0.2.1.
conffiles() {
    inside bash -c 'sha256sum /etc/hirdir/config.toml /etc/nginx/conf.d/hirdir.conf;
        ls /etc/hirdir /etc/nginx/conf.d /etc/nginx/snippets | grep -E "\.dpkg-|\.ucf-" || true' 2>&1
}

# The nginx snippet of the installation, without the three lines that hold the prefix.
# What is left is the same under every prefix, and is what a version ships.
snippet_body() { inside grep -v '# prefix$' /etc/nginx/snippets/hirdir.conf 2>&1 || true; }

# ---- the container --------------------------------------------------------------------

start_container() {
    section "container"
    check "S01 the package ships no byte-code from the build" \
        bash -c "! dpkg-deb -c '$deb' | grep -Eq '__pycache__|\\.pyc\$'"

    docker build --quiet --tag "$image" - <packaging/container/Dockerfile.systemd >/dev/null
    # systemd as init needs a privileged container with a cgroup tree of its own. HTTPS is
    # published on the loopback address of the host only, on a port docker chooses.
    local start state
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
    if [ "$mode" != fresh ]; then
        docker cp --quiet "$previous" "$container:/srv/debs/hirdir-previous.deb"
    fi
    inside chmod -R a+rX /srv/debs
}

# Checks of the previous package itself, before it is installed.
previous_package() {
    note "the previous release is $(basename "$previous"), $previous_found"
    check "pkg the previous package, $previous_version, is older than $version" \
        dpkg --compare-versions "$previous_version" lt "$version"
    if [ -f "$previous.sha256" ]; then
        expect "pkg the previous package has the SHA-256 written beside it" \
            "$(sha256sum "$previous" | cut -d' ' -f1)" "$(cut -d' ' -f1 "$previous.sha256")"
    fi
    local earlier
    earlier=$(earlier_release)
    if [ -n "$earlier" ] && [ "$earlier" != "$previous_version" ]; then
        note "docs/releases/ says the release before $version is $earlier; this pass upgrades from $previous_version"
    fi
}

install_previous() {
    if apt_get install /srv/debs/hirdir-previous.deb; then
        pass "pkg the previous package installs ($(basename "$previous"))"
    else
        fail "pkg the previous package installs ($(basename "$previous"))"
        tail -n 20 "$work/apt.log"
    fi
    expect "pkg the installed version is $previous_version" "$(installed_version)" "$previous_version"
}

# ---- the pass whose migration fails --------------------------------------------------------

failed_upgrade() {
    local witness_code revision_before planted tables_before backup good_backup command body
    local schema_before snippet_before created name database=/var/lib/hirdir/hirdir.db

    section "the previous release, $previous_version, with an account in it"
    previous_package
    if ! apt_get update; then
        fail "pkg apt-get update succeeds"
        tail -n 20 "$work/apt.log"
    fi
    install_previous
    create_user upgrade-witness
    witness_code=$code
    check "pkg an Admin is created with $previous_version" test -n "$witness_code"
    body=$(python3 -c 'import json, sys; print(json.dumps({"username": "upgrade-witness", "access_code": sys.argv[1]}))' "$witness_code")
    wait_local_ready || true
    expect "pkg that Admin signs in" "$(local_status POST /api/v1/auth/sign-in "$body")" 200
    revision_before=$(revision_now)
    check "pkg hirdir admin check of $previous_version names its schema revision ($revision_before)" \
        test -n "$revision_before"

    # The migration is made to fail by the database, not by the package: a table that
    # the new version is about to create is already there. The package under test is
    # installed exactly as it was built.
    planted=$(migrations created "$revision_before")
    if [ -z "$planted" ]; then
        skip "pkg a migration that fails stops the upgrade: no migration of $version after revision $revision_before creates a table, so this pass has no table to put in its way and needs another cause of failure"
        return
    fi
    if sqlite_run "CREATE TABLE \"$planted\" (planted_by_package_test INTEGER)" >/dev/null 2>&1; then
        pass "pkg a table named $planted, which the migration creates last, is put in its way"
    else
        fail "pkg a table named $planted, which the migration creates last, is put in its way"
    fi
    tables_before=$(sqlite_value "$database" "SELECT count(*) FROM sqlite_master WHERE type = 'table'")
    schema_before=$(schema_sum "$database")
    snippet_before=$(inside sha256sum /etc/nginx/snippets/hirdir.conf 2>&1)

    section "the upgrade to $version, whose migration fails"
    if apt_get install /srv/debs/hirdir-new.deb; then
        fail "pkg apt reports that the upgrade failed (it reported success)"
    else
        pass "pkg apt reports that the upgrade failed"
    fi
    cp "$work/apt.log" "$work/failed.log"
    check "pkg the message says that the migration failed and the service was not started" \
        grep -qxF 'hirdir: the migration failed, and the service was not started.' "$work/failed.log"
    backup=$(sed -n 's/^hirdir: the database as it was before the upgrade is at //p' "$work/failed.log")
    check "pkg the message names the backup of the database (${backup:-nothing})" test -n "$backup"
    check "pkg that backup exists" inside test -s "${backup:-/nonexistent}"
    expect "pkg the backup holds the schema as it was, at revision $revision_before" \
        "$(sqlite_value "${backup:-/nonexistent}" 'SELECT version_num FROM alembic_version')" "$revision_before"
    expect "pkg the backup holds the account" \
        "$(sqlite_value "${backup:-/nonexistent}" "SELECT count(*) FROM users WHERE username = 'upgrade-witness'")" 1
    for command in \
        "sudo apt install --allow-downgrades ./hirdir_${previous_version}_amd64.deb" \
        "sudo systemctl stop hirdir" \
        "sudo hirdir admin restore $backup" \
        "sudo systemctl start hirdir"; do
        check "pkg the message gives the way back: $command" \
            grep -qxF "hirdir:     $command" "$work/failed.log"
    done
    expect "pkg dpkg holds hirdir $version as not configured" \
        "$(inside dpkg-query -W -f "\${Version} \${Status}" hirdir 2>&1)" "$version install ok half-configured"
    expect "pkg the service was not started" "$(inside systemctl is-active hirdir.service 2>&1)" inactive
    expect "pkg the database still says revision $revision_before" "$(revision_now)" "$revision_before"
    expect "pkg the failed migration was undone as a whole: none of its tables is left behind" \
        "$(sqlite_value "$database" "SELECT count(*) FROM sqlite_master WHERE type = 'table'")" "$tables_before"
    expect "pkg and no table from before is changed: the schema is, statement for statement, as it was" \
        "$(schema_sum "$database")" "$schema_before"
    expect "pkg and the account is still in it" \
        "$(sqlite_value "$database" "SELECT count(*) FROM users WHERE username = 'upgrade-witness'")" 1
    expect "pkg the upgrade that stopped left the nginx snippet as $previous_version had it" \
        "$(inside sha256sum /etc/nginx/snippets/hirdir.conf 2>&1)" "$snippet_before"

    section "the way back that the message gives"
    if apt_get install --allow-downgrades /srv/debs/hirdir-previous.deb; then
        pass "pkg apt install --allow-downgrades puts $previous_version back"
    else
        fail "pkg apt install --allow-downgrades puts $previous_version back"
        tail -n 20 "$work/apt.log"
    fi
    expect "pkg dpkg holds hirdir $previous_version as installed" \
        "$(inside dpkg-query -W -f "\${Version} \${Status}" hirdir 2>&1)" "$previous_version install ok installed"
    check "pkg systemctl stop hirdir succeeds" inside systemctl stop hirdir.service
    check "pkg hirdir admin restore BACKUP succeeds" inside hirdir admin restore "${backup:-/nonexistent}"
    check "pkg systemctl start hirdir succeeds" inside systemctl start hirdir.service
    expect "pkg the database has the tables it had before the upgrade was tried, and no more" \
        "$(sqlite_value "$database" "SELECT count(*) FROM sqlite_master WHERE type = 'table'")" "$tables_before"
    check "pkg hirdir admin check of $previous_version exits 0" inside hirdir admin check
    if wait_local_ready; then
        pass "pkg $previous_version serves again"
    else
        fail "pkg $previous_version serves again"
    fi
    expect "pkg the Admin signs in with the access code from before" \
        "$(local_status POST /api/v1/auth/sign-in "$body")" 200

    section "the upgrade again, with its cause put right"
    check "pkg the table that was in the way is taken out" sqlite_run "DROP TABLE \"$planted\""
    if apt_get install /srv/debs/hirdir-new.deb; then
        pass "pkg apt upgrades hirdir $previous_version to $version"
    else
        fail "pkg apt upgrades hirdir $previous_version to $version"
        tail -n 30 "$work/apt.log"
    fi
    good_backup=$(sed -n 's/^hirdir: the database as it was before this upgrade is kept at //p' "$work/apt.log")
    expect "pkg dpkg holds hirdir $version as installed" \
        "$(inside dpkg-query -W -f "\${Version} \${Status}" hirdir 2>&1)" "$version install ok installed"
    expect "pkg the schema is at revision $head" "$(revision_now)" "$head"
    check "pkg hirdir admin check exits 0" inside hirdir admin check
    created=""
    for name in $(migrations tables "$revision_before"); do
        created="${created:+$created }$(sqlite_value "$database" "SELECT name FROM sqlite_master WHERE type = 'table' AND name = '$name'")"
    done
    expect "pkg every table that the migration creates is there now" \
        "$created" "$(migrations tables "$revision_before")"
    # No nginx is installed in this pass. The snippet is written all the same, for the
    # day there is one.
    expect "pkg the nginx snippet is the one $version ships, though no nginx is installed" \
        "$(snippet_body | sha256sum)" "$(shipped_snippet "$deb" | grep -v '# prefix$' | sha256sum)"
    if wait_local_ready; then
        pass "pkg $version serves"
    else
        fail "pkg $version serves"
    fi
    expect "pkg the Admin signs in with the access code from before" \
        "$(local_status POST /api/v1/auth/sign-in "$body")" 200

    # The way docs/install.md gives under "Going back to the release before". The first
    # step is the older package meeting a database it cannot read: it must stop there.
    section "going back from $version to $previous_version after a good upgrade"
    if apt_get install --allow-downgrades /srv/debs/hirdir-previous.deb; then
        fail "pkg $previous_version stops at the database that $version has changed (it went on)"
    else
        pass "pkg $previous_version stops at the database that $version has changed"
    fi
    expect "pkg and leaves that database as it is, at revision $head" \
        "$(sqlite_value /var/lib/hirdir/hirdir.db 'SELECT version_num FROM alembic_version')" "$head"
    expect "pkg the service is not running" "$(inside systemctl is-active hirdir.service 2>&1)" inactive
    check "pkg hirdir admin restore of the backup that the upgrade took succeeds (${good_backup:-no backup})" \
        inside hirdir admin restore "${good_backup:-/nonexistent}"
    check "pkg dpkg --configure hirdir succeeds" inside dpkg --configure hirdir
    expect "pkg dpkg holds hirdir $previous_version as installed" \
        "$(inside dpkg-query -W -f "\${Version} \${Status}" hirdir 2>&1)" "$previous_version install ok installed"
    # The older package takes the nginx snippet for its conffile again. dpkg must not
    # ask about it: there is nobody to answer, and the installation would stop there.
    expect "pkg dpkg kept the nginx snippet that $version wrote, and left no second copy of it" \
        "$(snippet_body | sha256sum) $(inside bash -c 'ls /etc/nginx/snippets | grep -c "\.dpkg-"' 2>&1)" \
        "$(shipped_snippet "$deb" | grep -v '# prefix$' | sha256sum) 0"
    expect "pkg the schema is at revision $revision_before again" "$(revision_now)" "$revision_before"
    if wait_local_ready; then
        pass "pkg $previous_version serves again"
    else
        fail "pkg $previous_version serves again"
    fi
    expect "pkg the Admin signs in with the access code from before" \
        "$(local_status POST /api/v1/auth/sign-in "$body")" 200
    if apt_get purge hirdir; then
        pass "pkg the package purges"
    else
        fail "pkg the package purges"
        tail -n 20 "$work/apt.log"
    fi
}

# ---- the previous release, with real state in it -------------------------------------------

# What the upgrade pass makes with the previous release and looks for afterwards.
old_admin_code=""
old_session=""
engineer_code=""
robot_hid=""
service_secret=""
revision_before=""
witness_entry=""
witness_item=""
witness_weight=""
users_before=0
events_before=0
conffiles_before=""

previous_release() {
    local engineer_hid group_hid held

    section "the previous release, $previous_version, with accounts and a changed configuration"
    previous_package
    install_previous
    revision_before=$(revision_now)
    check "pkg hirdir admin check of $previous_version names its schema revision ($revision_before)" \
        test -n "$revision_before"

    # What an operator does to the conffiles: another prefix, which hirdir-setup writes
    # into the nginx snippet, and a value changed in the configuration file.
    prefix=/before-upgrade
    if inside hirdir-setup --self-signed --prefix "$prefix" --yes >"$work/setup-previous.log" 2>&1; then
        pass "pkg hirdir-setup of $previous_version puts it under $prefix/"
    else
        fail "pkg hirdir-setup of $previous_version puts it under $prefix/"
        cat "$work/setup-previous.log"
    fi
    inside sed -i 's/^# session_hours = 12$/session_hours = 11/' /etc/hirdir/config.toml
    check "pkg the configuration file is edited: session_hours = 11" \
        inside grep -qx 'session_hours = 11' /etc/hirdir/config.toml
    inside systemctl restart hirdir.service || true
    if wait_ready; then
        pass "pkg $previous_version answers through nginx under $prefix/"
    else
        fail "pkg $previous_version answers through nginx under $prefix/ (got $status)"
    fi

    create_user upgrade-admin
    old_admin_code=$code
    check "pkg an Admin is created with $previous_version" test -n "$old_admin_code"
    sign_in upgrade-admin "$old_admin_code"
    expect "pkg that Admin signs in, and the session lasts the 11 hours of the edited configuration" \
        "$status $(session_hours)" "200 11.0"
    old_session=$token

    api POST /users '{"username": "upgrade-engineer", "display_name": "An engineer of the upgrade test"}'
    expect "pkg a second user is created" "$status" 201
    engineer_hid=$(json 'd["user"]["hid"]')
    engineer_code=$(json 'd["access_code"]')
    api POST /user-groups '{"name": "Network Engineering", "description": "Made before the upgrade"}'
    expect "pkg a user group is created" "$status" 201
    group_hid=$(json_field hid)
    api PUT "/user-groups/$group_hid/members/$engineer_hid"
    expect "pkg the second user is put in the group" "$status" 204
    api POST /role-grants "{\"role\": \"inventory\", \"group_hid\": \"$group_hid\"}"
    expect "pkg the Inventory role is granted to the group" "$status" 201
    api POST /users '{"username": "upgrade-robot", "is_service_account": true, "role": "viewer"}'
    expect "pkg a service account is created with the View-only role" "$status" 201
    robot_hid=$(json 'd["user"]["hid"]')
    api POST "/users/$robot_hid/service-tokens" '{"name": "nightly export"}'
    expect "pkg a service token is created for it" "$status" 201
    service_secret=$(json_field secret)

    # A previous release that already keeps the inventory is given some to carry over.
    # 0.2.0 kept support weight to three places, and every release since keeps two.
    api GET /vendors
    if [ "$status" = 200 ]; then
        witness_weight=1.25
        if [ "$previous_version" = 0.2.0 ]; then witness_weight=0.125; fi
        api POST /vendors '{"name": "Upgrade Witness Networks"}'
        expect "pkg $previous_version holds a vendor" "$status" 201
        api POST /catalog-entries "{\"vendor_hid\": \"$(json_field hid)\", \"pid\": \"UW-48P\", \"est_value\": \"18000.00\", \"support_weight\": \"$witness_weight\"}"
        expect "pkg $previous_version holds a catalog entry with a value and a support weight of $witness_weight" "$status" 201
        witness_entry=$(json_field hid)
        api POST /items "{\"catalog_entry_hid\": \"$witness_entry\", \"serial_number\": \"UWN0000X001\", \"support_weight\": \"1.5\"}"
        expect "pkg and an item of it with a support weight of its own" "$status" 201
        witness_item=$(json_field hid)
    fi

    sign_in upgrade-engineer not-the-access-code
    expect "pkg a wrong access code is refused" "$status" 401
    sign_in upgrade-engineer "$engineer_code"
    api GET /auth/me
    expect "pkg the second user signs in and holds Inventory through the group" \
        "$status $(json_field role)" "200 inventory"
    token=$service_secret
    api GET /auth/me
    expect "pkg the service token authenticates as the service account" \
        "$status $(json_field username) $(json_field role)" "200 upgrade-robot viewer"

    # Everything as it is now, read with the session that is kept in hand.
    token=$old_session
    api GET '/users?limit=1000'
    keep users
    users_before=$(json 'len(d["items"])')
    api GET /user-groups
    keep groups
    held="$users_before users, $(json 'len(d)') group with $(json 'd[0]["member_count"]') member"
    api GET /role-grants
    keep grants
    held="$held, $(json 'len(d)') role grants"
    api GET "/users/$robot_hid/service-tokens"
    keep tokens
    held="$held, $(json 'len(d)') service token"
    api GET '/audit-events?limit=1000'
    keep events
    events_before=$(json 'd["total"]')
    expect "pkg $previous_version now holds the accounts, the group, the grants and the token" \
        "$held" "3 users, 1 group with 1 member, 3 role grants, 1 service token"
    check "pkg and an audit event for each thing done ($events_before events)" test "$events_before" -ge 10
    if [ -n "$witness_entry" ]; then
        api GET /vendors
        keep vendors
    fi
    # A previous release whose snippet sets no limit leaves nginx at its own, a megabyte.
    # The same file is sent again after the upgrade, when nginx must let it through.
    if ! shipped_snippet "$previous" | grep -q client_max_body_size; then
        large_file "$work/large-upgraded.csv" "Upgrade Witness Networks" UW-48P
        send "/imports/preview?entity=items&file_name=large-upgraded.csv" "$work/large-upgraded.csv"
        expect "pkg behind the nginx snippet of $previous_version a file of $(megabytes "$work/large-upgraded.csv") is refused by nginx, with its 413 page" \
            "$status $(header content-type)" "413 text/html"
    fi
    conffiles_before=$(conffiles)
}

upgrade() {
    local backup renewed created name

    section "apt upgrades $previous_version to $version"
    if apt_get install /srv/debs/hirdir-new.deb; then
        pass "pkg apt upgrades hirdir $previous_version to $version"
    else
        fail "pkg apt upgrades hirdir $previous_version to $version"
        tail -n 30 "$work/apt.log"
    fi
    cp "$work/apt.log" "$work/install.log"
    expect "pkg the installed version is $version" "$(installed_version)" "$version"

    backup=$(sed -n 's/^hirdir: the database as it was before this upgrade is kept at //p' "$work/install.log")
    check "pkg the upgrade says where it kept a backup of the database (${backup:-nowhere})" test -n "$backup"
    check "pkg that backup exists" inside test -s "${backup:-/nonexistent}"
    expect "pkg the backup was taken before the migration: its schema is at revision $revision_before" \
        "$(sqlite_value "${backup:-/nonexistent}" 'SELECT version_num FROM alembic_version')" "$revision_before"
    expect "pkg the backup holds the $users_before users" \
        "$(sqlite_value "${backup:-/nonexistent}" 'SELECT count(*) FROM users')" "$users_before"
    expect "pkg the backup belongs to hirdir and is its alone" \
        "$(inside stat -c '%a %U' "${backup:-/nonexistent}" 2>&1)" "600 hirdir"
    check "pkg the upgrade prints no first-install hints" \
        bash -c "! grep -q 'hirdir admin create-user' '$work/install.log'"
    check "pkg the upgrade prints no warning that a unit file changed on disk" \
        bash -c "! grep -q 'daemon-reload' '$work/install.log'"
    expect "pkg the two conffiles are as the operator left them, and dpkg left no second copy of them or of the nginx snippet" \
        "$(conffiles | sha256sum)" "$(printf '%s\n' "$conffiles_before" | sha256sum)"

    # The nginx snippet is no conffile, because hirdir-setup writes the prefix into it:
    # dpkg would have stopped this upgrade to ask about it. The package writes it again
    # as the new version ships it, keeps the prefix, and has nginx reload.
    expect "pkg the nginx snippet is the one $version ships, in all but its prefix" \
        "$(snippet_body | sha256sum)" "$(shipped_snippet "$deb" | grep -v '# prefix$' | sha256sum)"
    expect "pkg and its three prefix lines still say $prefix, as the operator had it" \
        "$(inside grep -c "$prefix.*# prefix\$" /etc/nginx/snippets/hirdir.conf 2>&1)" 3
    renewed="hirdir: /etc/nginx/snippets/hirdir.conf is now as this version of hirdir ships it, for $prefix/. nginx was reloaded."
    if [ "$(shipped_snippet "$previous" | sha256sum)" != "$(shipped_snippet "$deb" | sha256sum)" ]; then
        check "pkg the upgrade says that it wrote the snippet again, for $prefix/, and that nginx was reloaded" \
            grep -qxF "$renewed" "$work/install.log"
    else
        check "pkg $version ships the snippet $previous_version did, and the upgrade says nothing of it" \
            bash -c "! grep -q 'snippets/hirdir.conf' '$work/install.log'"
    fi
    check "pkg nginx accepts its configuration" inside nginx -t
    expect "pkg hirdir-setup --renew finds nothing left to change" "$(inside hirdir-setup --renew --yes 2>&1)" \
        "Nothing to change: /etc/nginx/snippets/hirdir.conf is as this version of hirdir ships it, for $prefix/"

    expect "pkg hirdir admin check: the migration brought the schema from $revision_before to $head" \
        "$(inside hirdir admin check 2>&1 | sed -n 's/^schema revision: *//p')" "$head (this version expects $head)"
    check "pkg hirdir admin check exits 0" inside hirdir admin check
    created=""
    for name in $(migrations tables "$revision_before"); do
        created="${created:+$created }$(sqlite_value /var/lib/hirdir/hirdir.db "SELECT name FROM sqlite_master WHERE type = 'table' AND name = '$name'")"
    done
    expect "pkg every table that the migration creates is there" "$created" "$(migrations tables "$revision_before")"
    expect "pkg hirdir.service is running again" "$(inside systemctl is-active hirdir.service 2>&1)" active
    if wait_ready; then
        pass "pkg the readiness probe answers through nginx under $prefix/, the prefix from before"
    else
        fail "pkg the readiness probe answers through nginx under $prefix/, the prefix from before (got $status)"
    fi

    token=$old_session
    api GET /auth/me
    expect "pkg the session token issued before the upgrade is still accepted" \
        "$status $(json_field username) $(json_field role)" "200 upgrade-admin admin"
    api GET /about
    expect "pkg GET $prefix/api/v1/about says version $version and schema revision $head" \
        "$status $(json_field version) $(json_field schema_revision)" "200 $version $head"

    # An import on the upgraded installation, under the prefix from before, where nobody
    # has run hirdir-setup or reloaded nginx since the upgrade: a file larger than the
    # megabyte nginx takes when it is left to itself. It is previewed and not applied,
    # so the inventory stays as it was carried over. The examples are imported below,
    # with everything else the fresh pass does.
    large_file "$work/large-upgraded.csv" "Upgrade Witness Networks" UW-48P
    send "/imports/preview?entity=items&file_name=large-upgraded.csv" "$work/large-upgraded.csv"
    expect "pkg under $prefix/, where the upgrade alone changed nginx, a file of $(megabytes "$work/large-upgraded.csv") is taken and previewed: $large_rows items to create" \
        "$status $(job_counts)" "201 [\"previewed\", $large_rows, $large_rows, 0, 0, 0]"

    if [ -n "$witness_entry" ]; then
        local weight_after=$witness_weight row_version
        if [ "$previous_version" = 0.2.0 ]; then weight_after=0.13; fi
        api GET /vendors
        expect "pkg the vendor from before is as it was" "$status $(unchanged vendors)" "200 same"
        expect "pkg and every vendor there was is marked reviewed" \
            "$(json '[len(d["items"]), sorted({v.get("review_status") for v in d["items"]})]')" '[1, ["reviewed"]]'
        api GET "/catalog-entries/$witness_entry"
        expect "pkg the catalog entry from before has its value, and its support weight to two places" \
            "$status $(json_field est_value) $(json_field support_weight)" "200 18000.00 $weight_after"
        row_version=$(json_field row_version)
        api POST "/catalog-entries/$witness_entry/retire" "{\"row_version\": $row_version}"
        api GET "/items/$witness_item"
        expect "pkg the item from before has its own support weight and inherits the value" \
            "$status $(json_field support_weight) $(json 'd["effective"]["est_value"]["value"]')" "200 1.5 18000.00"
        # Retired, so that the rest of this pass starts from lists as empty as a new
        # installation's. Nothing is ever deleted.
        row_version=$(json_field row_version)
        api POST "/items/$witness_item/retire" "{\"row_version\": $row_version}"
        expect "pkg and both can be retired with $version" "$status" 200
    fi

    api GET '/users?limit=1000'
    expect "pkg every user is as before the upgrade ($users_before)" "$(unchanged users)" same
    api GET /user-groups
    expect "pkg the user group is as before, with its member and its role" "$(unchanged groups)" same
    api GET /role-grants
    expect "pkg every role grant is as before" "$(unchanged grants)" same
    api GET "/users/$robot_hid/service-tokens"
    expect "pkg the service token is as before" "$(unchanged tokens)" same
    api GET '/audit-events?limit=1000'
    expect "pkg every audit event from before is there and unchanged ($events_before)" \
        "$(unchanged events more)" same

    token=$service_secret
    api GET /auth/me
    expect "pkg the service token from before still authenticates" \
        "$status $(json_field username) $(json_field role)" "200 upgrade-robot viewer"
    api GET /items
    expect "pkg with View-only it reads the new item list, which is empty" "$status $(json_field total)" "200 0"
    api POST /vendors '{"name": "Cisco"}'
    expect "pkg and is refused when it tries to create a vendor" "$status" 403
    sign_in upgrade-engineer "$engineer_code"
    api GET /auth/me
    expect "pkg the second user signs in with the access code from before, and holds Inventory through the group" \
        "$status $(json_field role) $(json 'd["groups"][0]["name"]')" "200 inventory Network Engineering"
    sign_in upgrade-admin "$old_admin_code"
    expect "pkg the Admin signs in with the access code from before, for the 11 hours of the kept configuration" \
        "$status $(session_hours)" "200 11.0"
    api GET '/audit-events?limit=1'
    check "pkg sign-ins after the upgrade are added to the audit trail" \
        test "$(json 'd["total"]')" -gt "$events_before"
}

# ---- install ----------------------------------------------------------------------------

install_fresh() {
    section "install"
    if apt_get install /srv/debs/hirdir-new.deb; then
        pass "S01 the package installs with apt"
    else
        fail "S01 the package installs with apt"
        tail -n 30 "$work/apt.log"
    fi
    cp "$work/apt.log" "$work/install.log"
    check "S01 the install says how to create the first Admin" \
        grep -q 'sudo hirdir admin create-user --role admin NAME' "$work/install.log"
    check "S01 the install says how to add the site" grep -q 'sudo hirdir-setup' "$work/install.log"
    check "pkg a first install takes no backup, because there is nothing to back up" \
        bash -c "! grep -q 'the database as it was' '$work/install.log'"
    expect "pkg the install wrote the nginx snippet, /etc/nginx/snippets/hirdir.conf, as the package ships it" \
        "$(inside bash -c 'cmp /etc/nginx/snippets/hirdir.conf /usr/share/hirdir/nginx/snippet.conf && stat -c "%a %U:%G" /etc/nginx/snippets/hirdir.conf' 2>&1)" \
        "644 root:root"
    check "pkg and says nothing of it, nor of nginx, which no site of it is in yet" \
        bash -c "! grep -Eq 'snippets/hirdir.conf|nginx was reloaded' '$work/install.log'"
}

installed() {
    section "installed"
    local main_pid
    expect "S01 the installed version is $version" "$(installed_version)" "$version"
    expect "S01 the hirdir command runs and says its version" "$(inside hirdir version 2>&1)" "$version"
    expect "S01 hirdir.service is enabled" "$(inside systemctl is-enabled hirdir.service 2>&1)" enabled
    expect "S01 hirdir.service is running" "$(inside systemctl is-active hirdir.service 2>&1)" active
    main_pid=$(inside systemctl show --property MainPID --value hirdir.service)
    expect "S01 the service runs as user hirdir" "$(inside ps -o user= -p "$main_pid" 2>&1)" hirdir
    expect "S01 /var/lib/hirdir belongs to hirdir, mode 0750" \
        "$(inside stat -c '%a %U:%G' /var/lib/hirdir 2>&1)" "750 hirdir:hirdir"
    # Made by the package, so that its mode does not depend on who takes the first backup.
    expect "pkg so does /var/lib/hirdir/backups, which the package makes" \
        "$(inside stat -c '%a %U:%G' /var/lib/hirdir/backups 2>&1)" "750 hirdir:hirdir"
    check "S01 the install compiled the byte-code, so nothing writes under /opt later" \
        inside bash -c 'test -d /opt/hirdir/venv/lib/python3.*/site-packages/hirdir/__pycache__'
    check "pkg the regex package's compiled module is installed and loads in the package's Python" \
        inside /opt/hirdir/venv/bin/python -c 'import regex._regex'
    expect "pkg nothing of the development tools is installed" \
        "$(inside bash -c 'ls /opt/hirdir/venv/lib/python3.*/site-packages /opt/hirdir/venv/bin | grep -Ei "^(pytest|_pytest|ruff|ty)([-.]|$)"' 2>&1)" ""
    # The command line calls the API with httpx2 from 0.3.0. httpx, which it took the
    # place of, is no longer shipped.
    check "pkg httpx2, which the command line calls the API with, is installed and loads" \
        inside /opt/hirdir/venv/bin/python -c 'import httpx2'
    expect "pkg httpx and httpcore, which httpx2 took the place of, are not installed" \
        "$(inside bash -c 'ls /opt/hirdir/venv/lib/python3.*/site-packages | grep -Ei "^(httpx|httpcore)([-.]|$)"' 2>&1)" ""
    # /etc/nginx/snippets/hirdir.conf is not among them: postinst writes it. After an
    # upgrade from a version that had it as a conffile, dpkg lists it as obsolete.
    expect "pkg dpkg knows two conffiles of hirdir: its configuration and the nginx upstream" \
        "$(inside dpkg-query -W -f "\${Conffiles}\n" hirdir 2>&1 | grep -v ' obsolete$' | awk 'NF {print $1}' | sort | xargs)" \
        "/etc/hirdir/config.toml /etc/nginx/conf.d/hirdir.conf"
}

# ---- hirdir-setup ---------------------------------------------------------------------

setup() {
    section "hirdir-setup --self-signed --prefix /hirdir"
    local before
    prefix=/hirdir
    if inside hirdir-setup --self-signed --prefix /hirdir --yes >"$work/setup.log" 2>&1; then
        pass "S01 hirdir-setup --self-signed --prefix /hirdir --yes succeeds"
    else
        fail "S01 hirdir-setup --self-signed --prefix /hirdir --yes succeeds"
        cat "$work/setup.log"
    fi
    check "S01 it says plainly that the certificate is not for production" \
        grep -q 'not for production' "$work/setup.log"
    before=$(tree_sum)
    inside hirdir-setup --self-signed --prefix /hirdir --yes >"$work/setup-again.log" 2>&1 || true
    check "S01 run a second time, it says there is nothing to change" \
        grep -q 'Nothing to change' "$work/setup-again.log"
    expect "S01 run a second time, it changes no file" "$(tree_sum | sha256sum)" "$(printf '%s\n' "$before" | sha256sum)"
    check "S01 nginx accepts its configuration" inside nginx -t
}
tree_sum() { inside bash -c 'find /etc/nginx /etc/hirdir -type f -print0 | sort -z | xargs -0 sha256sum; ls -l /etc/nginx/sites-enabled'; }

# ---- through nginx, over HTTPS, under the prefix -----------------------------------------

first_token=""
admin_code=""

through_nginx() {
    section "through nginx over HTTPS under /hirdir/ (https://127.0.0.1:$port)"
    local asset
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
    api GET /about
    expect "pkg GET /hirdir/api/v1/about says version $version and schema revision $head" \
        "$status $(json_field version) $(json_field schema_revision)" "200 $version $head"

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
}

# ---- files: import and export -----------------------------------------------------------

# The files of examples/ in the order they load in. A record names the ones it refers to.
load_order=(tags vendors catalog-entries owners items)
large_rows=150

# large_file PATH VENDOR PID: write a CSV file of items of that model which is larger
# than the megabyte nginx takes when it is left to itself. Every name in it is invented.
large_file() {
    python3 -c '
import csv, sys

path, vendor, pid, count = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
note = "One of the rows of a file that the package test sends, to see that a file of more than a megabyte passes nginx. "
with open(path, "w", encoding="utf-8", newline="") as out:
    rows = csv.writer(out)
    rows.writerow(["vendor", "pid", "serial_number", "hostname", "comments"])
    for number in range(1, count + 1):
        serial, host = f"PKG0000X{number:03d}", f"pkgtest-sw-{number:03d}"
        rows.writerow([vendor, pid, serial, host, (note * 80)[:8000]])' "$1" "$2" "$3" "$large_rows"
}

# megabytes FILE: its size, as in "1.2 MB".
megabytes() { python3 -c 'import os, sys; print(f"{os.path.getsize(sys.argv[1]) / 1048576:.1f} MB")' "$1"; }

# limit_files: write the files that the limits of a file are tried with. They are those
# of docs/interfaces.md: 20 MB and 100,000 rows. The first two files name a column that
# no record has, so hirdir refuses each at its first line, whatever its size.
limit_files() {
    python3 -c '
import sys

work = sys.argv[1]
limit = 20 * 1024 * 1024
head, line = b"no_such_column\n", b"x" * 99 + b"\n"
for name, size in (("at-the-limit.csv", limit), ("over-the-limit.csv", limit + 1)):
    with open(f"{work}/{name}", "wb") as out:
        out.write(head)
        out.write(line * ((size - len(head)) // len(line)))
        out.write(b"y" * ((size - len(head)) % len(line)))
with open(f"{work}/too-many-rows.csv", "wb") as out:
    out.write(b"label\n")
    out.writelines(b"row-%06d\n" % number for number in range(1, 100_002))' "$work"
}

# Whether the database holds items, vendors and accounts, read from the file itself with
# the Python of the package, because the service is stopped when this is asked.
inventory_left() {
    inside /opt/hirdir/venv/bin/python -c '
import sqlite3
held = sqlite3.connect("/var/lib/hirdir/hirdir.db")
count = lambda table: held.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
print("some" if count("items") else "none", "some" if count("vendors") else "none", count("users") > 0)'
}

# export_request FORMAT FILTER [COLUMN...]: the body of POST /exports for items, sorted
# by host name.
export_request() {
    python3 -c '
import json, sys

body = {"entity": "items", "format": sys.argv[1], "filter": sys.argv[2], "sort": ["hostname"]}
if sys.argv[3:]:
    body["columns"] = sys.argv[3:]
print(json.dumps(body))' "$@"
}

# The examples are imported into an inventory that does not hold them, as scenario S12
# has it, and the checks that follow this section make records of the same names by
# hand. So the database is backed up first and put back at the end, with the commands
# an operator has for it. Nothing can be deleted from an inventory.
files() {
    section "files: examples/ imported and exported through nginx under $prefix/"
    local before items_before name entity rows item_rows hid filter wanted exported limit

    expect "pkg the package ships the CSV and JSON files of examples/ in /usr/share/doc/hirdir/examples/, each as the repository has it" \
        "$(inside bash -c 'cd /usr/share/doc/hirdir/examples && sha256sum -- * | LC_ALL=C sort' 2>&1)" \
        "$(cd examples && sha256sum -- *.csv *.json | LC_ALL=C sort)"
    before=$(inside hirdir admin backup 2>/dev/null || true)
    check "pkg hirdir admin backup keeps the inventory as it is before any file is imported (${before:-no backup})" \
        inside test -s "${before:-/nonexistent}"
    api GET '/items?include_archived=true&include_drafts=true&limit=1'
    items_before=$(json_field total)

    for name in "${load_order[@]}"; do
        entity=${name//-/_}
        rows=$(table 'len(rows)' "examples/$name.csv")
        send "/imports/preview?entity=$entity&file_name=$name.csv" "examples/$name.csv"
        expect "S12 POST $prefix/api/v1/imports/preview with examples/$name.csv as its body: each of its $rows rows is to be created" \
            "$status $(job_counts)" "201 [\"previewed\", $rows, $rows, 0, 0, 0]"
        hid=$(json 'd["job"]["hid"]')
        api POST "/imports/$hid/apply"
        expect "S12 POST $prefix/api/v1/imports/{hid}/apply creates the $rows" \
            "$status $(job_counts)" "200 [\"applied\", $rows, $rows, 0, 0, 0]"
    done
    item_rows=$(table 'len(rows)' examples/items.csv)
    api GET '/items?include_archived=true&include_drafts=true&limit=1'
    expect "S12 the item list holds the $item_rows items of the examples, beside the $items_before there were" \
        "$status $(json_field total)" "200 $((items_before + item_rows))"

    for name in "${load_order[@]}"; do
        entity=${name//-/_}
        rows=$(table 'len(rows)' "examples/$name.csv")
        send "/imports/preview?entity=$entity&file_name=$name.csv" "examples/$name.csv"
        expect "S13 examples/$name.csv a second time: each of its $rows rows finds its record unchanged" \
            "$status $(job_counts)" "201 [\"previewed\", $rows, 0, 0, $rows, 0]"
        hid=$(json 'd["job"]["hid"]')
        # A JSON file names its entity in its envelope, so the URL leaves it out.
        send "/imports/preview?file_name=$name.json" "examples/$name.json" application/json
        expect "S13 and examples/$name.json, the same records as JSON: unchanged as well" \
            "$status $(job_counts)" "201 [\"previewed\", $rows, 0, 0, $rows, 0]"
    done
    api POST "/imports/$hid/apply"
    expect "S13 applied, the second import of examples/items.csv changes nothing" \
        "$status $(job_counts)" "200 [\"applied\", $item_rows, 0, 0, $item_rows, 0]"

    # A filtered export. What it must hold is read from examples/items.csv, with the
    # same filter written in Python.
    filter='lifecycle_state:eq:Prod catalog.pid:glob:C93*'
    wanted=$(table '[r["hostname"] for r in sorted(rows, key=lambda r: r["hostname"]) if r["lifecycle_state"] == "Prod" and r["pid"].startswith("C93")]' examples/items.csv)
    expect "pkg the examples hold items for that filter to find, and others for it to leave out" \
        "$(table '0 < len([r for r in rows if r["lifecycle_state"] == "Prod" and r["pid"].startswith("C93")]) < len(rows)' examples/items.csv)" true
    api POST /exports "$(export_request csv "$filter")"
    expect "S16 POST $prefix/api/v1/exports as CSV, items in Prod of a model like C93*, by host name: the rows the examples have for it" \
        "$status $(table '[r["hostname"] for r in rows]')" "200 $wanted"
    expect "S16 it comes as a CSV file to keep" \
        "$(header content-type | cut -d';' -f1) $(header content-disposition | grep -c '^attachment; filename=".*\.csv"$')" "text/csv 1"
    expect "S16 hid is its first column, and every row has an HID of its own" \
        "$(table '[head[0], len({r["hid"] for r in rows if r["hid"]}) == len(rows)]')" '["hid", true]'
    cp "$work/body" "$work/export.csv"
    exported=$(table '[r["hid"] for r in rows]' "$work/export.csv")
    authorized GET "$prefix/api/v1/items" --get --data-urlencode "filter=$filter" --data-urlencode 'sort=hostname'
    expect "S16 and they are the items that the list gives for the same filter, in the same order" \
        "$status $(json '[i["hid"] for i in d["items"]]')" "200 $exported"
    api POST /exports "$(export_request json "$filter" hostname serial_number)"
    expect "S16 the same export as JSON with two columns named: the envelope of an import, and hid first in every record" \
        "$status $(header content-type | cut -d';' -f1) $(json '[d["schema"], d["entity"], sorted({tuple(r) for r in d["records"]})]')" \
        '200 application/json ["hirdir/1", "items", [["hid", "hostname", "serial_number"]]]'
    expect "S16 with the same items in the same order" "$(json '[r["hid"] for r in d["records"]]')" "$exported"

    # The form of an export that is made to be imported back: the values the records
    # hold themselves, and each row with its HID.
    api POST /exports '{"entity": "items", "format": "csv", "own_values": true, "include_archived": true, "include_drafts": true}'
    cp "$work/body" "$work/round-trip.csv"
    rows=$(table 'len(rows)' "$work/round-trip.csv")
    check "pkg an export of every item with its own values, the archived one and the draft among them, holds the $item_rows of the examples ($rows rows)" \
        test "$rows" -ge "$item_rows"
    send "/imports/preview?entity=items&file_name=round-trip.csv" "$work/round-trip.csv"
    expect "pkg imported back as it is, every row finds its record by HID, unchanged" \
        "$status $(job_counts)" "201 [\"previewed\", $rows, 0, 0, $rows, 0]"

    # nginx refuses a body of more than a megabyte unless it is told otherwise, and the
    # snippet of the package tells it: client_max_body_size 20m.
    large_file "$work/large.csv" Cisco C9300-48P
    check "pkg a file of $large_rows items is written that is larger than 1 MB ($(megabytes "$work/large.csv"))" \
        test "$(stat -c %s "$work/large.csv")" -gt 1048576
    send "/imports/preview?entity=items&file_name=large.csv" "$work/large.csv"
    expect "pkg nginx lets it through under $prefix/, and it is previewed: $large_rows items to create" \
        "$status $(job_counts)" "201 [\"previewed\", $large_rows, $large_rows, 0, 0, 0]"
    hid=$(json 'd["job"]["hid"]')
    authorized POST "$prefix/api/v1/imports/$hid/apply" --header 'Idempotency-Key: package-test-large-import'
    expect "pkg and applied, with an Idempotency-Key" \
        "$status $(job_counts)" "200 [\"applied\", $large_rows, $large_rows, 0, 0, 0]"
    authorized POST "$prefix/api/v1/imports/$hid/apply" --header 'Idempotency-Key: package-test-large-import'
    expect "pkg sent again with the same key, the apply is answered with the first answer and marked as replayed" \
        "$status $(header idempotency-replayed) $(job_counts)" "200 true [\"applied\", $large_rows, $large_rows, 0, 0, 0]"
    authorized GET "$prefix/api/v1/items" --get --data-urlencode 'filter=hostname:glob:pkgtest-sw-*' --data-urlencode 'limit=1'
    expect "pkg and the $large_rows items are there once" "$status $(json_field total)" "200 $large_rows"

    limit_files
    limit=$((20 * 1024 * 1024))
    send '/imports/preview?entity=tags' "$work/at-the-limit.csv"
    expect "pkg a body of exactly 20 MB passes nginx and is answered by hirdir, which refuses the file for its unknown column" \
        "$status $(header content-type) $(json 'd["errors"][0]["field"]')" "422 application/problem+json column"
    send '/imports/preview?entity=tags' "$work/over-the-limit.csv"
    expect "pkg a body of 20 MB and one byte is refused by nginx: a 413 with the page of nginx, which is not a problem document and has no request ID of hirdir" \
        "$status $(header content-type) request-id:$(header x-request-id)" "413 text/html request-id:"
    expect "pkg sent straight to the service, past nginx, a body of that size is refused by hirdir itself: a 413 that is a problem document" \
        "$(past_nginx $((limit + 1)))" "413 application/problem+json"
    send '/imports/preview?entity=tags' "$work/too-many-rows.csv"
    expect "pkg a file of 100,001 rows, which nginx takes, is refused by hirdir with its own 413, and nginx passes that on as it is" \
        "$status $(header content-type) $(json_field title)" "413 application/problem+json Too large"
    check "pkg with the request ID that every answer of hirdir carries" test -n "$(header x-request-id)"

    client_commands "$filter"

    # hirdir admin reset is how a site clears test data, on the server and nowhere else.
    # Here it clears the examples, before the backup puts back what the checks need.
    local code=0
    inside hirdir admin reset --yes >"$work/reset.out" 2>&1 || code=$?
    expect "pkg hirdir admin reset refuses while the service is running, and says to stop it" \
        "$code $(grep -c 'stop it first' "$work/reset.out")" "1 1"
    check "pkg systemctl stop hirdir, to put the inventory back as it was" inside systemctl stop hirdir.service
    code=0
    inside bash -c 'echo no | hirdir admin reset' >"$work/reset.out" 2>&1 || code=$?
    expect "pkg with the service stopped it asks for the word reset, and without it changes nothing" \
        "$code $(grep -c 'nothing was changed' "$work/reset.out") $(inventory_left)" "1 1 some some True"
    code=0
    inside hirdir admin reset --yes >"$work/reset.out" 2>&1 || code=$?
    expect "pkg hirdir admin reset --yes clears the inventory and keeps the accounts" \
        "$code $(inventory_left)" "0 none none True"
    expect "pkg it took a backup first and says how to put it back" \
        "$(grep -c '^backup: /var/lib/hirdir/backups/hirdir-' "$work/reset.out") $(grep -c 'hirdir admin restore /var/lib/hirdir/backups/hirdir-' "$work/reset.out")" "1 1"
    check "pkg hirdir admin restore of the backup taken before the examples were imported" \
        inside hirdir admin restore "${before:-/nonexistent}"
    check "pkg systemctl start hirdir" inside systemctl start hirdir.service
    if wait_ready; then
        pass "pkg hirdir answers again through nginx"
    else
        fail "pkg hirdir answers again through nginx (got $status)"
    fi
    api GET '/items?include_archived=true&include_drafts=true&limit=1'
    expect "pkg and the item list is as it was before the examples, for the checks that follow" \
        "$status $(json_field total)" "200 $items_before"
    api GET /tags
    expect "pkg with no tag left of those the examples brought" "$status $(json 'len(d)')" "200 0"
}

# ---- the client commands ----------------------------------------------------------------

# hirdir import, hirdir export and hirdir items, run in the container with the hirdir
# of the package: its own Python, and the httpx2 the package carries. They are pointed
# at the service itself, past nginx, because the test site's certificate is a throwaway
# that no client should be told to trust. The examples are loaded when this runs, and
# the filtered export of files() is in $work/export.csv.
#
# What a preview that is out of date exits with, 5, is not shown here: it takes a change
# made between a preview and its apply, which tests/api/test_cli.py makes.
cli() { inside env HIRDIR_URL=http://127.0.0.1:8715 HIRDIR_TOKEN="$token" hirdir "$@"; }

# cli_run OUT ARGUMENT...: run a client command with its output in OUT and what it says in
# $work/cli.err. Sets $code to what it exited with.
cli_run() {
    local out=$1
    shift
    code=0
    cli "$@" >"$out" 2>"$work/cli.err" || code=$?
}

client_commands() {
    section "the client commands of the package: hirdir import, export and items"
    local filter=$1 code=0 hid serial
    if ! inside hirdir import --help >/dev/null 2>&1; then
        fail "S16 the hirdir of this package has no import command"
        return
    fi

    cli_run "$work/cli.csv" export items --filter "$filter" --sort hostname --format csv
    expect "S16 hirdir export items --filter '$filter' --format csv writes the very file that POST /exports gave" \
        "$code $(sha256sum <"$work/cli.csv")" "0 $(sha256sum <"$work/export.csv")"
    cli_run "$work/cli-list.csv" items list --filter "$filter" --sort hostname --format csv
    expect "S16 hirdir items list with the same filter, as csv, is that file too" \
        "$code $(sha256sum <"$work/cli-list.csv")" "0 $(sha256sum <"$work/export.csv")"
    api POST /exports "$(export_request json "$filter" hostname serial_number)"
    cli_run "$work/cli.json" export items --filter "$filter" --sort hostname \
        --columns hostname,serial_number --format json
    expect "S16 and as JSON with two columns named, what POST /exports gives for them" \
        "$code $(sha256sum <"$work/cli.json")" "0 $(sha256sum <"$work/body")"
    cli_run "$work/cli.table" items list --filter "$filter" --sort hostname --limit 1000
    expect "S16 a list on a terminal is a table with the HID first and one line for each row" \
        "$code $(head -n 1 "$work/cli.table" | cut -d' ' -f1) $(($(wc -l <"$work/cli.table") - 1))" \
        "0 HID $(table 'len(rows)' "$work/export.csv")"

    hid=$(table 'rows[0]["hid"]' "$work/export.csv")
    serial=$(table 'rows[0]["serial_number"]' "$work/export.csv")
    cli_run "$work/cli.show" items show "$serial"
    expect "pkg hirdir items show finds an item by its serial number" \
        "$code $(sed -n 's/^hid: *//p' "$work/cli.show")" "0 $hid"
    expect "pkg and shows a time in the application's zone, with the zone named" \
        "$(grep -c -E '^created_at: +[0-9-]{10} [0-9:]{8} E[SD]T$' "$work/cli.show")" 1
    cli_run /dev/null items set "$hid" comments='Checked by the package test' --add-tag critical
    api GET "/items/$hid"
    expect "pkg hirdir items set changes one item at once: its comments and a tag" \
        "$code $(json '[d["comments"], "critical" in d["tags"]]')" '0 ["Checked by the package test", true]'
    api GET "/audit-events?record_hid=$hid&limit=1"
    expect "pkg and the change is audited as made through the command line" \
        "$(json 'd["items"][0]["via"]')" cli
    cli_run /dev/null items set --filter "$filter" comments='Seen in the autumn audit'
    api GET "/items/$hid"
    expect "pkg a change to many items is a preview until --apply is given: nothing is changed" \
        "$code $(grep -c 'Nothing was changed' "$work/cli.err") $(json_field comments)" \
        "0 1 Checked by the package test"
    cli_run /dev/null items set --filter "$filter" comments='Seen in the autumn audit' --apply
    api GET "/items/$hid"
    expect "pkg and with --apply it is made" "$code $(json_field comments)" "0 Seen in the autumn audit"

    cli_run /dev/null import /usr/share/doc/hirdir/examples/tags.csv --entity tags
    expect "S13 hirdir import of the packaged examples/tags.csv previews it: every row unchanged, nothing applied" \
        "$code $(grep -c 'preview: 0 created, 0 updated, 4 unchanged, 0 rejected' "$work/cli.err")" "0 1"
    inside bash -c 'printf "label,colour\npackage-test-cli,#1f6feb\n" >/tmp/cli-tags.csv'
    cli_run /dev/null import /tmp/cli-tags.csv --entity tags --apply
    api GET /tags
    expect "S12 hirdir import --apply loads a file: the tag it holds is there" \
        "$code $(grep -c 'applied: 1 created' "$work/cli.err") $(json 'sum(t["label"] == "package-test-cli" for t in d)')" "0 1 1"
    inside bash -c 'printf "vendor,pid,serial_number,owner\nCisco,C9300-48P,PKG0000X901,Nobody At All\n" >/tmp/cli-bad.csv'
    cli_run "$work/cli.out" import /tmp/cli-bad.csv --entity items --apply
    expect "pkg a file with a rejected row exits with 4, says why, and applies nothing" \
        "$code $(grep -c 'there is no owner Nobody At All' "$work/cli.out") $(grep -c 'nothing was applied' "$work/cli.err")" "4 1 1"
    code=0
    inside env HIRDIR_URL=http://127.0.0.1:8715 HIRDIR_TOKEN=not-a-token hirdir items list >/dev/null 2>&1 || code=$?
    expect "pkg without a session the commands exit with 3" "$code" 3
}

# ---- the inventory ------------------------------------------------------------------------

items_total=0

# Every name here is invented: the host names, the serial numbers, the MAC address from
# the range reserved for documentation, the owner. Vendor and product names are real,
# as docs/requirements.md has it under "Example data".
inventory() {
    section "the inventory through nginx under /hirdir/"
    local vendor c9300 c9500 owner first second filter long

    api GET /choices
    expect "pkg the migration loaded the default choices of all three lists" \
        "$status $(json '" ".join(sorted({c["list"] for c in d}))')" "200 catalog_function catalog_type state_reason"
    expect "pkg no choice is there twice ($(json 'len(d)') choices)" \
        "$(json 'len(d) - len({(c["list"], c["value"].casefold()) for c in d})')" 0
    keep choices
    api GET /lifecycle-rules
    expect "pkg the migration loaded the rules of the nine lifecycle states, in their order" \
        "$status $(json '" ".join(r["state"] for r in d)')" \
        "200 Purchased Delivered Assigned Test Prod Down Pending-Removal Released Archived"
    keep rules

    api POST /vendors '{"name": "Cisco"}'
    expect "S06 POST /hirdir/api/v1/vendors creates a vendor" "$status" 201
    vendor=$(json_field hid)
    api POST /catalog-entries "{\"vendor_hid\": \"$vendor\", \"pid\": \"C9300-48P\", \"est_value\": \"18000.00\", \"support_weight\": \"1.0\", \"ldos\": \"2034-04-30\"}"
    expect "S06 POST /hirdir/api/v1/catalog-entries creates an entry with value, weight and LDoS" "$status" 201
    c9300=$(json_field hid)
    api POST /catalog-entries "{\"vendor_hid\": \"$vendor\", \"pid\": \"C9500-24Y4C\"}"
    expect "S06 and a second entry" "$status" 201
    c9500=$(json_field hid)
    api POST /owners '{"label": "Network Engineering"}'
    expect "S08 POST /hirdir/api/v1/owners creates an owner" "$status" 201
    owner=$(json_field hid)
    api POST /tags '{"label": "refresh-2030"}'
    expect "S11 POST /hirdir/api/v1/tags creates a tag" "$status" 201

    api POST /items "{\"catalog_entry_hid\": \"$c9300\", \"serial_number\": \"FCW0000X001\", \"hostname\": \"site2-sw-access-01\", \"mac_address\": \"00:00:5E:00:53:01\", \"owner_hid\": \"$owner\", \"lifecycle_state\": \"Delivered\", \"tags\": [\"refresh-2030\"]}"
    expect "S06 POST /hirdir/api/v1/items creates an item" "$status" 201
    first=$(json_field hid)
    api POST /items "{\"catalog_entry_hid\": \"$c9300\", \"serial_number\": \"FCW0000X002\", \"hostname\": \"site2-sw-access-02\", \"owner_hid\": \"$owner\", \"lifecycle_state\": \"Prod\", \"est_value\": \"21500.00\"}"
    expect "S06 a second item of the same model, with a value of its own" "$status" 201
    second=$(json_field hid)
    api POST /items "{\"catalog_entry_hid\": \"$c9500\", \"serial_number\": \"FCW0000X003\", \"hostname\": \"site2-sw-core-01\", \"owner_hid\": \"$owner\", \"lifecycle_state\": \"Prod\"}"
    expect "S11 a third item, of the other model" "$status" 201
    api POST /items "{\"catalog_entry_hid\": \"$c9500\", \"serial_number\": \"FCW0000X004\", \"hostname\": \"site2-sw-dist-01\", \"owner_hid\": \"$owner\", \"lifecycle_state\": \"Test\"}"
    expect "S11 and a fourth" "$status" 201
    api POST /items "{\"catalog_entry_hid\": \"$c9300\", \"serial_number\": \"FCW0000X001\"}"
    expect "S09 the same vendor, PID and serial number a second time is refused" "$status" 409

    api GET "/items/$first"
    expect "S06 the first item shows the catalog's value, with the catalog entry as its source" \
        "$status $(json 'd["est_value"]') $(json 'd["effective"]["est_value"]')" \
        "200 null {\"source\": \"catalog\", \"source_hid\": \"$c9300\", \"value\": \"18000.00\"}"
    expect "S06 and the LDoS date of the catalog entry" \
        "$(json 'd["effective"]["ldos"]["value"] + " " + d["effective"]["ldos"]["source"]')" "2034-04-30 catalog"
    expect "S08 it names its vendor, product ID and owner" \
        "$(json '[d["catalog"]["vendor"], d["catalog"]["pid"], d["owner"]["label"]]')" \
        '["Cisco", "C9300-48P", "Network Engineering"]'
    api GET "/items/$second"
    expect "S06 the second item shows its own value, with itself as the source" \
        "$status $(json 'd["effective"]["est_value"]')" \
        "200 {\"source\": \"own\", \"source_hid\": \"$second\", \"value\": \"21500.00\"}"

    filter='lifecycle_state:in:Delivered,Prod catalog.pid:glob:C93* hostname:regex:^site2-sw-(access|core)-[0-9]+$'
    authorized GET /hirdir/api/v1/items --get --data-urlencode "filter=$filter" --data-urlencode 'sort=-hostname'
    expect "S11 GET /hirdir/api/v1/items with a state list, a PID glob and a hostname regex, sorted downwards" \
        "$status $(json 'd["total"]') $(json '" ".join(i["hostname"] for i in d["items"])')" \
        "200 2 site2-sw-access-02 site2-sw-access-01"
    api POST /items/query '{"filter": {"and": [{"field": "hostname", "op": "regex", "value": "^site2-sw-(core|dist)-[0-9]+$"}, {"field": "catalog.pid", "op": "glob", "value": "C95*"}, {"field": "lifecycle_state", "op": "in", "value": ["Test", "Prod"]}]}, "sort": ["hostname"]}'
    expect "S11 POST /hirdir/api/v1/items/query with the same kind of filter as a tree, sorted upwards" \
        "$status $(json '" ".join(i["hostname"] for i in d["items"])')" "200 site2-sw-core-01 site2-sw-dist-01"
    authorized GET /hirdir/api/v1/items --get --data-urlencode 'filter=tags:has:refresh-2030'
    expect "S11 a filter by tag finds the one item that carries it" \
        "$status $(json '" ".join(i["hostname"] for i in d["items"])')" "200 site2-sw-access-01"
    # The request that docs/install.md shows under "Automation", typed as it is there.
    api GET '/items?filter=lifecycle_state:eq:Prod&sort=hostname'
    expect "S11 the request of docs/install.md, items in Prod by host name, finds its two" \
        "$status $(json '" ".join(i["hostname"] for i in d["items"])')" "200 site2-sw-access-02 site2-sw-core-01"
    long=$(printf '(a|aa)+%.0s' $(seq 40))
    authorized GET /hirdir/api/v1/items --get --data-urlencode "filter=hostname:regex:$long"
    expect "S11 a pattern of ${#long} characters is refused with 422, as a problem with the filter" \
        "$status $(json 'd["errors"][0]["field"]')" "422 filter"
    check "S11 and the message says how long a pattern may be" \
        contains "$(json 'd["errors"][0]["message"]')" "at most 200 characters"
    request GET /hirdir/api/v1/health/ready
    expect "S11 the server still answers its health probe" "$status" 200

    api POST "/items/$first/transition" '{"to": "Assigned", "reason": "received", "row_version": 1}'
    expect "S10 POST /hirdir/api/v1/items/{hid}/transition moves the first item from Delivered to Assigned" \
        "$status $(json_field lifecycle_state) $(json_field disposition)" "200 Assigned Staging"
    api POST "/items/$first/transition" "{\"to\": \"Prod\", \"reason\": \"deployed\", \"row_version\": $(json_field row_version)}"
    expect "S10 a move the rules do not list, Assigned to Prod, is refused" "$status" 422
    api GET "/items/$first/history"
    expect "S10 GET /hirdir/api/v1/items/{hid}/history holds the creation and the move, newest first, each with who" \
        "$status $(json '[[e["action"], e["actor_name"]] for e in d["items"]]')" \
        "200 [[\"transition\", \"$admin\"], [\"create\", \"$admin\"]]"
    expect "S10 the move is recorded with from, to and why" \
        "$(json 'sorted([c["field"], c["old"], c["new"]] for c in d["items"][0]["changes"] if c["field"] in ("lifecycle_state", "state_reason"))')" \
        '[["lifecycle_state", "Delivered", "Assigned"], ["state_reason", null, "received"]]'
    api GET /items
    items_total=$(json_field total)
    expect "pkg the item list holds the four items" "$status $items_total" "200 4"
}

# ---- the same version, installed again -----------------------------------------------------

reinstall() {
    section "the same version installed again (apt-get install --reinstall)"
    if apt_get install --reinstall /srv/debs/hirdir-new.deb; then
        pass "pkg apt-get install --reinstall succeeds"
    else
        fail "pkg apt-get install --reinstall succeeds"
        tail -n 30 "$work/apt.log"
    fi
    check "pkg it keeps a backup of the database first, and says where" \
        grep -q '^hirdir: the database as it was before this upgrade is kept at /var/lib/hirdir/backups/' "$work/apt.log"
    check "pkg it prints no first-install hints" bash -c "! grep -q 'hirdir admin create-user' '$work/apt.log'"
    expect "pkg dpkg holds hirdir $version as installed" \
        "$(inside dpkg-query -W -f "\${Version} \${Status}" hirdir 2>&1)" "$version install ok installed"
    if wait_ready; then
        pass "pkg the service came back"
    else
        fail "pkg the service came back (got $status)"
    fi
    api GET /choices
    expect "pkg the default choices are the same records as before: none added, none changed" \
        "$status $(unchanged choices)" "200 same"
    api GET /lifecycle-rules
    expect "pkg the lifecycle rules are the same records as before: none added, none changed" \
        "$status $(unchanged rules)" "200 same"
    api GET /items
    expect "pkg the items are still there" "$status $(json_field total)" "200 $items_total"
    expect "pkg the schema is still at revision $head" "$(revision_now)" "$head"
}

# ---- on the host: files, restart, backup ---------------------------------------------

state() {
    section "state, restart and backup"
    local name file_mode backup count
    check "S01 hirdir admin check exits 0" inside hirdir admin check
    expect "S01 every file in /var/lib/hirdir is owned by hirdir" \
        "$(inside find /var/lib/hirdir ! -user hirdir 2>&1)" ""
    for name in hirdir.db secret.key; do
        file_mode=$(inside stat -c '%a' "/var/lib/hirdir/$name" 2>&1)
        case $file_mode in
            [0-7][0-7]0) pass "S01 /var/lib/hirdir/$name is not readable by other users (mode $file_mode)" ;;
            *) fail "S01 /var/lib/hirdir/$name is not readable by other users (mode $file_mode)" ;;
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
    token=$first_token
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
}

# ---- the browser scenarios --------------------------------------------------------------

browser_scenarios() {
    section "browser scenarios (npm --prefix web run e2e)"
    local playwright browser_port
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
}

# ---- another prefix -------------------------------------------------------------------

another_prefix() {
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
}

# ---- a site of the host's own -------------------------------------------------------------

site=/etc/nginx/sites-available/package-test

own_site() {
    section "hirdir-setup on a site that already terminates TLS"
    local before
    check "pkg hirdir-setup --remove --yes succeeds" inside hirdir-setup --remove --yes
    wait_status 000 GET /inventory/api/v1/health/ready || true
    expect "pkg after --remove nothing listens on port 443" "$status" 000
    check "pkg --remove takes the self-signed site and its certificate away" inside bash -c \
        '! ls -d /etc/nginx/sites-*/hirdir-self-signed /etc/hirdir/self-signed 2>/dev/null | grep -q .'

    # What an operator has before hirdir arrives: a site with a certificate of its own.
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
    check "pkg the snippet is again as the package ships it" \
        inside cmp /etc/nginx/snippets/hirdir.conf /usr/share/hirdir/nginx/snippet.conf
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
}

# ---- purge ----------------------------------------------------------------------------

purge() {
    section "apt-get purge hirdir"
    local path
    if apt_get purge hirdir; then
        pass "S01 the package purges"
    else
        fail "S01 the package purges"
        tail -n 20 "$work/apt.log"
    fi
    for path in /opt/hirdir /var/lib/hirdir /etc/hirdir /usr/bin/hirdir /etc/nginx/snippets/hirdir.conf \
        /etc/nginx/conf.d/hirdir.conf /usr/share/hirdir /usr/share/doc/hirdir; do
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
}

# ---- the pass -----------------------------------------------------------------------------

case $mode in
    upgrade) title="upgrade from hirdir $previous_version to $version" ;;
    failed-upgrade) title="an upgrade from hirdir $previous_version to $version whose migration fails" ;;
    *) title="fresh install of hirdir $version" ;;
esac
printf '\n==== package-test, the %s pass: %s\n' "$mode" "$title"
head=$(migrations head)

start_container
if [ "$mode" = failed-upgrade ]; then
    failed_upgrade
else
    section "nginx"
    if apt_get update && apt_get install nginx; then
        pass "S01 nginx installs with apt"
    else
        fail "S01 nginx installs with apt"
        tail -n 20 "$work/apt.log"
    fi
    if [ "$mode" = upgrade ]; then
        previous_release
        upgrade
    else
        install_fresh
        if [ -z "${PACKAGE_TEST_EVERY_PASS:-}" ]; then
            skip "pkg upgrade from the previous release: --fresh asks for the fresh install alone, so no upgrade was tested by this run"
        fi
    fi
    installed
    setup
    through_nginx
    files
    inventory
    reinstall
    state
    if [ "$e2e" = 1 ]; then browser_scenarios; fi
    another_prefix
    own_site
    cookies=$(grep -ci '^set-cookie:' "$work/headers.all" || true)
    expect "S02 none of the $responses responses of this pass set a cookie" "$cookies" 0
    purge
fi

# ---- summary --------------------------------------------------------------------------

section "summary of the $mode pass"
if [ "$mode" != failed-upgrade ]; then
    echo "package-test: $(basename "$deb"), web UI in the package: $web_ui"
fi
echo "package-test: $mode: $passes PASS, $failures FAIL, $skips SKIP ($title)"
if [ "$failures" -gt 0 ]; then
    echo "package-test: $failures check(s) FAILED in the $mode pass"
    echo "--- journal of hirdir.service"
    inside journalctl --unit hirdir.service --no-pager --lines 30 2>&1 || true
    echo "--- /var/log/nginx/error.log"
    inside tail -n 20 /var/log/nginx/error.log 2>&1 || true
    exit 1
fi
echo "package-test: all checks of the $mode pass passed"
