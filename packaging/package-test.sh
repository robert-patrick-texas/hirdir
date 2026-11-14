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
#                      a service token, audit events, an inventory and a changed
#                      configuration into it, upgrade it with apt, and see that all of
#                      it is still there and still works, under the prefix it had; then
#                      everything the fresh pass does. The inventory is made for what a
#                      migration could harm: items with every kind of value between
#                      them, minor items, a stack, a cluster, a controller domain, their
#                      members, a replacement, addresses, and choices of the site's own
#   --failed-upgrade   install the previous release, with the same inventory, and make
#                      the migration of the new one fail, in the database: by a table in
#                      the way of one it creates, or, where it creates none, by a
#                      trigger that refuses the new revision once everything else is
#                      done. The upgrade must stop, name the backup and leave the
#                      inventory as it was, and the way back that its message gives
#                      must work
#   --fresh            install on a system that never had hirdir, as a new
#                      installation does, and exercise it: the examples imported and
#                      exported through nginx, minor items, a stack, a replacement and
#                      addresses made beside them, condition, observation and health,
#                      a cluster counted in its three ways, then the inventory made by
#                      hand
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
# files, S18 to S21 and S23 for minor items, stacks, a replacement and addresses. The
# others, marked pkg, are about the package alone, or about a record that has no
# scenario of its own yet, such as the condition of an item and the health of a stack.
#
# The files are sent with curl, as the API takes them. The client commands of the
# command line (hirdir import, hirdir export, hirdir items, hirdir groups and hirdir
# report) are then run in the container, from the package, by client_commands().
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
# and a JSON body when one is given. The pass that installs no nginx makes the same
# request inside the container, straight to the service: see local_api.
api() {
    local method=$1 path=$2
    shift 2
    if [ "$mode" = failed-upgrade ]; then
        local_api "$method" "$path" "$@"
    elif [ $# -gt 0 ]; then
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

# unchanged NAME [more | fields]: print "same" when every record kept under NAME is in
# the last response with the same HID and every field as it was, and no record was
# added. With "more", records may have been added. With "fields", a newer version may
# have given a record more fields, also inside a record it holds, such as the block of
# effective values, and inside each record of a list it holds, such as its addresses:
# every field that was there must still be there as it was. Otherwise print what
# differs.
unchanged() {
    python3 -c '
import json, sys

def records(path):
    document = json.load(open(path, encoding="utf-8"))
    return document["items"] if isinstance(document, dict) else document

def same(was, now):
    if sys.argv[3] == "fields" and isinstance(was, dict) and isinstance(now, dict):
        return all(key in now and same(value, now[key]) for key, value in was.items())
    if sys.argv[3] == "fields" and isinstance(was, list) and isinstance(now, list):
        return len(was) == len(now) and all(same(*pair) for pair in zip(was, now))
    return was == now

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
    changed = sorted(
        key for key, value in record.items() if key not in found or not same(value, found[key])
    )
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

# local_api METHOD PATH [JSON]: what api does, where there is no nginx: the request is
# made inside the container, straight to the service on its loopback port, by the
# Python of the package, with the token in $token. Sets $status and leaves the body in
# $work/body.
local_api() {
    inside /opt/hirdir/python/bin/python3 -I -c '
import sys, urllib.error, urllib.request

headers = {"Content-Type": "application/json"}
if sys.argv[1]:
    headers["Authorization"] = "Bearer " + sys.argv[1]
request = urllib.request.Request(
    "http://127.0.0.1:8715/api/v1" + sys.argv[3],
    data=sys.argv[4].encode() if len(sys.argv) > 4 else None,
    method=sys.argv[2],
    headers=headers,
)
try:
    answer = urllib.request.urlopen(request, timeout=20)
except urllib.error.HTTPError as error:
    answer = error
except OSError:
    sys.exit("000")
print(answer.code)
sys.stdout.write(answer.read().decode())' "$token" "$@" >"$work/answer" 2>&1 || true
    status=$(head -n 1 "$work/answer")
    tail -n +2 "$work/answer" >"$work/body"
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

# table_read TABLE QUESTION [COLUMN...]: a table of the installation, read from the
# file itself. A migration that changes a table may rebuild it on SQLite: a new one is
# made, the rows are copied over and the old one is dropped.
#   columns          each column on a line of its own: name, type, NOT NULL, primary key
#   keys             each index and each foreign key on a line: what it is over, and
#                    whether it is unique. The name SQLite itself gave to the index of a
#                    uniqueness is left out, because it is numbered anew in a rebuild.
#   rows COLUMN...   how many rows there are, and one checksum of what they hold in the
#                    columns named, which are those the first answer listed
table_read() {
    inside runuser -u hirdir -- /opt/hirdir/python/bin/python3 -I -c '
import hashlib, sqlite3, sys

held = sqlite3.connect("/var/lib/hirdir/hirdir.db")
table, question, names = sys.argv[1], sys.argv[2], sys.argv[3:]
if not all(name.replace("_", "").isalnum() for name in [table, *names]):
    sys.exit("table_read: a table and its columns are named by letters, digits and _")
if question == "columns":
    for _, name, kind, not_null, _, key in held.execute(f"PRAGMA table_info({table})"):
        print(name, kind, "NOT NULL" if not_null else "NULL", "PRIMARY KEY" if key else "-")
elif question == "keys":
    lines = []
    for _, name, unique, origin, partial in held.execute(f"PRAGMA index_list({table})").fetchall():
        over = ",".join(row[2] for row in held.execute(f"PRAGMA index_info(\"{name}\")"))
        shown = "-" if name.startswith("sqlite_autoindex_") else name
        lines.append(f"index {shown} on {over} unique={unique} origin={origin} partial={partial}")
    for row in held.execute(f"PRAGMA foreign_key_list({table})"):
        lines.append(f"foreign key {row[3]} to {row[2]}.{row[4]}")
    print("\n".join(sorted(lines)))
else:
    if not names:
        sys.exit("table_read rows: name the columns")
    rows = held.execute("SELECT " + ", ".join(names) + f" FROM {table} ORDER BY hid").fetchall()
    print(len(rows), "rows", hashlib.sha256(repr(rows).encode()).hexdigest())' "$@" 2>&1
}

# table_columns TABLE: the names of its columns, on one line.
table_columns() { table_read "$1" columns | cut -d' ' -f1 | xargs; }

# table_rows TABLE "COLUMN ...": table_read rows, for the columns that one line names.
table_rows() {
    local names
    read -ra names <<<"$2"
    table_read "$1" rows "${names[@]}"
}

# sqlite_text SQL: every value of every row of one query on the database of the
# installation, the values of a row on one line with a space between them.
sqlite_text() {
    inside runuser -u hirdir -- /opt/hirdir/python/bin/python3 -I -c '
import sqlite3, sys

for row in sqlite3.connect("/var/lib/hirdir/hirdir.db").execute(sys.argv[1]):
    print(*("-" if value is None else value for value in row))' "$1" 2>&1
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

# shipped_settings PACKAGE: the settings file a package ships. From 0.3.0 it is the text
# that hirdir-setup --settings works from, and before that it was a conffile.
shipped_settings() {
    dpkg-deb --fsys-tarfile "$1" | tar --extract --to-stdout \
        ./usr/share/hirdir/config.toml ./etc/hirdir/config.toml 2>/dev/null || true
}

# The version of hirdir that dpkg has installed, or nothing.
installed_version() { inside dpkg-query -W -f "\${Version}" hirdir 2>/dev/null || true; }

apt_get() { inside apt-get -o Dpkg::Use-Pty=0 --yes "$@" >"$work/apt.log" 2>&1; }

# What is in the one conffile of the package, and whether dpkg left a second copy of it
# beside it, or of the settings file or the nginx snippet, which were conffiles up to
# 0.2.1 and are written by the package itself since.
conffiles() {
    inside bash -c 'sha256sum /etc/nginx/conf.d/hirdir.conf;
        ls /etc/hirdir /etc/nginx/conf.d /etc/nginx/snippets | grep -E "\.dpkg-|\.ucf-" || true' 2>&1
}

# The settings file of the installation.
settings_file() { inside cat /etc/hirdir/config.toml 2>&1 || true; }

# settings_kept BEFORE: whether the settings file still holds every line of the text in
# the file BEFORE, in its place, with only more after it.
settings_kept() {
    settings_file >"$work/settings-now.toml"
    python3 -c '
import sys
before, now = (open(path, encoding="utf-8").read() for path in sys.argv[1:3])
print("kept" if now.startswith(before.rstrip("\n") + "\n") else "changed", "same" if now == before else "more")' \
        "$1" "$work/settings-now.toml"
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
    local cause cause_sql said cure cure_sql table

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
    # The inventory that the upgrade pass makes, for the migration to fail over: it has
    # changed the tables of that inventory before it comes to what is in its way.
    token=""
    api POST /auth/sign-in "$body"
    token=$(json_field token)
    witness_inventory
    witness_kept
    revision_before=$(revision_now)
    check "pkg hirdir admin check of $previous_version names its schema revision ($revision_before)" \
        test -n "$revision_before"

    # The migration is made to fail by the database, not by the package, which is
    # installed exactly as it was built. Where the new version creates a table, the
    # table it creates last is already there. Where it creates none, a trigger refuses
    # the last thing every migration does, which is to write its revision into
    # alembic_version: by then the migration has made every change it makes, to the
    # tables and to what they hold, and all of it has to be undone. A column of a name
    # the migration adds would not do: SQLite refuses it where the column is added to
    # the table as it stands, and at the first statement, with nothing to undo, and
    # where the table is rebuilt the column is taken over without a word.
    planted=$(migrations created "$revision_before")
    if [ -n "$planted" ]; then
        cause="a table named $planted, which the migration creates last, is put in its way"
        cause_sql="CREATE TABLE \"$planted\" (planted_by_package_test INTEGER)"
        said="table \"\?$planted\"\? already exists"
        cure="the table that was in the way is taken out"
        cure_sql="DROP TABLE \"$planted\""
    elif [ "$head" != "$revision_before" ]; then
        cause="no migration of $version after revision $revision_before creates a table, so a trigger is put on alembic_version that refuses the new revision: the migration fails at its last statement, with everything else it does done"
        cause_sql="CREATE TRIGGER planted_by_package_test BEFORE UPDATE ON alembic_version BEGIN SELECT RAISE(ABORT, 'refused by the trigger of the package test'); END"
        said="refused by the trigger of the package test"
        cure="the trigger that refused the revision is taken out"
        cure_sql="DROP TRIGGER planted_by_package_test"
    else
        skip "pkg a migration that fails stops the upgrade: $version has no migration after revision $revision_before, the schema of $previous_version, so there is nothing that could fail and this pass tested no failure"
        return
    fi
    if sqlite_run "$cause_sql" >/dev/null 2>&1; then
        pass "pkg $cause"
    else
        fail "pkg $cause"
    fi
    expect "pkg $previous_version is not disturbed by it: hirdir admin check exits 0, and the service answers" \
        "$(inside hirdir admin check >/dev/null 2>&1 && echo checked) $(local_status GET /api/v1/health/ready)" "checked 200"
    tables_before=$(sqlite_value "$database" "SELECT count(*) FROM sqlite_master WHERE type = 'table'")
    schema_before=$(schema_sum "$database")
    snippet_before=$(inside sha256sum /etc/nginx/snippets/hirdir.conf 2>&1)
    settings_file >"$work/settings-before-failure.toml"

    section "the upgrade to $version, whose migration fails"
    if apt_get install /srv/debs/hirdir-new.deb; then
        fail "pkg apt reports that the upgrade failed (it reported success)"
    else
        pass "pkg apt reports that the upgrade failed"
    fi
    cp "$work/apt.log" "$work/failed.log"
    check "pkg the message says that the migration failed and the service was not started" \
        grep -qxF 'hirdir: the migration failed, and the service was not started.' "$work/failed.log"
    check "pkg and what stopped it is what was put in its way, and nothing else: the error of the database is in the output" \
        grep -q "$said" "$work/failed.log"
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
    expect "pkg the failed migration was undone as a whole: the database has the tables it had, and none of the migration's" \
        "$(sqlite_value "$database" "SELECT count(*) FROM sqlite_master WHERE type = 'table'")" "$tables_before"
    expect "pkg and no table from before is changed: the schema is, statement for statement, as it was" \
        "$(schema_sum "$database")" "$schema_before"
    expect "pkg and the account is still in it" \
        "$(sqlite_value "$database" "SELECT count(*) FROM users WHERE username = 'upgrade-witness'")" 1
    for table in $witness_tables; do
        expect "pkg the $table table, which the migration had its hands on before it failed, has the columns it had and no other" \
            "$(table_read "$table" columns)" "${columns_before[$table]}"
        expect "pkg and the indexes, uniquenesses and foreign keys it had" \
            "$(table_read "$table" keys)" "${keys_before[$table]}"
        expect "pkg and its rows, each as it was (${rows_before[$table]})" \
            "$(table_rows "$table" "$(columns_then "$table")")" "${rows_before[$table]}"
    done
    expect "pkg the upgrade that stopped left the nginx snippet as $previous_version had it" \
        "$(inside sha256sum /etc/nginx/snippets/hirdir.conf 2>&1)" "$snippet_before"
    expect "pkg and the settings file as it was" \
        "$(settings_kept "$work/settings-before-failure.toml")" "kept same"

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
    witness_carried exact "with $previous_version back and the backup restored,"

    section "the upgrade again, with its cause put right"
    check "pkg $cure" sqlite_run "$cure_sql"
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
    if [ -n "$planted" ]; then
        created=""
        for name in $(migrations tables "$revision_before"); do
            created="${created:+$created }$(sqlite_value "$database" "SELECT name FROM sqlite_master WHERE type = 'table' AND name = '$name'")"
        done
        expect "pkg every table that the migration creates is there now ($(migrations tables "$revision_before"))" \
            "$created" "$(migrations tables "$revision_before")"
    else
        expect "pkg the migration creates no table: the database has the tables it had, and nothing of the trigger is left" \
            "$(sqlite_value "$database" "SELECT count(*) FROM sqlite_master WHERE type = 'table'") $(sqlite_value "$database" "SELECT count(*) FROM sqlite_master WHERE type = 'trigger'")" \
            "$tables_before 0"
    fi
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
    witness_carried fields "after the upgrade that went through,"
    for table in $witness_tables; do
        expect "pkg and every row of the $table table holds what it held, in the columns it had (${rows_before[$table]})" \
            "$(table_rows "$table" "$(columns_then "$table")")" "${rows_before[$table]}"
    done

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
    witness_carried exact "gone back to $previous_version from the good upgrade,"
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
witness_second=""
witness_owner=""
witness_item=""
witness_weight=""
witness_full=""
witness_items=()
witness_groups=()
witness_stack=""
witness_cluster=""
witness_released=""
witness_tables=""
declare -A columns_before=() keys_before=() rows_before=()
tables_then=0
counted_before=""
cluster_before=""
duplicates_before=""
users_before=0
events_before=0
conffiles_before=""

# witness_body ENTRY OWNER: the body of POST /items for an item with a value in every
# field that a caller may set. All of it is invented.
witness_body() {
    python3 -c '
import json, sys

print(json.dumps({
    "catalog_entry_hid": sys.argv[1],
    "owner_hid": sys.argv[2],
    "serial_number": "UWN0000X002",
    "asset_tag": "UW-AT-0002",
    "name": "Upgrade witness with every value",
    "hostname": "upgrade-sw-02",
    "fqdn": "upgrade-sw-02.example.net",
    "mac_address": "00:00:5E:00:53:A2",
    "description": "Made with the release before",
    "comments": "Every field of this item has a value",
    "quantity": 2,
    "lifecycle_state": "Delivered",
    "procured_on": "2026-01-12",
    "delivered_on": "2026-02-02",
    "in_service_on": "2026-03-02",
    "warranty_start": "2026-02-02",
    "warranty_end": "2029-02-01",
    "est_value": "21500.00",
    "support_weight": "1.75",
    "annual_support_cost": "1600.00",
    "end_of_sale": "2030-01-31",
    "end_of_sw_support": "2032-01-31",
    "end_of_hw_support": "2034-01-31",
    "ldos": "2035-01-31",
    "tags": ["upgrade-witness", "upgrade-spare"],
}))' "$1" "$2"
}

# witness_inventory: with the previous release, through its API, make what the
# migrations of the new one could harm. A migration that adds a column to the items
# table may rebuild that table on SQLite, so the items made here have every kind of
# value between them: serial numbers, asset tags, a MAC address, tags, overrides of what
# the catalog gives, a state reached by moves, a draft and a retired one. A previous
# release from before there was an inventory is given none, and $witness_entry stays
# empty. 0.2.0 kept support weight to three places, and every release since keeps two.
witness_inventory() {
    local vendor move made rma row_version=1

    api GET /vendors
    [ "$status" = 200 ] || return 0
    witness_weight=1.25
    if [ "$previous_version" = 0.2.0 ]; then witness_weight=0.125; fi
    api POST /vendors '{"name": "Upgrade Witness Networks"}'
    expect "pkg $previous_version holds a vendor" "$status" 201
    vendor=$(json_field hid)
    api POST /catalog-entries "{\"vendor_hid\": \"$vendor\", \"pid\": \"UW-48P\", \"est_value\": \"18000.00\", \"support_weight\": \"$witness_weight\"}"
    expect "pkg $previous_version holds a catalog entry with a value and a support weight of $witness_weight" "$status" 201
    witness_entry=$(json_field hid)
    api POST /items "{\"catalog_entry_hid\": \"$witness_entry\", \"serial_number\": \"UWN0000X001\", \"support_weight\": \"1.5\"}"
    expect "pkg and an item of it with a support weight of its own" "$status" 201
    witness_item=$(json_field hid)
    witness_items=("$witness_item")

    api POST /catalog-entries "{\"vendor_hid\": \"$vendor\", \"pid\": \"UW-24S\", \"support_weight\": \"0.5\", \"annual_support_cost\": \"900.00\"}"
    made=$status
    witness_second=$(json_field hid)
    api POST /owners '{"label": "Upgrade Witness Team", "organization": "Infrastructure Operations"}'
    made="$made $status"
    witness_owner=$(json_field hid)
    api POST /tags '{"label": "upgrade-witness", "colour": "#1f6feb"}'
    made="$made $status"
    api POST /tags '{"label": "upgrade-spare"}'
    expect "pkg a second model, an owner and two tags" "$made $status" "201 201 201 201"
    # Choices of the site's own. One is a reason for a move, and an item below is moved
    # for it. The other two are reasons for a replacement, a list that the releases up
    # to 0.3.0 offered and used for nothing, and that 0.4.0 loads with its defaults. rma
    # is one of those defaults: up to 0.3.0 the site enters it itself, and from 0.4.0
    # the site gives the one that is there a label of its own.
    api POST /choices '{"list": "state_reason", "value": "site-audit", "label": "Found at the site audit"}'
    made=$status
    api POST /choices '{"list": "replacement_reason", "value": "site-swap", "label": "Swapped at the site"}'
    made="$made $status"
    api GET '/choices?list=replacement_reason'
    rma=$(json '([c["hid"] + " " + str(c["row_version"]) for c in d if c["value"] == "rma"] or [""])[0]')
    if [ -n "$rma" ]; then
        api PATCH "/choices/${rma% *}" "{\"row_version\": ${rma#* }, \"label\": \"Returned to the maker\"}"
        expect "pkg three choices of the site's own: a reason for a move, a reason for a replacement, and a label of the site's for rma, a reason that $previous_version offers already" \
            "$made $status $(json_field label)" "201 201 200 Returned to the maker"
    else
        api POST /choices '{"list": "replacement_reason", "value": "rma", "label": "Returned to the maker"}'
        expect "pkg three choices of the site's own: a reason for a move, and two reasons for a replacement, rma among them" \
            "$made $status" "201 201 201"
    fi

    api POST /items "$(witness_body "$witness_entry" "$witness_owner")"
    expect "pkg an item with a value in every field: serial number, asset tag, MAC address, names, dates, a quantity, an owner, two tags and every override" \
        "$status" 201
    witness_full=$(json_field hid)
    witness_items+=("$witness_full")
    for move in Assigned:received Test:staged Prod:site-audit; do
        api POST "/items/$witness_full/transition" "{\"to\": \"${move%:*}\", \"reason\": \"${move#*:}\", \"row_version\": $row_version}"
        row_version=$(json_field row_version)
    done
    api PATCH "/items/$witness_full" "{\"row_version\": $row_version, \"disposition\": \"Spare\", \"expected_online\": false}"
    expect "pkg it is moved from Delivered to Prod in three moves, the last for the site's own reason, and then set aside as a spare that is offline" \
        "$status $(json '[d["lifecycle_state"], d["state_reason"], d["disposition"], d["expected_online"], d["row_version"]]')" \
        '200 ["Prod", "site-audit", "Spare", false, 5]'
    api POST /items "{\"catalog_entry_hid\": \"$witness_second\", \"serial_number\": \"UWN0000X002\", \"mac_address\": \"00-00-5e-00-53-a2\", \"lifecycle_state\": \"Purchased\"}"
    expect "pkg the same serial number under the other model, with the same MAC address, is another item" "$status" 201
    witness_items+=("$(json_field hid)")
    api POST /items '{"asset_tag": "UW-AT-0003", "name": "Upgrade witness draft", "record_status": "draft", "tags": ["upgrade-spare"]}'
    expect "pkg a draft with an asset tag, a name and a tag, and nothing else" "$status $(json_field record_status)" "201 draft"
    witness_items+=("$(json_field hid)")
    api POST /items '{"name": "upgrade-console-01"}'
    expect "pkg an item that has a name and nothing else: no model and no state" "$status $(json_field lifecycle_state)" "201 null"
    witness_items+=("$(json_field hid)")
    api POST /items "{\"catalog_entry_hid\": \"$witness_entry\", \"serial_number\": \"UWN0000X005\", \"asset_tag\": \"UW-AT-0005\", \"lifecycle_state\": \"Prod\", \"est_value\": \"100.00\"}"
    witness_items+=("$(json_field hid)")
    api POST "/items/$(json_field hid)/retire" '{"row_version": 1}'
    expect "pkg and an item that is retired" "$status $(json_field record_status)" "200 retired"

    witness_structure
}

# witness_made SERIAL MODEL [MORE]: make an item with that serial number, of the model
# with that HID, for witness_structure, with more fields of the body when given. Its
# HID is left in $made_hid and added to the items that are carried over. An item that
# was not made is counted, for one check of them all.
made_hid=""
not_made=0
witness_made() {
    api POST /items "{\"catalog_entry_hid\": \"$2\", \"serial_number\": \"$1\"${3:+, $3}}"
    if [ "$status" = 201 ]; then
        made_hid=$(json_field hid)
        witness_items+=("$made_hid")
    else
        made_hid=""
        not_made=$((not_made + 1))
    fi
}

# site_condition VALUE LABEL: put a choice of the item_condition list straight into the
# database of the previous release, as the hirdir user, with an HID made as the
# application makes one.
site_condition() {
    inside runuser -u hirdir -- /opt/hirdir/python/bin/python3 -I -c '
import sqlite3, sys, uuid
from datetime import UTC, datetime

now = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")
held = sqlite3.connect("/var/lib/hirdir/hirdir.db", timeout=10)
held.execute(
    "INSERT INTO choices (hid, list, value, value_key, label, sort, active, created_at, updated_at, row_version)"
    " VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, 1)",
    (str(uuid.uuid7()), "item_condition", sys.argv[1], sys.argv[1].casefold(), sys.argv[2], 5, now, now),
)
held.commit()' "$1" "$2"
}

# witness_structure: the records that 0.4.0 brought, made through its API for a later
# migration to carry: minor items two deep, a stack with a master, a cluster, a
# controller domain with a cluster within it, a group that is a draft, a replacement,
# a membership that was ended, networks, and addresses of items and of groups. Migration 0006 adds columns
# to items and rebuilds device_groups. A previous release from before there were groups
# is given none of this, and $witness_groups stays empty. Every name is invented, and
# the addresses are from the ranges reserved for documentation.
witness_structure() {
    local s1 s2 s3 s4 s9 module f1 f2 w1 w2 w3 a1 a2 domain wlc member mgmt dmz made day row_version
    local items_then=${#witness_items[@]}

    api GET '/device-groups?limit=1'
    [ "$status" = 200 ] || return 0

    # Minor items beneath a switch: a power supply, and an optic in a module, two deep.
    witness_made UWN0000S001 "$witness_entry" '"lifecycle_state": "Prod", "annual_support_cost": "1200.00"'
    s1=$made_hid
    witness_made UWN0000P001 "$witness_second" "\"parent_item_hid\": \"$s1\", \"position\": \"PS-A\", \"asset_tag\": \"UW-AT-0101\", \"est_value\": \"450.00\""
    made=$status
    witness_made UWN0000M001 "$witness_second" "\"parent_item_hid\": \"$s1\", \"position\": \"NM-1\""
    module=$made_hid
    made="$made $status"
    witness_made UWN0000T001 "$witness_second" "\"parent_item_hid\": \"$module\", \"position\": \"1\", \"owner_hid\": \"$witness_owner\""
    expect "pkg $previous_version holds minor items: a power supply and a module in a switch, and an optic in the module, two deep, with an owner of its own" \
        "$made $status $(json '[d["is_major"], d["depth"], d["position"]]')" '201 201 201 [false, 2, "1"]'

    # A stack of three with a master. A fourth switch joins and leaves again, and the
    # second is replaced, so the stack has had five members and has three.
    witness_made UWN0000S002 "$witness_entry" '"lifecycle_state": "Prod"'
    s2=$made_hid
    witness_made UWN0000S003 "$witness_entry" '"lifecycle_state": "Prod"'
    s3=$made_hid
    witness_made UWN0000S004 "$witness_entry" '"lifecycle_state": "Prod"'
    s4=$made_hid
    api POST /device-groups "{\"type\": \"stack\", \"name\": \"upgrade-stack\", \"hostname\": \"upgrade-stack\", \"fqdn\": \"upgrade-stack.example.net\", \"owner_hid\": \"$witness_owner\", \"tags\": [\"upgrade-witness\"], \"members\": [{\"item_hid\": \"$s1\", \"role\": \"master\", \"position\": 1}, {\"item_hid\": \"$s2\", \"role\": \"member\", \"position\": 2}, {\"item_hid\": \"$s3\", \"role\": \"member\", \"position\": 3}, {\"item_hid\": \"$s4\", \"role\": \"member\", \"position\": 4, \"joined_on\": \"2026-03-02\"}]}"
    expect "pkg a stack of four switches with a master, a host name, an owner and a tag, which shows the master's serial number" \
        "$status $(json '[d["type"], d["member_count"], d["serial_number"]]')" '201 ["stack", 4, "UWN0000S001"]'
    witness_stack=$(json_field hid)
    witness_groups=("$witness_stack")
    api GET "/device-groups/$witness_stack/members"
    member=$(json '[m["hid"] for m in d["items"] if m["position"] == 4][0]')
    api PATCH "/device-groups/$witness_stack/members/$member" '{"row_version": 1, "left_on": "2026-09-30"}'
    expect "pkg the fourth leaves again: its membership is ended, with the day it left" \
        "$status $(json '[d["joined_on"], d["left_on"]]')" '200 ["2026-03-02", "2026-09-30"]'
    api GET "/items/$s2"
    api POST "/items/$s2/replace" "{\"row_version\": $(json_field row_version), \"reason\": \"rma\", \"reference\": \"RMA-0000-041\", \"new_item\": {\"catalog_entry_hid\": \"$witness_entry\", \"serial_number\": \"UWN0000S009\", \"lifecycle_state\": \"Prod\"}}"
    expect "pkg the second is replaced, for the reason the site calls rma, by a switch that the request creates" \
        "$status $(json '[d["reason"], d["reference"], d["new_item"]["serial_number"]]')" '201 ["rma", "RMA-0000-041", "UWN0000S009"]'
    s9=$(json 'd["new_item"]["hid"]')
    day=$(json_field replaced_on)
    witness_items+=("$s9")
    api GET "/device-groups/$witness_stack/members?include_past=true"
    expect "pkg the stack has three members now and has had five: two memberships are ended, each with its day" \
        "$status $(json '[sum(1 for m in d["items"] if not m["left_on"]), sorted(m["left_on"] for m in d["items"] if m["left_on"])]')" \
        "200 [3, $(python3 -c 'import json, sys; print(json.dumps(sorted(["2026-09-30", sys.argv[1]])))' "$day")]"

    # A cluster, as 0.4.0 has it: one managed node, whatever it is.
    witness_made UWN0000F001 "$witness_second" '"lifecycle_state": "Prod"'
    f1=$made_hid
    witness_made UWN0000F002 "$witness_second" '"lifecycle_state": "Prod"'
    f2=$made_hid
    api POST /device-groups "{\"type\": \"cluster\", \"name\": \"upgrade-cluster\", \"hostname\": \"upgrade-fw\", \"members\": [{\"item_hid\": \"$f1\", \"role\": \"active\"}, {\"item_hid\": \"$f2\", \"role\": \"standby\"}]}"
    expect "pkg a cluster of two, one active and one standby" "$status $(json '[d["type"], d["member_count"]]')" '201 ["cluster", 2]'
    witness_cluster=$(json_field hid)
    witness_groups+=("$witness_cluster")

    # A controller domain: a controller by itself, a pair of controllers as a cluster
    # within it, and two endpoints, one of which has left the team's hands. 0.4.0 lets
    # a Released item stay a member, where 0.4.1 ends the membership at the move. An
    # endpoint lists its controllers, by name in 0.4.0 and with the one that is in no
    # cluster first in 0.4.1: the one by itself has the first serial number, so that
    # the list reads the same in both and is compared as it stands.
    api POST /device-groups '{"type": "controller_domain", "name": "upgrade-wireless"}'
    made=$status
    domain=$(json_field hid)
    witness_groups+=("$domain")
    witness_made UWN0000W001 "$witness_second" '"lifecycle_state": "Prod"'
    w1=$made_hid
    witness_made UWN0000W002 "$witness_second" '"lifecycle_state": "Prod"'
    w2=$made_hid
    witness_made UWN0000W003 "$witness_second" '"lifecycle_state": "Prod"'
    w3=$made_hid
    witness_made UWN0000A001 "$witness_second" '"lifecycle_state": "Prod"'
    a1=$made_hid
    witness_made UWN0000A002 "$witness_second" '"lifecycle_state": "Prod"'
    a2=$made_hid
    witness_released=$a2
    api POST /device-groups "{\"type\": \"cluster\", \"name\": \"upgrade-wlc\", \"parent_group_hid\": \"$domain\", \"members\": [{\"item_hid\": \"$w2\", \"role\": \"active\"}, {\"item_hid\": \"$w3\", \"role\": \"standby\"}]}"
    made="$made $status"
    wlc=$(json_field hid)
    witness_groups+=("$wlc")
    api POST "/device-groups/$domain/members" "{\"members\": [{\"item_hid\": \"$w1\", \"role\": \"controller\"}, {\"item_hid\": \"$a1\", \"role\": \"endpoint\"}, {\"item_hid\": \"$a2\", \"role\": \"endpoint\"}]}"
    made="$made $status"
    api GET "/items/$a1"
    expect "pkg a controller domain with a controller by itself, a cluster of two controllers within it and two endpoints: an endpoint names its three controllers" \
        "$made $(json '[c["serial_number"] for c in d["controllers"]]')" \
        '201 201 201 ["UWN0000W001", "UWN0000W002", "UWN0000W003"]'
    api POST /device-groups '{"type": "custom", "name": "upgrade-lab", "record_status": "draft", "tags": ["upgrade-spare"]}'
    expect "pkg and a group of the site's own kind that is a draft, with a tag and no member" \
        "$status $(json '[d["type"], d["record_status"], d["member_count"]]')" '201 ["custom", "draft", 0]'
    witness_groups+=("$(json_field hid)")
    expect "pkg every one of the $((${#witness_items[@]} - items_then)) items of these groups was made" "$not_made" 0
    row_version=1
    for made in Pending-Removal:decommissioned Released:disposed; do
        api POST "/items/$a2/transition" "{\"to\": \"${made%:*}\", \"reason\": \"${made#*:}\", \"row_version\": $row_version}"
        row_version=$(json_field row_version)
    done
    expect "pkg one endpoint is moved to Released, and with $previous_version it is a member of the domain still" \
        "$status $(json '[d["lifecycle_state"], [g["name"] for g in d["groups"]]]')" '200 ["Released", ["upgrade-wireless"]]'

    # Networks and addresses: of items and of groups, both families, a primary one, one
    # address under two networks, and one twice under the same.
    api POST /networks '{"label": "upgrade-mgmt"}'
    made=$status
    mgmt=$(json_field hid)
    api POST /networks '{"label": "upgrade-dmz", "kind": "vrf"}'
    made="$made $status"
    dmz=$(json_field hid)
    for member in \
        "\"item_hid\": \"$s1\", \"address\": \"192.0.2.101\", \"network_hid\": \"$mgmt\", \"is_primary\": true" \
        "\"item_hid\": \"$s1\", \"address\": \"2001:0DB8:0000:0001:0000:0000:0000:0101\", \"role\": \"loopback\"" \
        "\"item_hid\": \"$s3\", \"address\": \"192.0.2.101\", \"network_hid\": \"$mgmt\", \"role\": \"secondary\"" \
        "\"item_hid\": \"$f1\", \"address\": \"192.0.2.101\", \"network_hid\": \"$dmz\"" \
        "\"group_hid\": \"$witness_stack\", \"address\": \"192.0.2.100\", \"network_hid\": \"$mgmt\", \"is_primary\": true" \
        "\"group_hid\": \"$witness_cluster\", \"address\": \"203.0.113.50\", \"network_hid\": \"$dmz\", \"role\": \"virtual\"" \
        "\"group_hid\": \"$witness_cluster\", \"address\": \"2001:db8:0:1::50\", \"is_primary\": true"; do
        api POST /addresses "{$member}"
        made="$made $status"
    done
    expect "pkg two networks and seven addresses: of items and of groups, of both families, three of them primary, one address under two networks and twice under one of them" \
        "$made" "201 201 201 201 201 201 201 201 201"
    duplicates_before=$(duplicates 192.0.2.101)
    expect "pkg GET /reports/duplicates of $previous_version lists that pair" "$duplicates_before" '[["upgrade-mgmt", 2, 2]]'

    # 0.4.0 has no list of conditions, so no site can have entered one through it. The
    # migration leaves alone what it finds in that list all the same, and that is
    # tried with two rows written into the database: one with the value of a default,
    # under a label of the site's, and one that is the site's alone.
    api POST /choices '{"list": "item_condition", "value": "in-repair", "label": "Away for repair"}'
    if [ "$status" = 201 ]; then
        api POST /choices '{"list": "item_condition", "value": "good", "label": "Works as it should"}'
        expect "pkg two conditions of the site's own in the item_condition list, good among them" "$status" 201
    else
        expect "pkg $previous_version has no item_condition list, and refuses a choice in it" "$status" 422
        if site_condition good "Works as it should" >/dev/null 2>&1 && site_condition in-repair "Away for repair" >/dev/null 2>&1; then
            pass "pkg so two conditions are written into its database as a site's own: good, under a label of the site's, and in-repair"
        else
            fail "pkg so two conditions are written into its database as a site's own: good, under a label of the site's, and in-repair"
        fi
    fi

    # What 0.4.0 counts, to compare with what the new version counts of the same items.
    api GET /reports/summary
    counted_before=$(counted)
    api GET '/reports/summary?filter=group.name:eq:upgrade-cluster'
    cluster_before=$(counted)
    expect "pkg $previous_version counts the cluster as one managed node of two components, with the support weight and the cost of two" \
        "$status $cluster_before" '200 [2, 2, 1, 1.0, "0.00", "1800.00"]'
}

# What the totals of the last summary of 0.4.0 say, which held the money too: items,
# components, managed nodes, the support weight as a number, the estimated value and
# the annual support cost.
counted() {
    json '(lambda t: [t["items"], t["component_count"], t["managed_node_count"], float(t["support_weight"]), t["est_value"], t["annual_support_cost"]])(d["totals"])'
}

# counted_now [QUERY]: the same six, as the new version gives them: the first four in
# the summary and the money in the management report. QUERY is the query of both
# requests, with its question mark.
counted_now() {
    local first
    api GET "/reports/summary${1:-}"
    first=$(json '(lambda t: [t["items"], t["component_count"], t["managed_node_count"], float(t["support_weight"])])(d["totals"])')
    api GET "/reports/management${1:-}"
    python3 -c 'import json, sys; print(json.dumps(json.loads(sys.argv[1]) + json.loads(sys.argv[2])))' \
        "$first" "$(json '[d["totals"]["est_value"], d["totals"]["annual_support_cost"]]')"
}

# The lists that hold every item, every device group and every address there is: the
# drafts, the archived and the retired too.
every_item='/items?include_archived=true&include_drafts=true&limit=1000'
every_group='/device-groups?include_archived=true&include_drafts=true&limit=1000'
every_address='/addresses?include_archived=true&include_drafts=true&limit=1000'

# witness_kept: keep the inventory as the previous release gives it, to compare with
# later: the items, the history of each, the groups with every membership they have
# had, the networks, the addresses, the choices, and the tables of all of it as the
# database file has them.
witness_kept() {
    local hid table
    [ -n "$witness_entry" ] || return 0
    api GET "$every_item"
    keep items
    expect "pkg $previous_version lists the ${#witness_items[@]} items, the draft and the retired one among them" \
        "$status $(json_field total)" "200 ${#witness_items[@]}"
    for hid in "${witness_items[@]}"; do
        api GET "/items/$hid/history?limit=1000"
        keep "history-$hid"
    done
    api GET /choices
    keep choices-before
    witness_tables=items
    if [ "${#witness_groups[@]}" -gt 0 ]; then
        witness_tables="items item_replacements device_groups device_group_members networks addresses"
        api GET "$every_group"
        keep device-groups
        expect "pkg and the ${#witness_groups[@]} device groups, the draft among them" \
            "$status $(json_field total)" "200 ${#witness_groups[@]}"
        for hid in "${witness_groups[@]}"; do
            api GET "/device-groups/$hid/members?include_past=true&limit=1000"
            keep "members-$hid"
        done
        api GET '/networks?limit=1000'
        keep networks
        api GET "$every_address"
        keep addresses
        expect "pkg and the seven addresses" "$status $(json_field total)" "200 7"
    fi
    for table in $witness_tables; do
        columns_before[$table]=$(table_read "$table" columns)
        keys_before[$table]=$(table_read "$table" keys)
        rows_before[$table]=$(table_rows "$table" "$(table_columns "$table")")
    done
    check "pkg and its items table is read from the database file: $(printf '%s\n' "${columns_before[items]}" | wc -l) columns, $(printf '%s\n' "${keys_before[items]}" | wc -l) indexes and foreign keys, ${rows_before[items]%% *} rows" \
        test "${rows_before[items]%% *}" = "${#witness_items[@]}"
    if [ "${#witness_groups[@]}" -gt 0 ]; then
        expect "pkg and so are the tables of the replacements, the groups, their members, the networks and the addresses: their rows" \
            "${rows_before[item_replacements]%% *} ${rows_before[device_groups]%% *} ${rows_before[device_group_members]%% *} ${rows_before[networks]%% *} ${rows_before[addresses]%% *}" \
            "1 ${#witness_groups[@]} 12 2 7"
    fi
}

# witness_carried HOW WHEN: the items and the history of each, and the groups, their
# memberships, the networks and the addresses, are as witness_kept found them. HOW is
# "fields" on the new version, which may give a record more fields, and "exact" where
# the previous release serves again. WHEN begins the lines.
witness_carried() {
    local how=$1 when=$2 hid found differing=""
    [ -n "$witness_entry" ] || return 0
    api GET "$every_item"
    expect "pkg $when every item from before is as it was, field for field and at the row_version it had (${#witness_items[@]} items)" \
        "$status $(unchanged items "$how")" "200 same"
    for hid in "${witness_items[@]}"; do
        api GET "/items/$hid/history?limit=1000"
        found=$(unchanged "history-$hid" "$how")
        [ "$found" = same ] || differing="$differing$hid: $found. "
    done
    expect "pkg $when the history of each is as it was, event for event" "$differing" ""
    [ "${#witness_groups[@]}" -gt 0 ] || return 0
    api GET "$every_group"
    expect "pkg $when every device group is as it was, field for field and at the row_version it had (${#witness_groups[@]} groups)" \
        "$status $(unchanged device-groups "$how")" "200 same"
    differing=""
    for hid in "${witness_groups[@]}"; do
        api GET "/device-groups/$hid/members?include_past=true&limit=1000"
        found=$(unchanged "members-$hid" "$how")
        [ "$found" = same ] || differing="$differing$hid: $found. "
    done
    expect "pkg $when every membership of each is as it was, those that were ended too, with the day they ended" "$differing" ""
    api GET '/networks?limit=1000'
    found=$(unchanged networks "$how")
    api GET "$every_address"
    expect "pkg $when the two networks and the seven addresses are as they were" \
        "$found $status $(unchanged addresses "$how")" "same 200 same"
}

# columns_then TABLE: the names of the columns that the table had when witness_kept
# read it.
columns_then() { printf '%s\n' "${columns_before[$1]}" | cut -d' ' -f1 | xargs; }

# carried_inventory: what the upgrade to this version did with the inventory of the
# previous release, by the API and by the database file. Migration 0006 adds three
# columns and two indexes to the items table as it stands, rebuilds device_groups with
# six columns more and a foreign key, says of every cluster there is that it is managed
# as one node, and loads the item_condition list.
carried_inventory() {
    local full made table
    witness_carried fields "after the upgrade,"
    api GET "$every_item"
    expect "pkg each of them has no condition, nothing observed of it, and a health of unknown" \
        "$(json 'sorted({json.dumps([i["condition"], i["observed_status"], i["observed_at"], i["health"]["value"]]) for i in d["items"]})')" \
        '["[null, null, null, \"unknown\"]"]'
    expect "pkg the items table has every column it had, each as it was, and after them the three of this version: condition, observed_status and observed_at" \
        "$(table_read items columns)" "${columns_before[items]}
condition VARCHAR(40) NULL -
observed_status VARCHAR(12) NULL -
observed_at DATETIME NULL -"
    expect "pkg every row of it holds in those columns what it held (${rows_before[items]})" \
        "$(table_rows items "$(columns_then items)")" "${rows_before[items]}"
    expect "pkg and in the three new columns nothing" \
        "$(sqlite_value /var/lib/hirdir/hirdir.db 'SELECT count(*) FROM items WHERE condition IS NOT NULL OR observed_status IS NOT NULL OR observed_at IS NOT NULL')" 0
    expect "pkg every index, uniqueness and foreign key of the items table is there as before, and with them the indexes of condition and of observed_status" \
        "$(table_read items keys)" \
        "$(printf '%s\n' "${keys_before[items]}" 'index ix_items_condition on condition unique=0 origin=c partial=0' \
            'index ix_items_observed_status on observed_status unique=0 origin=c partial=0' | LC_ALL=C sort)"

    # The uniquenesses are tried as well as read: a duplicate must still be refused.
    api GET "/items/$witness_full"
    full="$(json '[d["catalog_entry_hid"], d["serial_number"], d["asset_tag"]]')"
    api POST /items "{\"catalog_entry_hid\": \"$witness_entry\", \"serial_number\": \"uwn0000x002\"}"
    expect "pkg the serial number is still unique within a model: a second UWN0000X002 of UW-48P, written in lower case, is refused" \
        "$full $status $(json 'd["errors"][0]["field"]')" "[\"$witness_entry\", \"UWN0000X002\", \"UW-AT-0002\"] 409 serial_number"
    api POST /items '{"asset_tag": "uw-at-0003", "name": "Upgrade witness, a second draft"}'
    expect "pkg and the asset tag among all items: a second UW-AT-0003, which the draft has, is refused" \
        "$status $(json 'd["errors"][0]["field"]')" "409 asset_tag"

    api GET /choices
    expect "pkg every choice from before is the same record, those of the site's own among them" \
        "$status $(unchanged choices-before more)" "200 same"
    [ "${#witness_groups[@]}" -gt 0 ] || return 0

    # The device_groups table is made anew by this migration, and its rows copied over.
    expect "pkg the device_groups table has every column it had, each as it was, and after them the six of this version" \
        "$(table_read device_groups columns)" "${columns_before[device_groups]}
managed_as VARCHAR(20) NULL -
expected_members INTEGER NULL -
observed_status VARCHAR(12) NULL -
observed_at DATETIME NULL -
observed_master_hid VARCHAR(36) NULL -
master_observed_at DATETIME NULL -"
    expect "pkg every row of it holds in those columns what it held (${rows_before[device_groups]})" \
        "$(table_rows device_groups "$(columns_then device_groups)")" "${rows_before[device_groups]}"
    expect "pkg of the six new columns, managed_as says one for each of the two clusters and nothing for a group of any other type, and the other five hold nothing" \
        "$(sqlite_text "SELECT type, coalesce(managed_as, '-'), count(*), count(expected_members) + count(observed_status) + count(observed_at) + count(observed_master_hid) + count(master_observed_at) FROM device_groups GROUP BY type, managed_as ORDER BY type")" \
        "cluster one 2 0
controller_domain - 1 0
custom - 1 0
stack - 1 0"
    expect "pkg every index, uniqueness and foreign key of the device_groups table is there as before, and with them the foreign key of observed_master_hid" \
        "$(table_read device_groups keys)" \
        "$(printf '%s\n' "${keys_before[device_groups]}" 'foreign key observed_master_hid to items.hid' | LC_ALL=C sort)"
    for table in item_replacements device_group_members networks addresses; do
        expect "pkg the $table table, which this migration leaves alone, has the columns, the indexes, uniquenesses and foreign keys, and the rows it had (${rows_before[$table]})" \
            "$(table_read "$table" columns | sha256sum) $(table_read "$table" keys | sha256sum) $(table_rows "$table" "$(columns_then "$table")")" \
            "$(printf '%s\n' "${columns_before[$table]}" | sha256sum) $(printf '%s\n' "${keys_before[$table]}" | sha256sum) ${rows_before[$table]}"
    done
    api POST /device-groups '{"type": "custom", "name": "UPGRADE-STACK"}'
    expect "pkg the name of a group is still unique: a second upgrade-stack, written in capitals, is refused" \
        "$status $(json 'd["errors"][0]["field"]')" "409 name"

    api GET "/device-groups/$witness_stack"
    expect "pkg the stack still shows the serial number of its master, which is the one intended: nothing is seen of a master yet" \
        "$status $(json '[d["serial_number"], d["serial_source"], d["master"]["serial_number"], d["observed_master_hid"], d["master_observed_at"], d["member_count"]]')" \
        '200 ["UWN0000S001", "intended", "UWN0000S001", null, null, 3]'
    api GET "/device-groups/$witness_cluster"
    expect "pkg the cluster is managed as one, as $previous_version counted every cluster" \
        "$status $(json_field managed_as)" "200 one"
    expect "pkg and it is counted as it was: one managed node of two components, with the money now in the management report" \
        "$(counted_now '?filter=group.name:eq:upgrade-cluster')" "$cluster_before"
    expect "pkg the whole inventory is counted as $previous_version counted it: items, components, managed nodes, support weight, value and cost ($counted_before)" \
        "$(counted_now)" "$counted_before"
    api GET "/items/$witness_released"
    expect "pkg the endpoint that $previous_version left a member of its domain while Released is a member still: the upgrade ends no membership" \
        "$status $(json '[d["lifecycle_state"], [g["name"] for g in d["groups"]]]')" '200 ["Released", ["upgrade-wireless"]]'
    expect "pkg GET /reports/duplicates lists the address that is twice under one network as it did" \
        "$(duplicates 192.0.2.101)" "$duplicates_before"

    api GET '/choices?list=item_condition'
    expect "pkg the item_condition list is loaded: its six defaults and the site's two, with good there once, under the label the site gave it" \
        "$status $(json '" ".join(sorted(c["value"] + "=" + c["label"].replace(" ", "_") for c in d))')" \
        "200 dead=Dead degraded=Degraded failed=Failed good=Works_as_it_should in-repair=Away_for_repair suspect=Suspect untested=Untested"
    api GET /choices
    expect "pkg and the replacement_reason list is as $previous_version had it: its five defaults, rma under the label the site gave it, and the reason of the site's own" \
        "$(json '" ".join(sorted(c["value"] + "=" + c["label"].replace(" ", "_") for c in d if c["list"] == "replacement_reason"))')" \
        "other=Other project=Project refresh=Refresh rma=Returned_to_the_maker site-swap=Swapped_at_the_site upgrade=Upgrade"

    # What is new can be said of what was carried over.
    api GET "/items/$witness_item"
    api PATCH "/items/$witness_item" "{\"row_version\": $(json_field row_version), \"condition\": \"in-repair\", \"observed_status\": \"present\"}"
    expect "pkg an item from before takes the condition the site entered itself, and an observation, and has a health" \
        "$status $(json '[d["condition"], d["observed_status"], d["health"]["value"]]')" '200 ["in-repair", "present", "good"]'
    api GET "/device-groups/$witness_cluster"
    api PATCH "/device-groups/$witness_cluster" "{\"row_version\": $(json_field row_version), \"managed_as\": \"members\"}"
    made=$status
    api GET '/reports/summary?filter=group.name:eq:upgrade-cluster'
    expect "pkg and the cluster from before, said to be managed by its members, is two managed nodes" \
        "$made $status $(json 'd["totals"]["managed_node_count"]')" "200 200 2"
}

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
    witness_inventory

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
    witness_kept
    # A previous release whose snippet sets no limit leaves nginx at its own, a megabyte.
    # The same file is sent again after the upgrade, when nginx must let it through.
    if ! shipped_snippet "$previous" | grep -q client_max_body_size; then
        large_file "$work/large-upgraded.csv" "Upgrade Witness Networks" UW-48P
        send "/imports/preview?entity=items&file_name=large-upgraded.csv" "$work/large-upgraded.csv"
        expect "pkg behind the nginx snippet of $previous_version a file of $(megabytes "$work/large-upgraded.csv") is refused by nginx, with its 413 page" \
            "$status $(header content-type)" "413 text/html"
    fi
    conffiles_before=$(conffiles)
    settings_file >"$work/settings-before.toml"
    tables_then=$(sqlite_value /var/lib/hirdir/hirdir.db "SELECT count(*) FROM sqlite_master WHERE type = 'table'")
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
    expect "pkg the conffile of the nginx upstream is as the operator left it, and dpkg left no second copy of it, of the settings file or of the nginx snippet" \
        "$(conffiles | sha256sum)" "$(printf '%s\n' "$conffiles_before" | sha256sum)"

    # The settings file is no conffile either, and the operator edited it. Where
    # $version has a setting that $previous_version had not, dpkg would have stopped
    # this upgrade to ask: the package puts the new setting into the file, commented
    # out at its default, and changes nothing that was there. That was so from 0.2.1 to
    # 0.3.0, which brought max_megabytes. Where the two versions ship the same
    # settings, as 0.3.0, 0.4.0 and 0.4.1 do, the file is left as it is.
    if [ "$(shipped_settings "$deb" | sha256sum)" != "$(shipped_settings "$previous" | sha256sum)" ]; then
        expect "pkg the settings file holds every line the operator had, in its place, and more after them" \
            "$(settings_kept "$work/settings-before.toml")" "kept more"
        expect "pkg the value the operator set is still set, and the new setting is there, commented out at its default" \
            "$(inside grep -cx -e 'session_hours = 11' -e '# max_megabytes = 20' -e '\[files\]' /etc/hirdir/config.toml 2>&1)" 3
        expect "pkg the file as it was is kept beside it" \
            "$(inside bash -c 'cat /etc/hirdir/config.toml.*.bak | sha256sum' 2>&1)" "$(sha256sum <"$work/settings-before.toml")"
        check "pkg the upgrade says which settings it put in, and that nothing the operator set was changed" \
            grep -q '^hirdir: /etc/hirdir/config.toml has the new settings of this version.*files.max_megabytes.*Nothing you set was changed' "$work/install.log"
    else
        expect "pkg $version ships the settings $previous_version did, and the file is as the operator left it, with no copy made beside it" \
            "$(settings_kept "$work/settings-before.toml") $(inside bash -c 'ls /etc/hirdir | grep -c "\.bak$"' 2>&1)" "kept same 0"
        check "pkg and the upgrade says nothing of the settings file" \
            bash -c "! grep -q '/etc/hirdir/config.toml' '$work/install.log'"
    fi
    expect "pkg run again, hirdir-setup --settings finds nothing to change" \
        "$(inside hirdir-setup --settings --yes 2>&1)" \
        "Nothing to change: /etc/hirdir/config.toml has every setting of this version of hirdir."

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
    if [ -n "$(migrations tables "$revision_before")" ]; then
        created=""
        for name in $(migrations tables "$revision_before"); do
            created="${created:+$created }$(sqlite_value /var/lib/hirdir/hirdir.db "SELECT name FROM sqlite_master WHERE type = 'table' AND name = '$name'")"
        done
        expect "pkg every table that the migration creates is there ($(migrations tables "$revision_before"))" \
            "$created" "$(migrations tables "$revision_before")"
    else
        expect "pkg the migration creates no table: the database has the $tables_then tables it had" \
            "$(sqlite_value /var/lib/hirdir/hirdir.db "SELECT count(*) FROM sqlite_master WHERE type = 'table'")" "$tables_then"
    fi
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
        local weight_after=$witness_weight row_version hid retired wanted place
        if [ "$previous_version" = 0.2.0 ]; then weight_after=0.13; fi
        api GET /vendors
        expect "pkg the vendor from before is as it was" "$status $(unchanged vendors)" "200 same"
        expect "pkg and every vendor there was is marked reviewed" \
            "$(json '[len(d["items"]), sorted({v.get("review_status") for v in d["items"]})]')" '[1, ["reviewed"]]'
        api GET "/catalog-entries/$witness_entry"
        expect "pkg the catalog entry from before has its value, and its support weight to two places" \
            "$status $(json_field est_value) $(json_field support_weight)" "200 18000.00 $weight_after"
        row_version=$(json_field row_version)
        api GET "/items/$witness_item"
        expect "pkg the item from before has its own support weight and inherits the value" \
            "$status $(json_field support_weight) $(json 'd["effective"]["est_value"]["value"]')" "200 1.5 18000.00"
        carried_inventory
        # Retired, so that the rest of this pass starts from lists as empty as a new
        # installation's. An item, a group and a catalog entry are never deleted; an
        # address is removed outright, and so is a network that no address is under.
        # The items are taken newest first, a minor item before the item it is in.
        api POST "/catalog-entries/$witness_entry/retire" "{\"row_version\": $row_version}"
        retired="$status:"
        wanted="200:"
        for ((place = ${#witness_items[@]} - 1; place >= 0; place--)); do
            api GET "/items/${witness_items[place]}"
            if [ "$(json_field record_status)" != retired ]; then
                api POST "/items/${witness_items[place]}/retire" "{\"row_version\": $(json_field row_version)}"
                retired="$retired $status"
                wanted="$wanted 200"
            fi
        done
        expect "pkg the catalog entry and the $((${#witness_items[@]} - 1)) items that were not retired can be retired with $version" \
            "$retired" "$wanted"
        if [ "${#witness_groups[@]}" -gt 0 ]; then
            api GET "/device-groups/$witness_stack/members?include_past=true"
            expect "pkg retiring its members ended their memberships of the stack, which has no current member now" \
                "$status $(json 'sum(1 for m in d["items"] if not m["left_on"])')" "200 0"
            retired=""
            wanted=""
            for hid in "${witness_groups[@]}"; do
                api GET "/device-groups/$hid"
                api POST "/device-groups/$hid/retire" "{\"row_version\": $(json_field row_version)}"
                retired="$retired$status "
                wanted="${wanted}200 "
            done
            api GET "$every_address"
            for hid in $(json '" ".join(a["hid"] for a in d["items"])'); do
                api DELETE "/addresses/$hid"
                retired="$retired$status "
                wanted="${wanted}204 "
            done
            api GET '/networks?limit=1000'
            for hid in $(json '" ".join(n["hid"] for n in d["items"])'); do
                api DELETE "/networks/$hid"
                retired="$retired$status "
                wanted="${wanted}204 "
            done
            api GET "$every_address"
            expect "pkg the ${#witness_groups[@]} groups are retired, and the seven addresses and then the two networks are removed, with $version" \
                "$retired$(json_field total)" "${wanted}0"
        fi
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
    expect "pkg the install wrote the settings file, /etc/hirdir/config.toml, as the package ships it: every setting commented out" \
        "$(inside bash -c 'cmp /etc/hirdir/config.toml /usr/share/hirdir/config.toml && stat -c "%a %U:%G" /etc/hirdir/config.toml && grep -c "^[^#[]" /etc/hirdir/config.toml' 2>&1)" \
        "644 root:root
0"
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
    expect "pkg dpkg knows one conffile of hirdir, the nginx upstream: the settings file and the nginx snippet are written by the package" \
        "$(inside dpkg-query -W -f "\${Conffiles}\n" hirdir 2>&1 | grep -v ' obsolete$' | awk 'NF {print $1}' | sort | xargs)" \
        "/etc/nginx/conf.d/hirdir.conf"
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

# The files of examples/ in the order they load in, which is the order of examples/README.md
# and of "Load order" in docs/interfaces.md. A record names the ones it refers to: an
# item its network, a group its items, and an address either of the two.
load_order=(tags vendors catalog-entries owners networks items device-groups device-group-members addresses)
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

# The tables that hirdir admin reset clears: the inventory, those of 0.4.0 among it, and
# what was stored about it. A test in packaging/tests/ fails when a table that a reset
# clears is not named here.
inventory_tables="tags vendors owners catalog_entries items item_replacements device_groups device_group_members networks addresses idempotency_keys import_jobs import_rows tag_links"

# Which of those tables hold a row, and whether the table of accounts does. It is read
# from the database file with the Python of the package, because the service is stopped
# when this is asked.
inventory_left() {
    inside /opt/hirdir/venv/bin/python -c '
import sqlite3, sys
held = sqlite3.connect("/var/lib/hirdir/hirdir.db")
count = lambda table: held.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
print(*(table for table in sys.argv[1].split() + ["users"] if count(table)))' "$inventory_tables" 2>&1
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
    local before items_before tags_before groups_before name entity rows item_rows hid filter wanted exported limit made

    expect "pkg the package ships the CSV and JSON files of examples/ in /usr/share/doc/hirdir/examples/, each as the repository has it" \
        "$(inside bash -c 'cd /usr/share/doc/hirdir/examples && sha256sum -- * | LC_ALL=C sort' 2>&1)" \
        "$(cd examples && sha256sum -- *.csv *.json | LC_ALL=C sort)"
    before=$(inside hirdir admin backup 2>/dev/null || true)
    check "pkg hirdir admin backup keeps the inventory as it is before any file is imported (${before:-no backup})" \
        inside test -s "${before:-/nonexistent}"
    api GET '/items?include_archived=true&include_drafts=true&limit=1'
    items_before=$(json_field total)
    api GET /tags
    tags_before=$(json 'len(d)')
    # After an upgrade, the groups of the release before are there, retired.
    api GET "${every_group/limit=1000/limit=1}"
    groups_before=$(json_field total)

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
    # What 0.4.0 added to the examples: minor items, networks, device groups with their
    # members, and addresses. Each list holds what its file holds.
    authorized GET "$prefix/api/v1/items" --get --data-urlencode 'filter=is_major:eq:false' --data-urlencode 'limit=1'
    expect "S12 the minor items of the examples are there, each beneath the item its row names as its parent" \
        "$status $(json_field total)" "200 $(table 'sum(1 for r in rows if r["parent"])' examples/items.csv)"
    api GET '/networks?limit=1'
    made="$status $(json_field total)"
    api GET '/device-groups?limit=1000'
    made="$made $status $(json_field total) $(json 'sum(g["member_count"] for g in d["items"])')"
    api GET '/addresses?limit=1'
    expect "S12 and so are the networks, the device groups with their current members, and the addresses" \
        "$made $status $(json_field total)" \
        "200 $(table 'len(rows)' examples/networks.csv) 200 $(table 'len(rows)' examples/device-groups.csv) $(table 'sum(1 for r in rows if not r["left_on"])' examples/device-group-members.csv) 200 $(table 'len(rows)' examples/addresses.csv)"

    # What the examples show of 0.4.1: a stack whose master is not the one intended, an
    # address that two routers share, a duplicate that is a mistake, and items with a
    # condition and an observed status.
    authorized GET "$prefix/api/v1/device-groups" --get --data-urlencode 'filter=member.serial_number:eq:fcw0000y001'
    expect "S19 the core stack of the examples is found by the serial number of its first switch, the master that is intended, and shows that of its second, the master that is seen, and says which it shows" \
        "$status $(json '[[g["name"], g["serial_number"], g["serial_source"], g["master"]["serial_number"], g["observed_master"]["serial_number"], g["master_as_intended"]] for g in d["items"]]')" \
        '200 [["site2-sw-core", "FCW0000Y002", "observed", "FCW0000Y001", "FCW0000Y002", false]]'
    authorized GET "$prefix/api/v1/addresses" --get --data-urlencode 'filter=address:eq:192.0.2.254'
    expect "S23 the address that the two routers of the examples share is held once, by their cluster, as a virtual address" \
        "$status $(json '[[a["group"]["name"], a["item_hid"], a["role"], a["family"]] for a in d["items"]]')" \
        '200 [["site2-rtr-wan", null, "virtual", 4]]'
    api GET '/reports/duplicates?limit=1000'
    expect "S23 so GET $prefix/api/v1/reports/duplicates lists the one address of the examples that is held twice by mistake, on two virtual machines, and no other" \
        "$status $(json '[[p["address"], p["network"], p["count"], sorted(h["name"] for h in p["holders"])] for p in d["items"]]')" \
        '200 [["198.51.100.10", null, 2, ["netconfig-01", "netmon-01"]]]'
    wanted=$(table '[sum(1 for r in rows if r["condition"] == c and r["lifecycle_state"] != "Archived" and r["record_status"] == "active") for c in ("good", "degraded", "suspect", "failed", "untested")]' examples/items.csv)
    made=""
    for name in good degraded suspect failed untested; do
        api GET "/items?filter=condition:eq:$name&limit=1"
        made="${made:+$made, }$(json_field total)"
    done
    expect "pkg the item list finds the items of the examples by their condition: good, degraded, suspect, failed and untested, as many of each as examples/items.csv has" \
        "[$made]" "$wanted"
    api GET '/items?filter=hostname:eq:site2-rtr-wan-02'
    expect "pkg a router of the examples that is Down, not expected online and observed unreachable has a health of degraded, not failed, and says why" \
        "$status $(json '[[i["lifecycle_state"], i["expected_online"], i["condition"], i["observed_status"], i["health"]] for i in d["items"]]')" \
        '200 [["Down", false, "good", "unreachable", {"reasons": ["it is observed unreachable"], "value": "degraded"}]]'
    api GET '/device-groups?filter=name:eq:site2-sw-floor'
    expect "pkg the floor stack of the examples, which is to have three members and has two, one of them degraded, is degraded and says both" \
        "$status $(json '[[g["expected_members"], g["member_count"], g["health"]["value"], len(g["health"]["reasons"])] for g in d["items"]]')" \
        '200 [[3, 2, "degraded", 2]]'
    api GET '/reports/summary?by=condition'
    expect "pkg GET $prefix/api/v1/reports/summary holds no money: no est_value and no annual_support_cost, in its totals or in a row" \
        "$status $(json 'sorted({k for record in [d["totals"], *d["rows"]] for k in record if k in ("est_value", "annual_support_cost")})')" "200 []"
    expect "pkg it counts every component once by health: good, degraded, failed and unknown add up to the component count" \
        "$(json 'sum(d["totals"]["by_health"].values()) - d["totals"]["component_count"]')" 0
    expect "pkg and by condition: the components of each condition in its totals are those of the row of that condition when the summary is asked for by condition" \
        "$(json 'sorted([c["key"] or "", c["component_count"]] for c in d["totals"]["by_condition"])')" \
        "$(json 'sorted([r["key"] or "", r["component_count"]] for r in d["rows"])')"
    api GET '/reports/management'
    expect "pkg GET $prefix/api/v1/reports/management holds the money, and neither condition nor health: items, components, estimated value and annual support cost" \
        "$status $(json 'sorted(d["totals"])')" '200 ["annual_support_cost", "component_count", "est_value", "items"]'
    api GET '/reports/management?by=health'
    expect "pkg and is not to be had by health" "$status $(json 'd["errors"][0]["field"]')" "422 query.by"

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
        api POST "/imports/$hid/apply"
        expect "S13 applied, the second import of examples/$name.csv changes nothing" \
            "$status $(job_counts)" "200 [\"applied\", $rows, 0, 0, $rows, 0]"
    done

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
    structure
    health_and_counting
    first_file

    # hirdir admin reset is how a site clears test data, on the server and nowhere else.
    # Here it clears the examples and what structure() made beside them, a replacement
    # among it, before the backup puts back what the checks need.
    local code=0
    inside hirdir admin reset --yes >"$work/reset.out" 2>&1 || code=$?
    expect "pkg hirdir admin reset refuses while the service is running, and says to stop it" \
        "$code $(grep -c 'stop it first' "$work/reset.out")" "1 1"
    check "pkg systemctl stop hirdir, to put the inventory back as it was" inside systemctl stop hirdir.service
    code=0
    inside bash -c 'echo no | hirdir admin reset' >"$work/reset.out" 2>&1 || code=$?
    expect "pkg with the service stopped it asks for the word reset, and without it changes nothing: every table that a reset clears holds rows, the replacements, groups, members, networks and addresses of 0.4.0 too" \
        "$code $(grep -c 'nothing was changed' "$work/reset.out") $(inventory_left)" "1 1 $inventory_tables users"
    code=0
    inside hirdir admin reset --yes >"$work/reset.out" 2>&1 || code=$?
    expect "pkg hirdir admin reset --yes clears the inventory, every one of those tables, and keeps the accounts" \
        "$code $(inventory_left)" "0 users"
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
    expect "pkg with no tag left of those the examples brought" "$status $(json 'len(d)')" "200 $tags_before"
    api GET "${every_group/limit=1000/limit=1}"
    made=$(json_field total)
    api GET "${every_address/limit=1000/limit=1}"
    expect "pkg and no device group and no address but those there were before" "$status $made $(json_field total)" "200 $groups_before 0"
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
    section "the client commands of the package: hirdir import, export, items, groups and report"
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

    # What 0.4.0 added to the command line and 0.4.1 changed, on the examples: a stack
    # with the master that is intended and the one that is seen, a minor item, the
    # summary without money, the management report, and the one duplicate address.
    cli_run "$work/cli.group" groups show site2-sw-core
    expect "S19 hirdir groups show names a stack of the examples, with its type, its members, and the serial number of the master that is observed" \
        "$code $(sed -n 's/^type: *//p' "$work/cli.group") $(sed -n 's/^serial_number: *//p' "$work/cli.group") $(sed -n 's/^members: *//p' "$work/cli.group") $(grep -c -E '^[12] +(master|member) ' "$work/cli.group")" \
        "0 stack FCW0000Y002 (of the master that is observed) 2 2"
    expect "S19 and both masters: the one intended, and the one seen, with when it was seen in the application's zone, and that it is not the one intended" \
        "$(sed -n 's/^intended_master: *//p' "$work/cli.group") | $(sed -n 's/^observed_master: *//p' "$work/cli.group" | sed -E 's/[0-9-]{10} [0-9:]{8} E[SD]T/WHEN/')" \
        "site2-sw-core-01 | site2-sw-core-02, seen WHEN (not the one intended)"
    expect "pkg and the health of the stack, with its reason" \
        "$(sed -n 's/^health: *//p' "$work/cli.group")" "good: it is observed online"
    cli_run "$work/cli-groups.csv" groups list --format csv
    api POST /exports '{"entity": "device_groups", "format": "csv"}'
    expect "pkg hirdir groups list, as csv, is the file that POST /exports gives for device groups" \
        "$code $(sha256sum <"$work/cli-groups.csv")" "0 $(sha256sum <"$work/body")"
    cli_run "$work/cli.minor" items show LIT0000X001
    expect "S18 hirdir items show says what a minor item has from the item it is in, and where it is" \
        "$code $(grep -c -E '^lifecycle_state: +Prod \(parent_item\)$' "$work/cli.minor") $(sed -n 's/^position: *//p' "$work/cli.minor")" \
        "0 1 PS-A"
    api GET '/reports/summary?by=owner'
    local wanted
    wanted=$(json '[d["totals"]["component_count"], d["totals"]["managed_node_count"], len(d["rows"])]')
    cli_run "$work/cli-summary.json" report summary --by owner --format json
    cp "$work/cli-summary.json" "$work/body"
    expect "S20 hirdir report summary --by owner, as json, counts what GET /reports/summary counts" \
        "$code $(json '[d["totals"]["component_count"], d["totals"]["managed_node_count"], len(d["rows"])]')" "0 $wanted"
    cli_run "$work/cli.summary" report summary --by owner
    expect "pkg and on a terminal it is a table with a line for each owner and one for all: the counts, the support weight and the health, and no money" \
        "$code $(head -n 1 "$work/cli.summary" | xargs) $(grep -c '^(all) ' "$work/cli.summary")" \
        "0 OWNER ITEMS COMPONENT_COUNT MANAGED_NODE_COUNT SUPPORT_WEIGHT GOOD DEGRADED FAILED UNKNOWN 1"
    api GET '/reports/summary?by=health'
    wanted=$(json '[[r["key"], r["component_count"]] for r in d["rows"]]')
    cli_run "$work/cli-summary.json" report summary --by health --format json
    cp "$work/cli-summary.json" "$work/body"
    expect "pkg hirdir report summary --by health, as json, has the rows that GET /reports/summary has by health" \
        "$code $(json '[[r["key"], r["component_count"]] for r in d["rows"]]')" "0 $wanted"
    api GET '/reports/management?by=owner'
    wanted=$(json 'd')
    cli_run "$work/cli-management.json" report management --by owner --format json
    cp "$work/cli-management.json" "$work/body"
    expect "pkg hirdir report management --by owner, as json, is what GET /reports/management gives: the value and the cost of each owner's items" \
        "$code $(json 'd')" "0 $wanted"
    cli_run "$work/cli.management" report management --by owner
    expect "pkg and on a terminal it is a table with a line for each owner and one for all: the counts and the money, and no health" \
        "$code $(head -n 1 "$work/cli.management" | xargs) $(grep -c '^(all) ' "$work/cli.management")" \
        "0 OWNER ITEMS COMPONENT_COUNT EST_VALUE ANNUAL_SUPPORT_COST 1"
    cli_run "$work/cli.duplicates" report duplicates
    expect "S23 hirdir report duplicates lists the address that two virtual machines of the examples hold by mistake, once for each, and not the one that two routers share through their cluster" \
        "$code $(grep -c '^198\.51\.100\.10 ' "$work/cli.duplicates") $(grep -c '^192\.0\.2\.254 ' "$work/cli.duplicates")" "0 2 0"
}

# ---- minor items, groups, a replacement and addresses ---------------------------------------

# summary FILTER: GET /reports/summary for the items a filter finds, under $prefix.
summary() {
    authorized GET "$prefix/api/v1/reports/summary" --get --data-urlencode "filter=$1"
}

# management FILTER: GET /reports/management for the items a filter finds, under $prefix.
management() {
    authorized GET "$prefix/api/v1/reports/management" --get --data-urlencode "filter=$1"
}

# What the totals of the last summary say: items, components, managed nodes, and the
# support weight as a number.
totals() {
    json '(lambda t: [t["items"], t["component_count"], t["managed_node_count"], float(t["support_weight"])])(d["totals"])'
}

# What the totals of the last management report say: items, components, the estimated
# value and the annual support cost.
money() {
    json '(lambda t: [t["items"], t["component_count"], t["est_value"], t["annual_support_cost"]])(d["totals"])'
}

# duplicates ADDRESS: what GET /reports/duplicates lists for one address: for each
# network it is held more than once under, how often, and how many holders are named.
duplicates() {
    api GET '/reports/duplicates?limit=1000'
    json '[[p["network"], p["count"], len(p["holders"])] for p in d["items"] if p["address"] == "'"$1"'"]'
}

# The records that 0.4.0 added, made through nginx under the prefix: scenarios S18 to
# S21 and S23 of docs/build-plan.md, each in small. files() runs this while the examples
# are loaded, so everything here is told from them by its name, and the counts are
# those of these records alone. Every name is invented, the models too, and the
# addresses are from the ranges reserved for documentation. What is made here stays,
# for hirdir admin reset to clear with the examples.
structure() {
    section "minor items, a stack, a replacement and addresses through nginx under $prefix/"
    local vendor switch_model supply_model owner chassis supply items_then components_then
    local number members="" switches=() stack third old new day red black entity rows made

    api GET /settings
    expect "pkg the stack discount of the installation is the default of 50" \
        "$status $(json '[s["value"] for s in d if s["key"] == "stack_discount_pct"]')" "200 [50]"
    api POST /vendors '{"name": "Package Test Networks"}'
    made=$status
    vendor=$(json_field hid)
    api POST /catalog-entries "{\"vendor_hid\": \"$vendor\", \"pid\": \"PT-48P\", \"type\": \"switch\", \"support_weight\": \"1.0\", \"annual_support_cost\": \"1450.00\"}"
    made="$made $status"
    switch_model=$(json_field hid)
    api POST /catalog-entries "{\"vendor_hid\": \"$vendor\", \"pid\": \"PT-PWR-715\", \"type\": \"power-supply\"}"
    made="$made $status"
    supply_model=$(json_field hid)
    api POST /owners '{"label": "Package Test Team"}'
    owner=$(json_field hid)
    expect "pkg a vendor, a model of switch with a support weight of 1.0, a model of power supply and an owner are made" \
        "$made $status" "201 201 201 201"

    # S18: a minor item has the owner and the standing of the item it is in.
    api GET /reports/summary
    items_then=$(json 'd["totals"]["items"]')
    components_then=$(json 'd["totals"]["component_count"]')
    api POST /items "{\"catalog_entry_hid\": \"$switch_model\", \"serial_number\": \"PKG0000C001\", \"hostname\": \"pkgtest-chassis-01\", \"owner_hid\": \"$owner\", \"lifecycle_state\": \"Assigned\"}"
    chassis=$(json_field hid)
    api POST /items "{\"catalog_entry_hid\": \"$supply_model\", \"serial_number\": \"PKG0000P001\", \"parent_item_hid\": \"$chassis\", \"position\": \"PS-A\"}"
    expect "S18 POST $prefix/api/v1/items with parent_item_hid makes a minor item, one level beneath its switch, with no owner and no state of its own" \
        "$status $(json '[d["is_major"], d["depth"], d["position"], d["owner_hid"], d["lifecycle_state"]]')" \
        '201 [false, 1, "PS-A", null, null]'
    supply=$(json_field hid)
    expect "S18 it shows the owner of its switch, with the source parent_item and the switch as the record it comes from" \
        "$(json 'd["effective"]["owner_hid"]')" \
        "{\"label\": \"Package Test Team\", \"source\": \"parent_item\", \"source_hid\": \"$chassis\", \"value\": \"$owner\"}"
    expect "S18 and the state of its switch, Assigned, in the same way" \
        "$(json 'd["effective"]["lifecycle_state"]')" \
        "{\"source\": \"parent_item\", \"source_hid\": \"$chassis\", \"value\": \"Assigned\"}"
    api GET /reports/summary
    expect "S18 GET $prefix/api/v1/reports/summary counts two items more and one component more: a minor item is no component" \
        "$status $(json 'd["totals"]["items"]') $(json 'd["totals"]["component_count"]')" \
        "200 $((items_then + 2)) $((components_then + 1))"
    api POST "/items/$chassis/transition" '{"to": "Test", "reason": "staged", "row_version": 1}'
    made=$status
    api GET "/items/$chassis/children"
    expect "S18 the switch is moved to Test: GET $prefix/api/v1/items/{hid}/children shows its minor item in Test, from its parent, and nothing was written to it" \
        "$made $status $(json '[[c["hid"], c["effective"]["lifecycle_state"]["value"], c["effective"]["lifecycle_state"]["source"], c["lifecycle_state"], c["row_version"]] for c in d["items"]]')" \
        "200 200 [[\"$supply\", \"Test\", \"parent_item\", null, 1]]"

    # S19: a stack reads its serial number from its master.
    for number in 1 2 3 4; do
        api POST /items "{\"catalog_entry_hid\": \"$switch_model\", \"serial_number\": \"PKG0000S00$number\", \"hostname\": \"pkgtest-stack-0$number\", \"lifecycle_state\": \"Prod\"}"
        switches+=("$(json_field hid)")
        if [ "$number" = 1 ]; then made=master; else made=member; fi
        members="$members${members:+, }{\"item_hid\": \"$(json_field hid)\", \"role\": \"$made\", \"position\": $number}"
    done
    summary "hid:eq:${switches[0]}"
    expect "S20 the summary of one of the four switches while it stands alone: one component, one managed node and a support weight of 1.0" \
        "$status $(totals)" '200 [1, 1, 1, 1.0]'
    management "hid:eq:${switches[0]}"
    expect "S20 and the management report of it: its annual support cost, and no estimated value, because its model has none" \
        "$status $(money)" '200 [1, 1, "0.00", "1450.00"]'
    api POST /device-groups "{\"type\": \"stack\", \"name\": \"pkgtest-stack\", \"hostname\": \"pkgtest-stack\", \"members\": [$members]}"
    expect "S19 POST $prefix/api/v1/device-groups makes a stack of four switches with its members, one of them the master, and shows the master's serial number" \
        "$status $(json '[d["type"], d["member_count"], d["serial_number"]]')" '201 ["stack", 4, "PKG0000S001"]'
    stack=$(json_field hid)
    api GET "/device-groups/$stack/members"
    expect "S19 GET $prefix/api/v1/device-groups/{hid}/members lists the four by position, the master first" \
        "$status $(json '[[m["position"], m["role"]] for m in d["items"]]')" \
        '200 [[1, "master"], [2, "member"], [3, "member"], [4, "member"]]'
    third=$(json 'd["items"][2]["hid"]')
    api PATCH "/device-groups/$stack/members/$third" "{\"row_version\": $(json 'd["items"][2]["row_version"]'), \"role\": \"master\"}"
    made=$status
    api GET "/device-groups/$stack"
    expect "S19 the third member is made master, and the stack shows its serial number at once" \
        "$made $status $(json_field serial_number)" "200 200 PKG0000S003"
    api GET "/device-groups/$stack/members"
    expect "S19 and the former master is a member, by the same change: there is one master" \
        "$status $(json '[[m["position"], m["role"]] for m in d["items"]]')" \
        '200 [[1, "member"], [2, "member"], [3, "master"], [4, "member"]]'
    # The master that is intended and the one that is seen are two facts. The stack
    # reads its serial number from the one seen, when one is recorded, and says which.
    api GET "/device-groups/$stack"
    expect "S19 nothing is seen of a master yet: the serial number is that of the master intended, and the stack says so" \
        "$status $(json '[d["serial_number"], d["serial_source"], d["observed_master_hid"], d["master_as_intended"]]')" \
        '200 ["PKG0000S003", "intended", null, null]'
    api PATCH "/device-groups/$stack" "{\"row_version\": $(json_field row_version), \"observed_master_hid\": \"${switches[1]}\"}"
    expect "S19 the second switch is seen to be master: the stack shows its serial number, says that it is the observed one and when it was seen, and that it is not the master intended, who stays as it was" \
        "$status $(json '[d["serial_number"], d["serial_source"], d["observed_master"]["serial_number"], d["master"]["serial_number"], d["master_as_intended"], d["master_observed_at"] is not None]')" \
        '200 ["PKG0000S002", "observed", "PKG0000S002", "PKG0000S003", false, true]'
    authorized GET "$prefix/api/v1/device-groups" --get --data-urlencode 'filter=member.serial_number:eq:pkg0000s004'
    expect "S19 GET $prefix/api/v1/device-groups finds the stack by the serial number of any member, the fourth here, which is neither master" \
        "$status $(json '[g["hid"] for g in d["items"]]')" "200 [\"$stack\"]"
    api GET "/device-groups/$stack"
    api PATCH "/device-groups/$stack" "{\"row_version\": $(json_field row_version), \"observed_master_hid\": \"$chassis\"}"
    made="$status $(json 'd["errors"][0]["field"]')"
    api GET "/device-groups/$stack"
    api PATCH "/device-groups/$stack" "{\"row_version\": $(json_field row_version), \"observed_master_hid\": null}"
    expect "S19 a switch that is no member is refused as the master seen; and with the observation taken back, the stack shows the serial number of the master intended again" \
        "$made $status $(json '[d["serial_number"], d["serial_source"], d["master_observed_at"]]')" \
        '422 observed_master_hid 200 ["PKG0000S003", "intended", null]'

    # S20: the stack discount lowers the support weight and never the cost.
    summary 'group.name:eq:pkgtest-stack'
    expect "S20 the summary of the stack: four components, one managed node, and a support weight of 2.0 at the discount of 50" \
        "$status $(totals)" '200 [4, 4, 1, 2.0]'
    management 'group.name:eq:pkgtest-stack'
    expect "S20 the management report of the stack: the cost of four switches, which no discount lowers" \
        "$status $(money)" '200 [4, 4, "0.00", "5800.00"]'
    api GET "/catalog-entries/$switch_model"
    api PATCH "/catalog-entries/$switch_model" "{\"row_version\": $(json_field row_version), \"stack_discount_pct\": \"30\"}"
    made=$status
    summary 'group.name:eq:pkgtest-stack'
    expect "S20 with a discount of 30 set on the model the weight is 2.8, and the counts are as they were" \
        "$made $status $(totals)" '200 200 [4, 4, 1, 2.8]'
    management 'group.name:eq:pkgtest-stack'
    expect "S20 and so is the cost" "$status $(money)" '200 [4, 4, "0.00", "5800.00"]'

    # S21: the master is replaced, and the stack is the same record.
    old=${switches[2]}
    api GET "/items/$old"
    api POST "/items/$old/replace" "{\"row_version\": $(json_field row_version), \"reason\": \"rma\", \"reference\": \"RMA-0000-001\", \"new_item\": {\"catalog_entry_hid\": \"$switch_model\", \"serial_number\": \"PKG0000S009\"}}"
    expect "S21 POST $prefix/api/v1/items/{hid}/replace replaces the master for an RMA, with a switch that the request creates" \
        "$status $(json '[d["reason"], d["reference"], d["new_item"]["serial_number"]]')" '201 ["rma", "RMA-0000-001", "PKG0000S009"]'
    new=$(json 'd["new_item"]["hid"]')
    day=$(json_field replaced_on)
    api GET "/items/$old"
    made="$(json 'd["replaced_by"]["item_hid"]') $(json 'd["groups"]')"
    api GET "/items/$new"
    expect "S21 two item records, linked by the replacement: the old one is in no group now, and the new one is in the stack" \
        "$made $(json 'd["replaces"]["item_hid"]') $(json '[g["group_hid"] for g in d["groups"]]')" "$new [] $old [\"$stack\"]"
    api GET "/device-groups/$stack/members?include_past=true"
    expect "S21 the membership of the switch that left has an end date, the day of the replacement, and the new switch has its place from that day: master, at position 3" \
        "$status $(json '[[m["role"], m["position"], m["joined_on"], m["left_on"]] for m in d["items"] if m["item_hid"] == "'"$new"'"] + [m["left_on"] for m in d["items"] if m["item_hid"] == "'"$old"'"]')" \
        "200 [[\"master\", 3, \"$day\", null], \"$day\"]"
    api GET "/device-groups/$stack"
    expect "S21 the stack is the same record, with four members, and reads its serial number from the new master" \
        "$status $(json '[d["hid"], d["member_count"], d["serial_number"]]')" "200 [\"$stack\", 4, \"PKG0000S009\"]"

    # S23: one address under two networks is two addresses; twice under one is reported.
    api POST /networks '{"label": "pkgtest-red", "kind": "vrf"}'
    made=$status
    red=$(json_field hid)
    api POST /networks '{"label": "pkgtest-black", "kind": "vrf"}'
    made="$made $status"
    black=$(json_field hid)
    api POST /addresses "{\"item_hid\": \"${switches[0]}\", \"address\": \"203.0.113.210\", \"network_hid\": \"$red\"}"
    made="$made $status"
    api POST /addresses "{\"item_hid\": \"${switches[0]}\", \"address\": \"203.0.113.210\", \"network_hid\": \"$black\"}"
    expect "S23 POST $prefix/api/v1/networks and $prefix/api/v1/addresses: 203.0.113.210 under two networks is accepted, and GET $prefix/api/v1/reports/duplicates does not list it" \
        "$made $status $(duplicates 203.0.113.210)" "201 201 201 201 []"
    api POST /addresses "{\"item_hid\": \"${switches[1]}\", \"address\": \"203.0.113.210\", \"network_hid\": \"$red\"}"
    expect "S23 the same address a second time under one of them, on another switch, is accepted too, and the report lists that pair and no other" \
        "$status $(duplicates 203.0.113.210)" '201 [["pkgtest-red", 2, 2]]'
    authorized GET "$prefix/api/v1/addresses" --get --data-urlencode 'filter=address:eq:203.0.113.210'
    expect "S23 GET $prefix/api/v1/addresses finds the three by the address" "$status $(json_field total)" "200 3"
    api POST /addresses "{\"group_hid\": \"$stack\", \"address\": \"2001:0DB8:0000:0000:0000:0000:0000:0010\", \"is_primary\": true}"
    expect "pkg an IPv6 address of the stack itself, written out in full, is kept in its short form, as the primary management address" \
        "$status $(json '[d["address"], d["role"], d["is_primary"], d["network_hid"]]')" '201 ["2001:db8::10", "management", true, null]'

    # Every record of the new kinds, the examples' and these, exported and imported back.
    for entity in networks device_groups device_group_members addresses; do
        api POST /exports "{\"entity\": \"$entity\", \"format\": \"csv\", \"own_values\": true, \"include_archived\": true, \"include_drafts\": true}"
        cp "$work/body" "$work/back-$entity.csv"
        rows=$(table 'len(rows)' "$work/back-$entity.csv")
        send "/imports/preview?entity=$entity&file_name=$entity.csv" "$work/back-$entity.csv"
        made="$status $(job_counts)"
        api POST /exports "{\"entity\": \"$entity\", \"format\": \"json\", \"own_values\": true, \"include_archived\": true, \"include_drafts\": true}"
        cp "$work/body" "$work/back-$entity.json"
        send "/imports/preview?file_name=$entity.json" "$work/back-$entity.json" application/json
        expect "pkg an export of every record of $entity ($rows rows) is imported back as it is, as CSV and as JSON: every row finds its record by HID, unchanged" \
            "$made $status $(job_counts)" \
            "201 [\"previewed\", $rows, 0, 0, $rows, 0] 201 [\"previewed\", $rows, 0, 0, $rows, 0]"
    done
    api POST /exports '{"entity": "items", "format": "csv", "own_values": true, "include_archived": true, "include_drafts": true, "sort": ["depth"]}'
    cp "$work/body" "$work/back-items.csv"
    rows=$(table 'len(rows)' "$work/back-items.csv")
    send "/imports/preview?entity=items&file_name=items.csv" "$work/back-items.csv"
    expect "pkg and so is an export of every item, sorted by depth so that a parent stands before its minor items, $(table 'sum(1 for r in rows if r["parent"])' "$work/back-items.csv") of the $rows rows" \
        "$status $(job_counts)" "201 [\"previewed\", $rows, 0, 0, $rows, 0]"
}

# ---- condition, observation and health; one switch alone; how a cluster is managed ------------

# health: what the last item or group says of its health, the value and its reasons.
health() { json '[d["health"]["value"], d["health"]["reasons"]]'; }

# What 0.4.1 added, made through nginx under the prefix, beside the examples and what
# structure() made: the condition of an item and what is observed of it, with the
# health that follows; a stack that is one switch alone; a cluster counted in each of
# its three ways; and a move out of the team's hands that ends a membership. These have
# no scenario of their own in docs/build-plan.md, so they are marked pkg. Every name is
# invented, the model too. What is made here stays, for hirdir admin reset to clear.
health_and_counting() {
    section "condition, observation and health, one switch alone, and a cluster counted three ways, under $prefix/"
    local vendor model item lone second stack members cluster first other made number row_version day

    api GET '/vendors?limit=1000'
    vendor=$(json '[v["hid"] for v in d["items"] if v["name"] == "Package Test Networks"][0]')
    api POST /catalog-entries "{\"vendor_hid\": \"$vendor\", \"pid\": \"PT-24S\", \"type\": \"switch\", \"support_weight\": \"1.0\", \"est_value\": \"9000.00\", \"annual_support_cost\": \"700.00\"}"
    expect "pkg a second model of the vendor made above, with a support weight of 1.0, a value and a cost" "$status" 201
    model=$(json_field hid)

    # The three facts of an item, and the health that is worked out from them.
    api POST /items "{\"catalog_entry_hid\": \"$model\", \"serial_number\": \"PKG0000H001\", \"hostname\": \"pkgtest-health-01\", \"lifecycle_state\": \"Prod\"}"
    item=$(json_field hid)
    expect "pkg POST $prefix/api/v1/items: a new item has no condition and nothing observed, and its health is unknown, with the reason" \
        "$status $(json '[d["condition"], d["observed_status"], d["observed_at"], d["expected_online"]]') $(health)" \
        '201 [null, null, null, true] ["unknown", ["nothing is said of its condition, and nothing is observed"]]'
    api PATCH "/items/$item" '{"row_version": 1, "condition": "good"}'
    expect "pkg PATCH $prefix/api/v1/items/{hid} sets its condition to good, and its health is good" \
        "$status $(json_field condition) $(health)" '200 good ["good", ["its condition is good"]]'
    api PATCH "/items/$item" '{"row_version": 2, "observed_status": "unreachable"}'
    expect "pkg it is observed unreachable while it is expected online: its health is failed, whatever its condition, and the moment of the observation is kept" \
        "$status $(json '[d["condition"], d["observed_status"], d["observed_at"] is not None]') $(health)" \
        '200 ["good", "unreachable", true] ["failed", ["it is expected online and is observed unreachable"]]'
    api PATCH "/items/$item" '{"row_version": 3, "observed_status": "online", "observed_at": "2026-11-02T15:00:00Z", "condition": "degraded"}'
    expect "pkg observed online at a moment that the request gives, with a condition of degraded: its health is degraded, the worse of the two" \
        "$status $(json '[d["condition"], d["observed_status"], d["observed_at"]]') $(health)" \
        '200 ["degraded", "online", "2026-11-02T15:00:00Z"] ["degraded", ["its condition is degraded"]]'
    api PATCH "/items/$item" '{"row_version": 4, "condition": "as-new"}'
    # After an upgrade the list may hold conditions of the site's own beside the six.
    expect "pkg a condition that the item_condition list does not offer is refused, and the answer names those that it offers, the six defaults among them" \
        "$status $(json '[d["errors"][0]["field"], sorted({"untested", "good", "degraded", "suspect", "failed", "dead"} - set(d["errors"][0]["message"].removeprefix("one of ").split(", ")))]')" \
        '422 ["condition", []]'
    api PATCH "/items/$item" '{"row_version": 4, "observed_status": null}'
    expect "pkg the observation is taken back: its moment goes with it, and the condition alone decides the health" \
        "$status $(json '[d["observed_status"], d["observed_at"], d["lifecycle_state"]]') $(health)" \
        '200 [null, null, "Prod"] ["degraded", ["its condition is degraded"]]'
    authorized GET "$prefix/api/v1/items" --get --data-urlencode 'filter=health:eq:degraded hostname:glob:pkgtest-*'
    expect "pkg GET $prefix/api/v1/items finds it by its health, which is stored nowhere" \
        "$status $(json '[i["hostname"] for i in d["items"]]')" '200 ["pkgtest-health-01"]'
    api GET "/items/$item/history"
    expect "pkg each of those changes is in its history, the condition and the observation as fields like any other" \
        "$status $(json '[sorted(c["field"] for c in e["changes"]) for e in d["items"][:4]]')" \
        '200 [["observed_at", "observed_status"], ["condition", "observed_at", "observed_status"], ["observed_at", "observed_status"], ["condition"]]'
    summary 'hostname:eq:pkgtest-health-01'
    expect "pkg GET $prefix/api/v1/reports/summary counts it as one component that is degraded" \
        "$status $(totals) $(json 'd["totals"]["by_health"]')" \
        '200 [1, 1, 1, 1.0] {"degraded": 1, "failed": 0, "good": 0, "unknown": 0}'

    # A stack may be one switch alone, with no master. It is degraded, and it earns no
    # discount: one switch takes the full effort to look after.
    api POST /items "{\"catalog_entry_hid\": \"$model\", \"serial_number\": \"PKG0000L001\", \"hostname\": \"pkgtest-lone-01\", \"lifecycle_state\": \"Prod\"}"
    lone=$(json_field hid)
    api POST /device-groups "{\"type\": \"stack\", \"name\": \"pkgtest-lone\", \"members\": [{\"item_hid\": \"$lone\", \"position\": 1}]}"
    expect "pkg POST $prefix/api/v1/device-groups makes a stack of one switch with no master: it has no serial number, and it is degraded because it is one switch alone" \
        "$status $(json '[d["member_count"], d["master"], d["serial_number"], d["serial_source"]]') $(health)" \
        '201 [1, null, null, null] ["degraded", ["it is one switch alone"]]'
    stack=$(json_field hid)
    summary 'group.name:eq:pkgtest-lone'
    expect "pkg the summary of it: one component, one managed node, and the whole support weight of 1.0, with no stack discount" \
        "$status $(totals)" '200 [1, 1, 1, 1.0]'
    api PATCH "/device-groups/$stack" "{\"row_version\": 1, \"observed_master_hid\": \"$lone\"}"
    expect "pkg the switch is seen to be master, though none is intended: the stack shows its serial number as the observed one" \
        "$status $(json '[d["serial_number"], d["serial_source"], d["master"], d["master_as_intended"]]')" \
        '200 ["PKG0000L001", "observed", null, null]'
    api PATCH "/device-groups/$stack" "{\"row_version\": $(json_field row_version), \"expected_members\": 1}"
    expect "pkg said to be meant as one switch, with expected_members, it is no longer degraded for being alone" \
        "$status $(json_field expected_members) $(json 'd["health"]["value"]')" "200 1 unknown"
    api POST /items "{\"catalog_entry_hid\": \"$model\", \"serial_number\": \"PKG0000L002\", \"hostname\": \"pkgtest-lone-02\", \"lifecycle_state\": \"Prod\", \"condition\": \"good\"}"
    second=$(json_field hid)
    api POST "/device-groups/$stack/members" "{\"members\": [{\"item_hid\": \"$second\", \"position\": 2}]}"
    made=$status
    summary 'group.name:eq:pkgtest-lone'
    expect "pkg a second switch joins: two components, one managed node, and now the discount of 50 on both, a support weight of 1.0 for the two" \
        "$made $status $(totals)" '201 200 [2, 2, 1, 1.0]'
    management 'group.name:eq:pkgtest-lone'
    expect "pkg GET $prefix/api/v1/reports/management of the stack: the value and the cost of two switches, with no discount" \
        "$status $(money)" '200 [2, 2, "18000.00", "1400.00"]'
    api POST "/items/$second/transition" '{"to": "Pending-Removal", "reason": "rma", "row_version": 1}'
    made="$status $(json '[g["name"] for g in d["groups"]]')"
    api GET "/device-groups/$stack"
    expect "pkg the second switch is moved to Pending-Removal: it is a member still, and the stack is degraded for it" \
        "$made $(json '[d["member_count"], d["health"]["value"]]')" '200 ["pkgtest-lone"] [2, "degraded"]'

    # A cluster says how it is managed, and is counted so. The components and the
    # support weight do not depend on it.
    members=""
    for number in 1 2; do
        api POST /items "{\"catalog_entry_hid\": \"$model\", \"serial_number\": \"PKG0000F00$number\", \"hostname\": \"pkgtest-fw-0$number\", \"lifecycle_state\": \"Prod\"}"
        if [ "$number" = 1 ]; then first=$(json_field hid); else other=$(json_field hid); fi
        members="$members${members:+, }{\"item_hid\": \"$(json_field hid)\", \"role\": \"member\"}"
    done
    api POST /device-groups "{\"type\": \"cluster\", \"name\": \"pkgtest-fw\", \"members\": [$members]}"
    cluster=$(json_field hid)
    made="$status $(json_field managed_as)"
    summary 'group.name:eq:pkgtest-fw'
    expect "pkg a cluster of two that does not say how it is managed is managed as one: two components, one managed node" \
        "$made $status $(totals)" '201 one 200 [2, 2, 1, 2.0]'
    api PATCH "/device-groups/$cluster" '{"row_version": 1, "managed_as": "members"}'
    made=$status
    summary 'group.name:eq:pkgtest-fw'
    expect "pkg managed by its members, it is two managed nodes, and the components and the support weight are as they were" \
        "$made $status $(totals)" '200 200 [2, 2, 2, 2.0]'
    api PATCH "/device-groups/$cluster" '{"row_version": 2, "managed_as": "members_and_cluster"}'
    made=$status
    summary 'group.name:eq:pkgtest-fw'
    expect "pkg managed by its members and as a cluster too, it is three: one more than its members" \
        "$made $status $(totals)" '200 200 [2, 2, 3, 2.0]'
    api GET "/device-groups/$stack"
    api PATCH "/device-groups/$stack" "{\"row_version\": $(json_field row_version), \"managed_as\": \"members\"}"
    expect "pkg a stack is always one managed node: managed_as is refused on it" \
        "$status $(json 'd["errors"][0]["field"]')" "422 managed_as"

    # An item that leaves the team's hands leaves its groups. Released and Archived end
    # the membership on that day; no other move does.
    row_version=1
    made=""
    for number in Pending-Removal:decommissioned Released:disposed; do
        api POST "/items/$other/transition" "{\"to\": \"${number%:*}\", \"reason\": \"${number#*:}\", \"row_version\": $row_version}"
        row_version=$(json_field row_version)
        made="$made$status $(json '[g["name"] for g in d["groups"]]') "
    done
    expect "pkg a member of the cluster is moved to Pending-Removal, and is a member still; moved on to Released, it is in no group" \
        "$made" '200 ["pkgtest-fw"] 200 [] '
    api POST "/items/$first/transition" '{"to": "Archived", "reason": "disposed", "row_version": 1, "force": true}'
    made="$status $(json '[d["lifecycle_state"], d["groups"]]')"
    api GET "/device-groups/$cluster/members?include_past=true"
    day=$(json 'd["items"][0]["left_on"]')
    expect "pkg the other is moved straight to Archived, by an Admin who forces the move: that ends its membership too, and both memberships stay on record with the day they ended" \
        "$made $status $(json '[len(d["items"]), sorted({m["left_on"] for m in d["items"]}) == ["'"$day"'"], sum(1 for m in d["items"] if not m["left_on"])]')" \
        '200 ["Archived", []] 200 [2, true, 0]'
    check "pkg and that day is written as a date, YYYY-MM-DD ($day)" \
        bash -c "[[ '$day' =~ ^20[0-9]{2}-[0-9]{2}-[0-9]{2}\$ ]]"
    api GET "/device-groups/$cluster"
    expect "pkg the cluster is the same record, with no member" \
        "$status $(json '[d["hid"], d["member_count"]]')" "200 [\"$cluster\", 0]"
}

# ---- a first file ---------------------------------------------------------------------------

# The file a site is likely to have before anything else: host names and addresses, under
# the column names of its own spreadsheet. It loads as it is, and a second time changes
# nothing. The addresses are from the ranges reserved for documentation.
first_file() {
    section "a first file of host names and addresses, through nginx under $prefix/"
    local hid
    printf '%s\n' 'hostname,IP_address' \
        'pkgtest-first-01,198.51.100.101' \
        'pkgtest-first-02,2001:0DB8:0000:0051:0000:0000:0000:0102' \
        'pkgtest-first-03,' >"$work/first.csv"
    send "/imports/preview?entity=items&file_name=first.csv" "$work/first.csv"
    expect "pkg POST $prefix/api/v1/imports/preview takes a file whose columns are hostname and IP_address, as it is: each of its 3 rows is to be created" \
        "$status $(job_counts)" '201 ["previewed", 3, 3, 0, 0, 0]'
    hid=$(json 'd["job"]["hid"]')
    api POST "/imports/$hid/apply"
    expect "pkg applied, it creates the 3 items" "$status $(job_counts)" '200 ["applied", 3, 3, 0, 0, 0]'
    authorized GET "$prefix/api/v1/items" --get --data-urlencode 'filter=hostname:glob:pkgtest-first-*' --data-urlencode 'sort=hostname'
    expect "pkg each has its host name, and its address as the primary management address of its family, IPv4 or IPv6, in the short form; the one with no address has none" \
        "$status $(json '[[i["hostname"], [[a["address"], a["family"], a["role"], a["is_primary"], a["network"]] for a in i["addresses"]]] for i in d["items"]]')" \
        '200 [["pkgtest-first-01", [["198.51.100.101", 4, "management", true, null]]], ["pkgtest-first-02", [["2001:db8:0:51::102", 6, "management", true, null]]], ["pkgtest-first-03", []]]'
    send "/imports/preview?entity=items&file_name=first.csv" "$work/first.csv"
    expect "pkg the same file a second time: each row finds its item by its host name, unchanged" \
        "$status $(job_counts)" '201 ["previewed", 3, 0, 0, 3, 0]'
    printf '%s\n' 'hostname,ipv4,ipv6,observed_status' \
        'pkgtest-first-02,198.51.100.102,,online' \
        'pkgtest-first-03,198.51.100.103,2001:db8:0:51::103,present' >"$work/second.csv"
    send "/imports/preview?entity=items&file_name=second.csv" "$work/second.csv"
    hid=$(json 'd["job"]["hid"]')
    api POST "/imports/$hid/apply"
    expect "pkg a file with ipv4 and ipv6 columns and what was observed of each: both rows update their items" \
        "$status $(job_counts)" '200 ["applied", 2, 0, 2, 0, 0]'
    authorized GET "$prefix/api/v1/items" --get --data-urlencode 'filter=hostname:glob:pkgtest-first-*' --data-urlencode 'sort=hostname'
    expect "pkg an item has a primary management address of each family now, and what was observed of it, with a health of good" \
        "$status $(json '[[i["hostname"], sorted([a["family"], a["address"], a["is_primary"]] for a in i["addresses"]), i["observed_status"], i["health"]["value"]] for i in d["items"][1:]]')" \
        '200 [["pkgtest-first-02", [[4, "198.51.100.102", true], [6, "2001:db8:0:51::102", true]], "online", "good"], ["pkgtest-first-03", [[4, "198.51.100.103", true], [6, "2001:db8:0:51::103", true]], "present", "good"]]'
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
    expect "pkg the migrations loaded the default choices of all five lists, item_condition among them" \
        "$status $(json '" ".join(sorted({c["list"] for c in d}))')" "200 catalog_function catalog_type item_condition replacement_reason state_reason"
    expect "pkg the replacement_reason list offers at least its five defaults" \
        "$(json 'sorted({"rma", "refresh", "project", "upgrade", "other"} - {c["value"] for c in d if c["list"] == "replacement_reason"})')" "[]"
    expect "pkg and the item_condition list at least its six, from untested to dead" \
        "$(json 'sorted({"untested", "good", "degraded", "suspect", "failed", "dead"} - {c["value"] for c in d if c["list"] == "item_condition"})')" "[]"
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

    # hirdir-setup --upgrade is how an operator installs a newer package: it checks the
    # file and hands over to apt with no question left to answer. Given the package
    # that is installed, it installs it again.
    local code=0
    inside hirdir-setup --upgrade /srv/debs/hirdir-new.deb --yes >"$work/setup-upgrade.log" 2>&1 </dev/null || code=$?
    expect "pkg hirdir-setup --upgrade PACKAGE.deb, with nobody to answer, installs the package through apt" \
        "$code $(grep -c "^hirdir $version -> $version\$" "$work/setup-upgrade.log") $(grep -c '^hirdir: the database as it was before this upgrade is kept at' "$work/setup-upgrade.log")" \
        "0 1 1"
    if wait_ready; then
        pass "pkg and the service came back"
    else
        fail "pkg and the service came back (got $status)"
    fi
    expect "pkg and the hirdir-setup of the package that was installed finishes it: it reports the version and that the service runs" \
        "$(grep -c "^hirdir $version is installed, and is running\.\$" "$work/setup-upgrade.log") $(grep -c '^hirdir.service: active$' "$work/setup-upgrade.log")" "1 1"
    # The nightly upgrade is shipped switched off, and runs late at night when on.
    expect "pkg hirdir-upgrade.timer is installed and is not enabled: a site turns it on" \
        "$(inside systemctl is-enabled hirdir-upgrade.timer 2>&1) $(inside systemctl is-active hirdir-upgrade.timer 2>&1)" \
        "disabled inactive"
    inside systemctl enable --now hirdir-upgrade.timer >/dev/null 2>&1 || true
    expect "pkg turned on, it waits for a time between 21:00 and 03:00 in the host's local time" \
        "$(inside bash -c 'next=$(systemctl show hirdir-upgrade.timer --property=NextElapseUSecRealtime --value)
            hour=$(date --date="$next" +%-H); if [ "$hour" -ge 21 ] || [ "$hour" -lt 3 ]; then echo late at night; else echo "at $next"; fi' 2>&1)" \
        "late at night"
    expect "pkg and what it will run is hirdir-setup --upgrade --yes" \
        "$(inside systemctl show hirdir-upgrade.service --property=ExecStart --value 2>&1 | grep -c 'argv\[\]=/usr/sbin/hirdir-setup --upgrade --yes ')" 1
    inside systemctl disable --now hirdir-upgrade.timer >/dev/null 2>&1 || true
    expect "pkg turned off again, it is off" "$(inside systemctl is-enabled hirdir-upgrade.timer 2>&1)" disabled

    # Asking GitHub is not done here: a test must not hang on the network. What is shown
    # is that a proxy named with --proxy is the way the request goes, and that a proxy
    # which does not answer is said plainly, with nothing changed.
    code=0
    inside hirdir-setup --check --proxy http://127.0.0.1:9/ >"$work/setup-check.log" 2>&1 </dev/null || code=$?
    expect "pkg hirdir-setup --check --proxy goes through the proxy named, and says so when the proxy does not answer" \
        "$code $(grep -c 'GitHub could not be reached through the proxy http://127.0.0.1:9' "$work/setup-check.log") $(grep -c Traceback "$work/setup-check.log")" \
        "1 1 0"
    if inside test -e /srv/debs/hirdir-previous.deb; then
        code=0
        inside hirdir-setup --upgrade /srv/debs/hirdir-previous.deb --yes >"$work/setup-upgrade.log" 2>&1 </dev/null || code=$?
        expect "pkg given an older package it refuses, and installs nothing" \
            "$code $(grep -c 'older than' "$work/setup-upgrade.log") $(installed_version)" "1 1 $version"
    fi
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
    # A site that turned the nightly upgrade on: the purge must leave no link to it.
    inside systemctl enable --now hirdir-upgrade.timer >/dev/null 2>&1 || true
    expect "pkg the nightly upgrade is turned on before the purge, as a site may have it" \
        "$(inside systemctl is-enabled hirdir-upgrade.timer 2>&1)" enabled
    if apt_get purge hirdir; then
        pass "S01 the package purges"
    else
        fail "S01 the package purges"
        tail -n 20 "$work/apt.log"
    fi
    for path in /opt/hirdir /var/lib/hirdir /var/cache/hirdir /etc/hirdir /usr/bin/hirdir /etc/nginx/snippets/hirdir.conf \
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
