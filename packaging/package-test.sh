#!/bin/bash
# Install the package in a clean Ubuntu 26.04 container that runs systemd, and exercise
# it through nginx over HTTPS under a URL prefix. "make package-test" runs this, and
# "make e2e" runs it with --e2e. It needs docker, curl, python3, make and dpkg-deb on
# the host.
#
# Usage: packaging/package-test.sh [--e2e] [--upgrade | --upgrade-alone | --failed-upgrade | --fresh]
#
# There are three passes, each in a container of its own. With none named, all three
# run, side by side when the host has cores and memory free for it and one after another
# when it has not, and a summary of them all ends the run.
#
#   --upgrade          install the previous release, put accounts, a group, a role grant,
#                      a service token, audit events, an inventory and a changed
#                      configuration into it, upgrade it with apt, and see that all of
#                      it is still there and still works, under the prefix it had; then
#                      everything the fresh pass does. The inventory is made for what an
#                      upgrade could harm, of everything the previous release can
#                      store: items with every kind of value between them, minor items,
#                      stacks, clusters, a controller domain, their members, a
#                      replacement, conditions, what is observed and when, addresses,
#                      and choices of the site's own; from 0.5.0 places, contacts and
#                      operators, with items and a stack among them; from 0.6.0
#                      agreements, contracts, coverage, purchases, external systems,
#                      registrations and capacity lines; from 0.7.0 the contacts of
#                      contracts, the flag not to renew, renewals with their members,
#                      lines that are not tracked, a line that multiplies, the record
#                      of the capacity balance, links and the renewal alert seen; from
#                      0.8.0 circuits of each shape with their carriers, cost lines,
#                      devices and contacts, the contacts of a carrier, a circuit
#                      group, the weights of places and the six weights set
#   --failed-upgrade   install the previous release, with the same inventory, and make
#                      the migration of the new one fail, in the database: by a table in
#                      the way of one it creates, or, where it creates none, by a
#                      trigger that refuses the new revision once everything else is
#                      done. The upgrade must stop, name the backup and leave the
#                      inventory as it was, and the way back that its message gives
#                      must work. A release with no migration has nothing that could
#                      fail: the pass says so in a SKIP line, upgrades, and goes back by
#                      installing the older package alone
#   --upgrade-alone    the upgrade pass up to where it goes on to what the fresh pass
#                      does, and no further. For work on the upgrade passes, and for a
#                      pair of older releases, whose package cannot do what the fresh
#                      pass asks of this tree's. It says in a SKIP line what it left out,
#                      and is not the release check
#   --fresh            install on a system that never had hirdir, as a new
#                      installation does, and exercise it: the examples imported and
#                      exported through nginx, minor items, a stack, a replacement and
#                      addresses made beside them, condition, observation and health,
#                      a cluster counted in its three ways, regions, sites, locations
#                      and contacts with what a place has in force, a site moved, an
#                      item with an owner outside the team, operators, deliveries to
#                      a street address, planned locations and a site made active,
#                      what a group gives its members, contracts and what they
#                      cover, a purchase received, a stack registered, a draft site
#                      and an archived item, reference files uploaded and downloaded
#                      through nginx and a backup of them restored on a second, clean
#                      host, then the inventory made by hand, and the capacity balance
#                      of the worked example
#   --e2e              in the fresh pass, also run the browser scenarios of web/
#                      against the container (npm --prefix web run e2e). The browser
#                      runs in Playwright's container image unless E2E_HOST_BROWSER=1
#                      asks for the host's, or PW_TEST_CONNECT_WS_ENDPOINT names one.
# Environment:
#   DEB            the package to test (default: dist/hirdir_<version>_amd64.deb, for
#                  the version of this tree). The version that is tested is read from
#                  the package.
#   PREVIOUS_DEB   the package of the previous release, for the two upgrade passes.
#                  Left out, it is the hirdir_*_amd64.deb beside DEB with the highest
#                  version below the one being tested.
#
# When no previous package is found, the two upgrade passes are skipped and the run
# says so with a SKIP line that names what was not tested and how to test it. The
# fresh install is tested all the same. --fresh alone asks for just that.
#
# The two upgrade passes are written for no pair of releases. They read from the two
# packages which versions they are and which revision the migrations of each end at,
# and so whether there is a migration between them and which. What every upgrade must
# show is in this file. What one migration, or one release, alone has is in a file of
# its own in packaging/package-test.d/, which is read when the pair crosses it: see
# "what one upgrade alone has" below. A release with no migration needs no change here.
#
# Every check prints a line that starts with PASS, FAIL or SKIP. A failed check is
# counted and the run goes on, so that one run reports every problem. The exit status
# is 0 only when no check failed. The container and its image are always removed.
#
# A check that belongs to a scenario of docs/build-plan.md carries its number, S01 or
# S02 for the package and sign-in, S06 to S11 for the inventory, S12, S13 and S16 for
# files, S18 to S21 and S23 for minor items, stacks, a replacement and addresses, S24 to
# S28 for places, contacts, a site that is moved and an owner outside the team, S29 to
# S35 for contracts and coverage, the end of life, the portfolio of a vendor, purchases,
# registrations, drafts and archived items, S39 and S40 for the capacity balance. The
# others, marked pkg, are about the package alone, or about a record that has no
# scenario of its own yet, such as the condition of an item and the health of a stack.
#
# The files are sent with curl, as the API takes them. The client commands of the
# command line (hirdir import, hirdir export, hirdir items, hirdir groups, hirdir
# report, hirdir geography, hirdir locations, hirdir regions, hirdir sites, hirdir
# operators, hirdir agreements, hirdir contracts, hirdir purchases, hirdir systems,
# hirdir registrations, hirdir capacity and hirdir vendors) are then run in the
# container, from the package, by client_commands().
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
self=packaging/package-test.sh

usage() {
    echo "usage: $self [--e2e] [--upgrade | --upgrade-alone | --failed-upgrade | --fresh]" >&2
    exit 2
}

e2e=0
mode=""
alone=0
for argument in "$@"; do
    case $argument in
        --e2e) e2e=1 ;;
        --upgrade | --failed-upgrade | --fresh)
            [ -z "$mode" ] || usage
            mode=${argument#--}
            ;;
        --upgrade-alone)
            [ -z "$mode" ] || usage
            mode=upgrade
            alone=1
            ;;
        *) usage ;;
    esac
done

# The package under test is the one of this tree's version unless DEB names another. Its
# version is then read from the package itself, as that of the previous one is.
tree_version=$(make -s version)
deb=${DEB:-dist/hirdir_${tree_version}_amd64.deb}
if [ ! -f "$deb" ]; then
    echo "package-test: there is no $deb. Build the package first: make deb" >&2
    exit 2
fi
version=$(dpkg-deb -f "$deb" Version)

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

# ---- the pair of releases -----------------------------------------------------------------

# migrations PACKAGE QUESTION [REVISION]: read the migrations that a package carries.
#   head              the newest revision, which is where the schema of that release ends
#   after REVISION    the revisions after that one, in order, on one line
#   created REVISION  the table that the migrations after REVISION create last, or nothing
#   tables REVISION   every table that the migrations after REVISION create, in order
migrations() {
    local from=$1
    shift
    dpkg-deb --fsys-tarfile "$from" |
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
    sys.exit()
later = [revision for revision in sorted(tables) if revision > sys.argv[2]]
created = [name for revision in later for name in tables[revision]]
if sys.argv[1] == "after":
    print(" ".join(later))
else:
    print(" ".join(created) if sys.argv[1] == "tables" else created[-1] if created else "")' "$@"
}

# What the two packages say of themselves, which is all that the upgrade passes are told
# of the pair: the revision that the migrations of each end at, and so the migrations
# that the upgrade runs. $crossed is their revisions, in order, and is empty when the
# two releases have the same schema: the upgrade then has no migration.
head=$(migrations "$deb" head)
previous_head=""
crossed=""
if [ -n "$previous" ]; then
    previous_head=$(migrations "$previous" head)
    crossed=$(migrations "$deb" after "$previous_head")
fi

# Whether the upgrade from the previous release runs a migration.
migrating() { [ -n "$crossed" ]; }

# In words, for the lines that say it.
if migrating; then
    crossing="migration $crossed"
    case $crossed in *' '*) crossing="migrations ${crossed// /, }" ;; esac
else
    crossing="no migration"
fi

# ---- every pass ---------------------------------------------------------------------------

# How many passes may run at once: as many as the host has cores and memory free, which
# scripts/test_load.py says after waiting for a busy host, ten minutes at the most. One
# at a time where that cannot be asked.
passes_at_once() {
    local width
    width=$(python3 "$(dirname "$self")/../scripts/test_load.py" --wait) || width=1
    case $width in '' | *[!0-9]*) width=1 ;; esac
    if [ "$width" -gt "$1" ]; then width=$1; fi
    if [ "$width" -lt 1 ]; then width=1; fi
    echo "$width"
}

# one_pass OPTION...: run one pass as a command of its own.
one_pass() {
    # A pass finds the previous package as this run did: by PREVIOUS_DEB when the
    # person set it, which the pass inherits, and beside the package otherwise.
    DEB=$deb PACKAGE_TEST_EVERY_PASS=1 bash "$self" "$@" 2>&1
}

# With no pass named: run each one as a command of its own, and sum them up. Each pass
# has a container, an image and a port of its own, so they run side by side when the
# host has room for it. The output of each is then shown whole, in the order of the
# passes, when all have ended.
every_pass() {
    local log logs failed=0 code option earlier options arguments width running=0 started
    log=$(mktemp)
    logs=$(mktemp -d)
    # shellcheck disable=SC2064  # The names are fixed now, on purpose.
    trap "rm -rf '$log' '$logs'" EXIT
    if [ -n "$previous" ]; then
        options=(--upgrade --failed-upgrade --fresh)
        echo "package-test: hirdir $previous_version, with its schema at revision $previous_head, to $version, at $head: the upgrade runs $crossing"
    else
        options=(--fresh)
        earlier=$(earlier_release)
        if [ -n "$earlier" ]; then
            echo "SKIP  pkg upgrade from the previous release: hirdir $earlier was released before $version, and no package older than $version is in $(dirname "$deb")/, so no upgrade was tested by this run. Put the package of the previous release there, or name it with PREVIOUS_DEB, to test it" | tee -a "$log"
        else
            echo "SKIP  pkg upgrade from the previous release: docs/releases/ holds no release before $version, so there is nothing to upgrade from" | tee -a "$log"
        fi
    fi
    started=$SECONDS
    width=$(passes_at_once "${#options[@]}")
    if [ "$width" -gt 1 ]; then
        echo "package-test: $width passes at once; what each says is shown when all have ended, and is written meanwhile to $logs/"
        # Built once here, so that the passes find the image's layers made and do not
        # each make them.
        docker build --quiet - <packaging/container/Dockerfile.systemd >/dev/null
    fi
    for option in "${options[@]}"; do
        arguments=("$option")
        if [ "$e2e" = 1 ] && [ "$option" = --fresh ]; then arguments+=(--e2e); fi
        if [ "$width" -gt 1 ]; then
            while [ "$running" -ge "$width" ]; do
                wait -n || true
                running=$((running - 1))
            done
            (
                code=0
                one_pass "${arguments[@]}" >"$logs/${option#--}.log" || code=$?
                echo "$code" >"$logs/${option#--}.status"
            ) &
            running=$((running + 1))
            continue
        fi
        code=0
        one_pass "${arguments[@]}" | tee "$logs/${option#--}.log" || code=$?
        echo "$code" >"$logs/${option#--}.status"
    done
    wait
    for option in "${options[@]}"; do
        if [ "$width" -gt 1 ]; then cat "$logs/${option#--}.log"; fi
        cat "$logs/${option#--}.log" >>"$log"
        code=$(cat "$logs/${option#--}.status" 2>/dev/null || echo 1)
        if [ "$code" -ne 0 ]; then
            failed=1
            grep -q "^package-test: ${option#--}: " "$log" ||
                echo "FAIL  pkg the ${option#--} pass ran to its end (it stopped with status $code)" | tee -a "$log"
        fi
    done

    printf '\n== every pass, in %s s, %s at once\n' "$((SECONDS - started))" "$width"
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
    # The second host of reference_files, where a pass stopped before it was removed.
    docker rm --force "$container-clean" >/dev/null 2>&1 || true
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

# apply_job PATH [curl options]: POST the apply of a stored preview, which answers 202 at
# once while the server applies it in the background (D-185), then look at the job
# until it is no longer queued or applying, two minutes at the most. $status is the
# answer to the POST, and the body is the job as it ended, for job_counts to read. With
# curl options the POST goes through nginx with them, as `authorized` sends it.
apply_job() {
    local path=$1 begun hid looked=0
    shift
    if [ $# -gt 0 ]; then
        authorized POST "$prefix/api/v1$path" "$@"
    else
        api POST "$path"
    fi
    begun=$status
    hid=$(json_field hid)
    while [ "$begun" = 202 ] && [ "$looked" -lt 1200 ]; do
        case $(json_field status) in
        queued | applying) ;;
        *) break ;;
        esac
        sleep 0.1
        looked=$((looked + 1))
        api GET "/imports/$hid"
    done
    status=$begun
}

# keep NAME: keep the JSON of the last response for unchanged to compare with.
keep() { cp "$work/body" "$work/kept-$1.json"; }

# unchanged NAME [more | fields | "fields more"]: print "same" when every record kept
# under NAME is in the last response with the same HID and every field as it was, and
# no record was added. With "more", records may have been added. With "fields", a newer
# version may have given a record more fields, also inside a record it holds, such as
# the block of effective values, and inside each record of a list it holds, such as its
# addresses: every field that was there must still be there as it was. Both may be
# said, with a space between them. A third word names what is
# meant to have changed and is looked at by itself, each as HID.field, with a space
# between them: those fields are passed over. With "fields", one field of a block that
# the record holds is named as HID.field.field, as HID.effective.owner_hid is, and the
# rest of that block is compared. Otherwise print what differs. What was kept may be a
# list of records, a page of them, or one record by itself.
unchanged() {
    python3 -c '
import json, sys

def records(path):
    document = json.load(open(path, encoding="utf-8"))
    if isinstance(document, dict):
        return document["items"] if "items" in document else [document]
    return document

how = sys.argv[3].split()

def same(was, now, path):
    if "fields" in how and isinstance(was, dict) and isinstance(now, dict):
        return all(
            f"{path}.{key}" in meant or (key in now and same(value, now[key], f"{path}.{key}"))
            for key, value in was.items()
        )
    if "fields" in how and isinstance(was, list) and isinstance(now, list):
        return len(was) == len(now) and all(same(*pair, path) for pair in zip(was, now))
    return was == now

try:
    before = records(sys.argv[1])
    now = {record["hid"]: record for record in records(sys.argv[2])}
except Exception as error:
    print(f"<{type(error).__name__}: {error}>")
    sys.exit()
problems = []
meant = set(sys.argv[4].split())
if len(now) != len(before) and "more" not in how:
    problems.append(f"{len(now)} records where there were {len(before)}")
for record in before:
    hid = record["hid"]
    found = now.get(hid)
    if found is None:
        problems.append(hid + " is gone")
        continue
    changed = sorted(
        key
        for key, value in record.items()
        if f"{hid}.{key}" not in meant and (key not in found or not same(value, found[key], f"{hid}.{key}"))
    )
    if changed:
        problems.append(hid + " changed in " + ", ".join(changed))
print("; ".join(problems[:3]) if problems else "same")' "$work/kept-$1.json" "$work/body" "${2:-exact}" "${3:-}"
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
#   rows-of HID,HID COLUMN...
#                    the same, of the rows with these HIDs alone
#   hids [HID,HID]   the HID of every row, but for those named, with a comma between them
# A row is known by its HID. A table that has no hid column, such as the targets of a
# capacity line, knows a row by its primary key, its columns written with a / between
# them, and that stands for the HID above.
table_read() {
    inside runuser -u hirdir -- /opt/hirdir/python/bin/python3 -I -c '
import hashlib, sqlite3, sys

held = sqlite3.connect("/var/lib/hirdir/hirdir.db")
table, question, names = sys.argv[1], sys.argv[2], sys.argv[3:]
hids = names.pop(0).split(",") if names and question in ("rows-of", "hids") else None
if not all(name.replace("_", "").isalnum() for name in [table, *names]):
    sys.exit("table_read: a table and its columns are named by letters, digits and _")
info = held.execute(f"PRAGMA table_info({table})").fetchall()
keyed = [column[1] for column in sorted(info, key=lambda column: column[5]) if column[5]]
key = "hid" if any(column[1] == "hid" for column in info) else (" || " + repr("/") + " || ").join(f"\"{name}\"" for name in keyed)
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
elif question == "hids":
    found = [hid for (hid,) in held.execute(f"SELECT {key} FROM {table} ORDER BY {key}")]
    print(",".join(hid for hid in found if hid not in (hids or [])))
else:
    if not names:
        sys.exit("table_read rows: name the columns")
    only = "" if hids is None else f" WHERE {key} IN (" + ", ".join("?" * len(hids)) + ")"
    rows = held.execute("SELECT " + ", ".join(f"\"{name}\"" for name in names) + f" FROM {table}{only} ORDER BY {key}", hids or []).fetchall()
    print(len(rows), "rows", hashlib.sha256(repr(rows).encode()).hexdigest())' "$@" 2>&1
}

# table_columns TABLE: the names of its columns, on one line.
table_columns() { table_read "$1" columns | cut -d' ' -f1 | xargs; }

# table_rows TABLE "COLUMN ..." [HID,HID]: table_read rows, for the columns that one
# line names: of every row, or of the rows with these HIDs alone.
table_rows() {
    local names
    read -ra names <<<"$2"
    if [ $# -ge 3 ]; then
        table_read "$1" rows-of "$3" "${names[@]}"
    else
        table_read "$1" rows "${names[@]}"
    fi
}

# events_beside HIDS: the audit trail as it is after an upgrade, beside the events it
# held before, whose HIDs are named with a comma between them: how many of those there
# are and one checksum of what they hold, as table_rows prints it of them all; then
# how many events there are since that the started service did not write by itself,
# and how many it did. From 0.7.0 the service records the capacity balance of the
# week when it starts in a week that has no record (D-188): one event, which the system
# makes and nobody, of the action create on a capacity_record. From 0.8.0 it also works
# out the long reports when it starts (P-157), which writes nothing. No upgrade writes
# an event, and a check that one wrote none allows for that event by name, and for no
# other.
events_beside() {
    inside runuser -u hirdir -- /opt/hirdir/python/bin/python3 -I -c '
import hashlib, sqlite3, sys

held = sqlite3.connect("/var/lib/hirdir/hirdir.db")
then = set(sys.argv[1].split(","))
names = [column[1] for column in held.execute("PRAGMA table_info(audit_events)")]
rows = held.execute("SELECT " + ", ".join(f"\"{name}\"" for name in names) + " FROM audit_events ORDER BY hid").fetchall()
kept = [row for row in rows if row[names.index("hid")] in then]
since = [dict(zip(names, row)) for row in rows if row[names.index("hid")] not in then]
own = [e for e in since if (e["via"], e["actor_hid"], e["action"], e["record_type"]) == ("system", None, "create", "capacity_record")]
print(len(kept), "rows", hashlib.sha256(repr(kept).encode()).hexdigest(), "|", len(since) - len(own), "other,", len(own), "by the service itself")' "$1" 2>&1
}

# no_event_written BEFORE HIDS: the check that an upgrade wrote no audit event, made
# before anything is asked of the new version, since a sign-in is an event too. BEFORE
# is what table_rows printed of the audit trail before the upgrade and HIDS the HIDs of
# its events: each must be as it was, and beside them there may be the one event that
# the started service writes by itself, and nothing else.
no_event_written() {
    local found own
    found=$(events_beside "$2")
    own=$(printf '%s' "$found" | sed -n 's/.*other, \([0-9]*\) by the service itself$/\1/p')
    own=${own:-0}
    expect "pkg the upgrade wrote no audit event: the audit trail holds the events it held, each as it was ($1), and beside them nothing but what the started service writes by itself, the record of the capacity balance of a week that had none: $own such event" \
        "$found" "$1 | 0 other, $((own > 1 ? 1 : own)) by the service itself"
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
# the file BEFORE, each as it was and in its order, with nothing taken out or changed:
# only lines put in among them, where a new setting goes to the end of its table.
settings_kept() {
    settings_file >"$work/settings-now.toml"
    python3 -c '
import difflib, sys
before, now = (open(path, encoding="utf-8").read() for path in sys.argv[1:3])
steps = difflib.SequenceMatcher(None, before.splitlines(), now.splitlines(), autojunk=False).get_opcodes()
kept = all(step[0] in ("equal", "insert") for step in steps)
print("kept" if kept else "changed", "same" if now == before else "more")' \
        "$1" "$work/settings-now.toml"
}

# new_settings: the settings that the package under test ships and the previous one
# does not, each on a line: its name, as files.max_megabytes, a tab, and its line in the
# file, commented out at its default. A heading that is new comes before its settings,
# as itself in both places.
new_settings() {
    python3 -c '
import re, sys

def settings(text):
    found, section = {}, ""
    for line in text.splitlines():
        if head := re.fullmatch(r"\[(.+)\]", line):
            section = head[1]
            found[line] = line
        elif key := re.fullmatch(r"# ([a-z_]+) = .+", line):
            found[f"{section}.{key[1]}"] = line
    return found

before, now = (settings(text) for text in sys.argv[1:3])
for name, line in now.items():
    if name not in before:
        print(name, line, sep="\t")' "$(shipped_settings "$previous")" "$(shipped_settings "$deb")"
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
    revision_before=$(revision_now)
    expect "pkg hirdir admin check of $previous_version names its schema revision, which is the one that the migrations of its package end at" \
        "$revision_before" "$previous_head"
}

# ---- what one upgrade alone has ------------------------------------------------------------

# Everything else in the two upgrade passes is what every upgrade must show. What only
# one migration has, or only one release, is in a file of its own in
# packaging/package-test.d/:
#
#   migration-REVISION.sh   read when the upgrade runs that migration: its revision is
#                           after the schema of the previous release, and the new
#                           version has it
#   release-VERSION.sh      read when the upgrade crosses that release: the previous
#                           release is older than it, and the new version is not. For a
#                           release that says or reads differently, with no migration,
#                           something that it holds as before. Most releases have none
#
# Such a file says what it has to say in up to three functions. They are named for its
# revision, as before_0006 is, or for its version with _ for each dot, as before_0_4_2
# is. Any of them may be left out.
#
#   before_KEY        runs with the previous release serving, when the inventory is
#                     made and before it is kept. It makes what the migration could
#                     harm, or is meant to change, through the API of the previous
#                     release, and says what is meant to change, in the names below
#   changed_KEY WHEN  runs with the new version serving, each time the inventory has
#                     been compared with what was kept. It looks, by itself, at what
#                     was left out of that comparison by name, and at what the
#                     migration puts into what it creates. It changes nothing. WHEN
#                     begins its lines
#   after_KEY         runs in the upgrade pass alone, last of what is asked of the
#                     inventory. It tries what is new on what was carried over, and
#                     may write
#
# What a file says is meant to change, so that the comparison passes over it by name:
#
#   meant[LIST]          fields of records, each as HID.field, with a space before each,
#                        or as HID.field.field for one field of a block that the
#                        record holds. LIST is items, device-groups, members,
#                        networks, addresses, owners, choices or stack, which is the
#                        first stack read by itself
#   may_add[NAME]        set when the new version may add records to that list, or
#                        rows to the table of that name: choices is both
#   rows_apart[TABLE]    the HIDs of the rows of a table that are meant to change, with
#                        a comma between them
#   new_columns[TABLE]   the columns that the migration adds to a table, as table_read
#                        columns prints them, one on a line
#   altered_columns[TABLE]
#                        the columns that it declares otherwise, each in its place, such
#                        as one that may now be blank, as table_read columns prints them
#                        afterwards, one on a line
#   new_keys[TABLE]      the indexes and foreign keys that it adds, as table_read keys
#                        prints them, one on a line
#   more_tables          tables that hold what a site made and are no part of the
#                        inventory, which the migration changes, such as its import jobs,
#                        with a space between them: they are read from the database
#                        file, kept and compared as the tables of the inventory are
#   counted_view         the view of the items that must be counted as before, as a
#                        query with its question mark, where the migration is meant to
#                        change how some are counted. Empty, it is all of them
#   writes_no_event=yes  the migration writes no audit event: the audit trail must
#                        then hold the events it held and no other when the upgrade
#                        is done, as after an upgrade with no migration
#   fail_by=trigger      make the migration fail by the trigger on alembic_version
#                        though it creates a table: for a migration that creates its
#                        tables before it changes those that hold a site's records
#
# The tables that a migration creates are read from the package and are not named. A
# file may also set, as it is read, what the inventory is to expect of the previous
# release where that differs from every release since: see $zoneless_moment and
# $witness_weight.
#
# A migration that has no file is given what every upgrade is given, and a SKIP line
# that says so, in both passes. Nobody has then said what it adds, so what was there
# must be as it was, and what is there beside it, columns, rows or records, is let be
# until its file names it. Its file is then still to be written, or to be made with
# nothing in it but the reason why it needs nothing.
particulars_dir=packaging/package-test.d
particulars=()
particular_files=()
unwritten=""
declare -A meant=() may_add=() rows_apart=() new_columns=() altered_columns=() new_keys=() rest_of=() rest_before=()
more_tables=""
counted_view=""
writes_no_event=""
fail_by=""
# The days, in UTC, that the upgrade which went through began and ended on.
upgrade_days=""

# also NAME TABLE LINES: put LINES after what the files of the earlier migrations of the
# upgrade have said of a table in new_columns, altered_columns or new_keys, which NAME
# is, so that an upgrade that runs two migrations, each with its file, is told of both:
#   also new_columns items 'do_not_renew BOOLEAN NULL -'
also() {
    local -n said=$1
    said[$2]="${said[$2]:+${said[$2]}$'\n'}$3"
}

# Read the files of the migrations that the upgrade runs, and of the releases it crosses.
load_particulars() {
    local revision file found
    for revision in $crossed; do
        file=$particulars_dir/migration-$revision.sh
        if [ -f "$file" ]; then
            # shellcheck source=/dev/null
            . "$file"
            particulars+=("$revision")
            particular_files+=("$file")
        else
            unwritten="${unwritten:+$unwritten }$revision"
        fi
    done
    for file in $(printf '%s\n' "$particulars_dir"/release-*.sh | sort -V); do
        [ -f "$file" ] || continue
        found=${file##*/release-}
        found=${found%.sh}
        if dpkg --compare-versions "$previous_version" lt "$found" &&
            dpkg --compare-versions "$found" le "$version"; then
            # shellcheck source=/dev/null
            . "$file"
            particulars+=("${found//./_}")
            particular_files+=("$file")
        fi
    done
}

# particular WHAT [ARGUMENT...]: run the function WHAT_KEY of every file that was read
# and has one.
particular() {
    local what=$1 key
    shift
    for key in "${particulars[@]}"; do
        if declare -F "${what}_$key" >/dev/null; then "${what}_$key" "$@"; fi
    done
}

# What the pass was told of the pair, and what it read for it.
pair_said() {
    local file revision
    note "hirdir $previous_version has its schema at revision $previous_head, and $version at $head: the upgrade runs $crossing"
    if [ "$version" != "$tree_version" ]; then
        note "the package under test is hirdir $version, which DEB names, and this tree is $tree_version"
    fi
    for file in "${particular_files[@]}"; do
        note "read for this pair: $file"
    done
    for revision in $unwritten; do
        skip "pkg what migration $revision alone has: there is no $particulars_dir/migration-$revision.sh, so this pass shows of that migration what every upgrade must show, and nothing of what it alone is meant to change or to create"
    done
}

# previous_at REVISION: whether the schema of the previous release is at that revision
# or at a later one. The inventory is made through the API of the previous release, and
# each part of it that a release before some revision could not store, or would have
# refused, is made only where this says that the previous release has it.
previous_at() { [[ ! $previous_head < $1 ]]; }

# tables_there "NAME ...": those of the tables named that the database has, in order.
tables_there() {
    local name found=""
    for name in $1; do
        found="${found:+$found }$(sqlite_value /var/lib/hirdir/hirdir.db "SELECT name FROM sqlite_master WHERE type = 'table' AND name = '$name'")"
    done
    printf '%s' "$found"
}

# ---- the pass whose migration fails --------------------------------------------------------

failed_upgrade() {
    local witness_code planted tables_before backup good_backup command body
    local schema_before snippet_before created database=/var/lib/hirdir/hirdir.db
    local cause cause_sql said cure cure_sql table events_then events_hids found

    section "the previous release, $previous_version, with an account in it"
    previous_package
    pair_said
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
    particular before
    witness_kept

    if ! migrating; then
        skip "pkg a migration that fails stops the upgrade: $version has no migration after revision $revision_before, the schema of $previous_version, so there is nothing that could fail and this pass tested no failure. It upgrades and goes back all the same, to see that going back needs no backup"
        without_migration "$body"
        return
    fi

    # The migration is made to fail by the database, not by the package, which is
    # installed exactly as it was built. Where the new version creates a table, the
    # table it creates last is already there. Where it creates none, or where the file
    # of the migration asks for it, a trigger refuses the last thing every migration
    # does, which is to write its revision into alembic_version: by then the migration
    # has made every change it makes, to the tables and to what they hold, and all of
    # it has to be undone. A column of a name the migration adds would not do: SQLite
    # refuses it where the column is added to the table as it stands, and at the first
    # statement, with nothing to undo, and where the table is rebuilt the column is
    # taken over without a word.
    planted=""
    if [ "$fail_by" != trigger ]; then planted=$(migrations "$deb" created "$revision_before"); fi
    if [ -n "$planted" ]; then
        cause="a table named $planted, which the migration creates last, is put in its way"
        cause_sql="CREATE TABLE \"$planted\" (planted_by_package_test INTEGER)"
        said="table \"\?$planted\"\? already exists"
        cure="the table that was in the way is taken out"
        cure_sql="DROP TABLE \"$planted\""
    else
        cause="no migration of $version after revision $revision_before creates a table"
        if [ "$fail_by" = trigger ]; then cause="the file of the migration asks for it"; fi
        cause="$cause, so a trigger is put on alembic_version that refuses the new revision: the migration fails at its last statement, with everything else it does done"
        cause_sql="CREATE TRIGGER planted_by_package_test BEFORE UPDATE ON alembic_version BEGIN SELECT RAISE(ABORT, 'refused by the trigger of the package test'); END"
        said="refused by the trigger of the package test"
        cure="the trigger that refused the revision is taken out"
        cure_sql="DROP TRIGGER planted_by_package_test"
    fi
    if sqlite_run "$cause_sql" >/dev/null 2>&1; then
        pass "pkg $cause"
    else
        fail "pkg $cause"
    fi
    expect "pkg $previous_version is not disturbed by it: hirdir admin check exits 0, and the service answers" \
        "$(inside hirdir admin check >/dev/null 2>&1 && echo checked) $(local_status GET /api/v1/health/ready)" "checked 200"
    tables_before=$(sqlite_value "$database" "SELECT count(*) FROM sqlite_master WHERE type = 'table'")
    events_then=$(sqlite_value "$database" 'SELECT count(*) FROM audit_events')
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
    expect "pkg and the audit trail holds the events it held, and none that the migration had written before it failed ($events_then)" \
        "$(sqlite_value "$database" 'SELECT count(*) FROM audit_events')" "$events_then"
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
    events_then=$(table_rows audit_events "$(table_columns audit_events)")
    events_hids=$(table_read audit_events hids)
    upgrade_days=$(date -u +%F)
    if apt_get install /srv/debs/hirdir-new.deb; then
        upgrade_days="$upgrade_days $(date -u +%F)"
        pass "pkg apt upgrades hirdir $previous_version to $version"
    else
        fail "pkg apt upgrades hirdir $previous_version to $version"
        tail -n 30 "$work/apt.log"
    fi
    # Read before anything is asked of the new version: a sign-in is an event too.
    if [ -n "$writes_no_event" ]; then no_event_written "$events_then" "$events_hids"; fi
    good_backup=$(sed -n 's/^hirdir: the database as it was before this upgrade is kept at //p' "$work/apt.log")
    expect "pkg dpkg holds hirdir $version as installed" \
        "$(inside dpkg-query -W -f "\${Version} \${Status}" hirdir 2>&1)" "$version install ok installed"
    expect "pkg the schema is at revision $head" "$(revision_now)" "$head"
    check "pkg hirdir admin check exits 0" inside hirdir admin check
    created=$(migrations "$deb" tables "$revision_before")
    if [ -n "$created" ]; then
        expect "pkg every table that the migration creates is there now ($created)" "$(tables_there "$created")" "$created"
        if [ -z "$planted" ]; then
            expect "pkg and nothing of the trigger is left" \
                "$(sqlite_value "$database" "SELECT count(*) FROM sqlite_master WHERE type = 'trigger'")" 0
        fi
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
    tables_carried "after the upgrade that went through," migrated

    # The settings file, which nobody edited in this pass, as the upgrade pass has one
    # that the operator edited: every line of it stays, and the settings of the new
    # version that it lacks are put in, each at the end of its table. A line that only
    # says more of a setting the file has is not put in.
    new_settings >"$work/new-settings.txt"
    found=$(settings_kept "$work/settings-before-failure.toml")
    if [ -s "$work/new-settings.txt" ]; then
        expect "pkg the settings file, which nobody edited, holds every line it had, each as it was and in its order, and among them every setting that $version has and $previous_version had not ($(cut -f1 "$work/new-settings.txt" | xargs))" \
            "$found $(cut -f2 "$work/new-settings.txt" | grep -cvxF -f "$work/settings-now.toml" || true)" "kept more 0"
    else
        expect "pkg the settings file, which nobody edited, is as $previous_version wrote it: $version has no setting that it had not" \
            "$found" "kept same"
    fi
    expect "pkg and hirdir-setup --settings finds nothing to change in it" \
        "$(inside hirdir-setup --settings --yes 2>&1)" \
        "Nothing to change: /etc/hirdir/config.toml has every setting of this version of hirdir."

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

# without_migration SIGN_IN_BODY: what the failed-upgrade pass does for a release that
# has no migration, once it has said in its SKIP line that no failure was tested. It
# upgrades, with no nginx installed, and goes back. The schema is the same on both
# sides, so the older package reads the database as the newer one leaves it: going back
# is installing the older package again, with nothing to restore, and what was entered
# since the upgrade stays.
without_migration() {
    local body=$1 backup database=/var/lib/hirdir/hirdir.db schema_before events_before events_hids

    section "the upgrade to $version, which has no migration"
    schema_before=$(schema_sum "$database")
    events_before=$(table_rows audit_events "$(table_columns audit_events)")
    events_hids=$(table_read audit_events hids)
    if apt_get install /srv/debs/hirdir-new.deb; then
        pass "pkg apt upgrades hirdir $previous_version to $version"
    else
        fail "pkg apt upgrades hirdir $previous_version to $version"
        tail -n 30 "$work/apt.log"
    fi
    backup=$(sed -n 's/^hirdir: the database as it was before this upgrade is kept at //p' "$work/apt.log")
    expect "pkg dpkg holds hirdir $version as installed" \
        "$(inside dpkg-query -W -f "\${Version} \${Status}" hirdir 2>&1)" "$version install ok installed"
    check "pkg the upgrade kept a backup of the database all the same, and says where (${backup:-nowhere})" \
        inside test -s "${backup:-/nonexistent}"
    expect "pkg the schema is at revision $head, as it was, and is the same statement for statement" \
        "$(revision_now) $(schema_sum "$database")" "$revision_before $schema_before"
    no_event_written "$events_before" "$events_hids"
    check "pkg hirdir admin check exits 0" inside hirdir admin check
    if wait_local_ready; then
        pass "pkg $version serves"
    else
        fail "pkg $version serves"
    fi
    expect "pkg the Admin signs in with the access code from before" \
        "$(local_status POST /api/v1/auth/sign-in "$body")" 200
    tables_carried "after the upgrade,"
    witness_carried fields "after the upgrade,"
    # Something that is no part of the inventory, so that its tables stay as they were.
    api POST /user-groups '{"name": "Entered since the upgrade"}'
    expect "pkg a user group is entered with $version" "$status" 201

    # What docs/install.md says of going back from a release that changed no schema.
    section "going back from $version to $previous_version, with no migration between them"
    if apt_get install --allow-downgrades /srv/debs/hirdir-previous.deb; then
        pass "pkg apt install --allow-downgrades puts $previous_version back, and it does not stop at the database: there is nothing in it that $previous_version cannot read"
    else
        fail "pkg apt install --allow-downgrades puts $previous_version back, and it does not stop at the database: there is nothing in it that $previous_version cannot read"
        tail -n 20 "$work/apt.log"
    fi
    expect "pkg dpkg holds hirdir $previous_version as installed, and the service runs" \
        "$(inside dpkg-query -W -f "\${Version} \${Status}" hirdir 2>&1) $(inside systemctl is-active hirdir.service 2>&1)" \
        "$previous_version install ok installed active"
    expect "pkg the schema is at revision $revision_before still, the same statement for statement" \
        "$(revision_now) $(schema_sum "$database")" "$revision_before $schema_before"
    check "pkg hirdir admin check of $previous_version exits 0" inside hirdir admin check
    if wait_local_ready; then
        pass "pkg $previous_version serves again, with no backup put back"
    else
        fail "pkg $previous_version serves again, with no backup put back"
    fi
    expect "pkg the Admin signs in with the access code from before" \
        "$(local_status POST /api/v1/auth/sign-in "$body")" 200
    tables_carried "gone back to $previous_version,"
    witness_carried exact "gone back to $previous_version,"
    api GET /user-groups
    expect "pkg and what was entered with $version is still there: nothing was restored" \
        "$status $(json 'sum(g["name"] == "Entered since the upgrade" for g in d)')" "200 1"
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
witness_full=""
witness_items=()
witness_groups=()
witness_stack=""
witness_cluster=""
witness_domain=""
witness_endpoint=""
witness_lone=""
witness_moment=""
witness_own=""
witness_untested=""
witness_day=""
witness_tables=""
witness_switch=""
witness_third=""
witness_retired=""
witness_site=""
witness_room=""
witness_contracts=""
witness_renewed=""
witness_circuited=""
witness_referenced=""
# The files that witness_references uploads, as "HID:the file on this host", whose
# content must come back byte for byte.
witness_files=()
# What came after the groups, which witness_places, witness_money, witness_renewals,
# witness_circuits and witness_references make where the previous release has it. Each list is kept and
# compared record for record, as "NAME PATH", and each answer that is worked out of the
# records, a tree or a report, by what one expression makes of it, as
# "NAME|PATH|EXPRESSION|what it is, in words".
# The records are noted in the order in which the upgrade pass takes them out again,
# as "what/HID".
witness_lists=()
witness_answers=()
witness_undo=()
declare -A answers_before=()
members_made=0
addresses_made=0
declare -A columns_before=() keys_before=() rows_before=()
tables_then=0
schema_then=""
events_then=""
events_hids_then=""
counted_before=""
cluster_before=""
lone_before=""
duplicates_before=""
# What the inventory expects of the previous release where a release once did otherwise.
# The file of the migration or of the release that changed it says how it was before.
#   the support weight given to the first model, and what the new version makes of it
witness_weight=1.25
witness_weight_after=1.25
#   the moment kept for 09:00 on 3 November 2026 written with no zone, and its words
zoneless_moment=2026-11-03T14:00:00Z
zoneless_said="09:00 in the application's time zone, New York here, which is 14:00 in UTC"
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

# witness_inventory: with the previous release, through its API, make what an upgrade
# to the new one could harm. A migration that adds a column to the items table may
# rebuild that table on SQLite, so the items made here have every kind of value between
# them: serial numbers, asset tags, a MAC address, tags, overrides of what
# the catalog gives, a state reached by moves, a draft and a retired one. A previous
# release from before there was an inventory is given none, and $witness_entry stays
# empty.
witness_inventory() {
    local vendor move made rma row_version=1

    api GET /vendors
    [ "$status" = 200 ] || return 0
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
    # for it. The other two are reasons for a replacement, a list that the first
    # releases offered and used for nothing, and that the later ones load with their
    # defaults. rma is one of those defaults: where the previous release has it, the
    # site gives it a label of its own, and where it has not, the site enters it.
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
    witness_retired=$(json_field hid)
    witness_items+=("$witness_retired")
    api POST "/items/$witness_retired/retire" '{"row_version": 1}'
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

# witness_said ITEM JSON: say something more of an item that witness_made made: its
# condition, or what is observed of it. JSON is the fields, without the row_version.
# Prints the status and what the item then says of itself.
witness_said() {
    api GET "/items/$1"
    api PATCH "/items/$1" "{\"row_version\": $(json_field row_version), $2}"
    echo "$status $(json '[d["condition"], d["observed_status"], d["observed_at"], d["health"]["value"]]')"
}

# witness_structure: the records that came after the first inventory, made through the
# API of the previous release for an upgrade to carry: minor items two deep; a stack
# with the master that is intended and another that is seen, the number of members it
# is to have and what is observed of it; a cluster that says how it is managed; a
# controller domain with a cluster within it; a stack that is one switch alone; a group
# that is a draft; a replacement; memberships that were ended, one of them by a move
# out of the team's hands; conditions, one of the site's own; observations, with a
# moment that names a zone and one that names none; networks, and addresses of items
# and of groups, with a primary management address of each family on one item.
#
# Each kind is made where the previous release can hold it. One from before there were
# groups is given none of this, and $witness_groups stays empty. What came with
# revision 0006 is made where previous_at says that the previous release is there: the
# condition of an item and what is observed of it, how a cluster is managed and how
# many members a group is to have, the master that is seen, a stack of one switch, a
# membership that ends when its item leaves the team's hands, and a primary address of
# each family. Every name is invented, and the addresses are from the ranges reserved
# for documentation.
# shellcheck disable=SC2034  # Some of what it notes is for the files of package-test.d.
witness_structure() {
    local s1 s2 s3 s4 s9 module f1 f2 w1 w2 w3 a1 a2 d1 domain wlc member mgmt dmz made day row_version good
    local more wanted addresses
    local items_then=${#witness_items[@]}

    api GET '/device-groups?limit=1'
    [ "$status" = 200 ] || return 0

    # Minor items beneath a switch: a power supply, and an optic in a module, two deep.
    witness_made UWN0000S001 "$witness_entry" '"lifecycle_state": "Prod", "annual_support_cost": "1200.00"'
    s1=$made_hid
    witness_switch=$s1
    witness_made UWN0000P001 "$witness_second" "\"parent_item_hid\": \"$s1\", \"position\": \"PS-A\", \"asset_tag\": \"UW-AT-0101\", \"est_value\": \"450.00\""
    made=$status
    witness_made UWN0000M001 "$witness_second" "\"parent_item_hid\": \"$s1\", \"position\": \"NM-1\""
    module=$made_hid
    made="$made $status"
    witness_made UWN0000T001 "$witness_second" "\"parent_item_hid\": \"$module\", \"position\": \"1\", \"owner_hid\": \"$witness_owner\""
    expect "pkg $previous_version holds minor items: a power supply and a module in a switch, and an optic in the module, two deep, with an owner of its own" \
        "$made $status $(json '[d["is_major"], d["depth"], d["position"]]')" '201 201 201 [false, 2, "1"]'

    # A stack of four with a master, which is to have four members and is observed
    # online, where the previous release can say so. A fourth switch joins and leaves
    # again, and the second is replaced, so the stack has had five members and has
    # three. Then its third switch is seen to be master, at a moment that is written
    # with no zone, where that can be said too.
    witness_made UWN0000S002 "$witness_entry" '"lifecycle_state": "Prod"'
    s2=$made_hid
    witness_made UWN0000S003 "$witness_entry" '"lifecycle_state": "Prod"'
    s3=$made_hid
    witness_third=$s3
    witness_made UWN0000S004 "$witness_entry" '"lifecycle_state": "Prod"'
    s4=$made_hid
    more=""
    if previous_at 0006; then
        more='"expected_members": 4, "observed_status": "online", "observed_at": "2026-11-02T15:00:00Z", '
    fi
    api POST /device-groups "{\"type\": \"stack\", \"name\": \"upgrade-stack\", \"hostname\": \"upgrade-stack\", \"fqdn\": \"upgrade-stack.example.net\", \"owner_hid\": \"$witness_owner\", \"tags\": [\"upgrade-witness\"], $more\"members\": [{\"item_hid\": \"$s1\", \"role\": \"master\", \"position\": 1}, {\"item_hid\": \"$s2\", \"role\": \"member\", \"position\": 2}, {\"item_hid\": \"$s3\", \"role\": \"member\", \"position\": 3}, {\"item_hid\": \"$s4\", \"role\": \"member\", \"position\": 4, \"joined_on\": \"2026-03-02\"}]}"
    expect "pkg a stack of four switches with a master, a host name, an owner and a tag, which shows the master's serial number" \
        "$status $(json '[d["type"], d["member_count"], d["serial_number"]]')" '201 ["stack", 4, "UWN0000S001"]'
    if previous_at 0006; then
        expect "pkg and which is to have four members and is observed online" \
            "$(json '[d["expected_members"], d["observed_status"], d["observed_at"]]')" '[4, "online", "2026-11-02T15:00:00Z"]'
    fi
    witness_stack=$(json_field hid)
    witness_groups=("$witness_stack")
    members_made=4
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
    witness_day=$day
    witness_items+=("$s9")
    members_made=$((members_made + 1))
    api GET "/device-groups/$witness_stack/members?include_past=true"
    expect "pkg the stack has three members now and has had five: two memberships are ended, each with its day" \
        "$status $(json '[sum(1 for m in d["items"] if not m["left_on"]), sorted(m["left_on"] for m in d["items"] if m["left_on"])]')" \
        "200 [3, $(python3 -c 'import json, sys; print(json.dumps(sorted(["2026-09-30", sys.argv[1]])))' "$day")]"
    if previous_at 0006; then
        api GET "/device-groups/$witness_stack"
        api PATCH "/device-groups/$witness_stack" "{\"row_version\": $(json_field row_version), \"observed_master_hid\": \"$s3\", \"master_observed_at\": \"2026-11-03T09:00:00\"}"
        expect "pkg its third switch is seen to be master, which is not the one intended: the stack shows that switch's serial number, and is short of a member" \
            "$status $(json '[d["serial_number"], d["serial_source"], d["master"]["serial_number"], d["master_as_intended"], d["health"]["value"]]')" \
            '200 ["UWN0000S003", "observed", "UWN0000S001", false, "degraded"]'
        # The moment was written with no zone, and is read in the application's time
        # zone, America/New_York here. A release that read it otherwise has that in
        # its file, which sets $zoneless_moment.
        expect "pkg the moment it was seen at, written as 09:00 with no zone, is kept by $previous_version as $zoneless_said" \
            "$(json_field master_observed_at)" "$zoneless_moment"
    fi

    # A cluster of two. Where the previous release can say how a cluster is managed,
    # each member is managed at its own address, which makes two managed nodes. Where
    # it cannot, a cluster is one managed node.
    witness_made UWN0000F001 "$witness_second" '"lifecycle_state": "Prod"'
    f1=$made_hid
    witness_made UWN0000F002 "$witness_second" '"lifecycle_state": "Prod"'
    f2=$made_hid
    more=""
    if previous_at 0006; then more='"managed_as": "members", '; fi
    api POST /device-groups "{\"type\": \"cluster\", \"name\": \"upgrade-cluster\", \"hostname\": \"upgrade-fw\", $more\"members\": [{\"item_hid\": \"$f1\", \"role\": \"active\"}, {\"item_hid\": \"$f2\", \"role\": \"standby\"}]}"
    expect "pkg a cluster of two, one active and one standby" \
        "$status $(json '[d["type"], d["member_count"]]')" '201 ["cluster", 2]'
    if previous_at 0006; then
        expect "pkg which is managed by its members" "$(json_field managed_as)" members
    fi
    witness_cluster=$(json_field hid)
    witness_groups+=("$witness_cluster")
    members_made=$((members_made + 2))

    # A controller domain: a controller by itself, a pair of controllers as a cluster
    # within it, and two endpoints. An endpoint lists its controllers, the one that is
    # in no cluster first. One endpoint then leaves the team's hands, which ends its
    # membership on that day.
    api POST /device-groups '{"type": "controller_domain", "name": "upgrade-wireless"}'
    made=$status
    wanted=201
    domain=$(json_field hid)
    witness_domain=$domain
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
    more=""
    if previous_at 0006; then more='"expected_members": 2, '; fi
    api POST /device-groups "{\"type\": \"cluster\", \"name\": \"upgrade-wlc\", \"parent_group_hid\": \"$domain\", $more\"members\": [{\"item_hid\": \"$w2\", \"role\": \"active\"}, {\"item_hid\": \"$w3\", \"role\": \"standby\"}]}"
    made="$made $status"
    wanted="$wanted 201"
    if previous_at 0006; then
        made="$made $(json_field managed_as)"
        wanted="$wanted one"
    fi
    wlc=$(json_field hid)
    witness_groups+=("$wlc")
    api POST "/device-groups/$domain/members" "{\"members\": [{\"item_hid\": \"$w1\", \"role\": \"controller\"}, {\"item_hid\": \"$a1\", \"role\": \"endpoint\"}, {\"item_hid\": \"$a2\", \"role\": \"endpoint\"}]}"
    made="$made $status"
    members_made=$((members_made + 5))
    api GET "/items/$a1"
    expect "pkg a controller domain with a controller by itself, a cluster of two controllers within it, which is managed as one where that is said of a cluster, and two endpoints: an endpoint names its three controllers" \
        "$made $(json '[c["serial_number"] for c in d["controllers"]]')" \
        "$wanted 201 [\"UWN0000W001\", \"UWN0000W002\", \"UWN0000W003\"]"
    # A release before revision 0006 let the membership of such an item stand, and
    # migration 0006 ends it: the file of that migration makes the move there.
    witness_endpoint=$a2
    if previous_at 0006; then
        row_version=1
        for made in Pending-Removal:decommissioned Released:disposed; do
            api POST "/items/$a2/transition" "{\"to\": \"${made%:*}\", \"reason\": \"${made#*:}\", \"row_version\": $row_version}"
            row_version=$(json_field row_version)
        done
        made="$status $(json '[d["lifecycle_state"], d["groups"]]')"
        api GET "/device-groups/$domain/members?include_past=true"
        expect "pkg one endpoint is moved to Released, which ends its membership of the domain on that day" \
            "$made $(json '[[m["joined_on"] <= m["left_on"]] for m in d["items"] if m["item_hid"] == "'"$a2"'"]') $(json 'sum(1 for m in d["items"] if not m["left_on"])')" \
            '200 ["Released", []] [[true]] 2'
    fi

    # A stack that is one switch alone, with no master, where the previous release
    # takes one, and a group that is a draft.
    if previous_at 0006; then
        witness_made UWN0000D001 "$witness_entry" '"lifecycle_state": "Prod"'
        d1=$made_hid
        api POST /device-groups "{\"type\": \"stack\", \"name\": \"upgrade-lone\", \"members\": [{\"item_hid\": \"$d1\", \"position\": 1}]}"
        expect "pkg a stack that is one switch alone, with no master and so no serial number, which says that it is degraded for it" \
            "$status $(json '[d["member_count"], d["serial_number"], d["health"]]')" \
            '201 [1, null, {"reasons": ["it is one switch alone"], "value": "degraded"}]'
        witness_lone=$(json_field hid)
        witness_groups+=("$witness_lone")
        members_made=$((members_made + 1))
    fi
    api POST /device-groups '{"type": "custom", "name": "upgrade-lab", "record_status": "draft", "tags": ["upgrade-spare"]}'
    expect "pkg and a group of the site's own kind that is a draft, with a tag and no member" \
        "$status $(json '[d["type"], d["record_status"], d["member_count"]]')" '201 ["custom", "draft", 0]'
    witness_groups+=("$(json_field hid)")
    expect "pkg every one of the $((${#witness_items[@]} - items_then)) items of these groups was made" "$not_made" 0

    if previous_at 0006; then
        # Conditions: the list has its six, and the site adds one of its own and gives
        # one of the six a label of its own.
        api POST /choices '{"list": "item_condition", "value": "in-repair", "label": "Away for repair"}'
        made=$status
        api GET '/choices?list=item_condition'
        good=$(json '([c["hid"] + " " + str(c["row_version"]) for c in d if c["value"] == "good"] or ["none 0"])[0]')
        api PATCH "/choices/${good% *}" "{\"row_version\": ${good#* }, \"label\": \"Works as it should\"}"
        expect "pkg a condition of the site's own in the item_condition list, in-repair, and a label of the site's for good" \
            "$made $status $(json_field label)" "201 200 Works as it should"

        # What is said of items: a condition, and what is observed, with the health
        # that follows. One moment names its zone and one names none.
        expect "pkg a switch whose condition is good and which is observed online, at a moment that names its zone: its health is good" \
            "$(witness_said "$s1" '"condition": "good", "observed_status": "online", "observed_at": "2026-11-02T15:00:00Z"')" \
            '200 ["good", "online", "2026-11-02T15:00:00Z", "good"]'
        expect "pkg a switch whose condition is degraded, and a member of the cluster that is observed unreachable, which is failed" \
            "$(witness_said "$s3" '"condition": "degraded"') $(witness_said "$f2" '"observed_status": "unreachable"' | sed -E 's/"20[0-9T:.-]+Z"/"NOW"/')" \
            '200 ["degraded", null, null, "degraded"] 200 [null, "unreachable", "NOW", "failed"]'
        witness_moment=$f1
        expect "pkg the other member is observed present at 09:00, written with no zone: $previous_version keeps that as $zoneless_said" \
            "$(witness_said "$f1" '"observed_status": "present", "observed_at": "2026-11-03T09:00:00"')" \
            "200 [null, \"present\", \"$zoneless_moment\", \"good\"]"
        witness_own=$w1
        witness_untested=$a1
        expect "pkg a controller with the condition of the site's own, and an endpoint that is untested: the health of each is not known" \
            "$(witness_said "$w1" '"condition": "in-repair"') $(witness_said "$a1" '"condition": "untested"')" \
            '200 ["in-repair", null, null, "unknown"] 200 ["untested", null, null, "unknown"]'
    fi

    # Networks and addresses: of items and of groups, both families, one address under
    # two networks, one twice under the same, and on the first switch a primary
    # management address of each family, where the previous release holds one of each:
    # before revision 0006 a record had one primary address in all.
    api POST /networks '{"label": "upgrade-mgmt"}'
    made=$status
    mgmt=$(json_field hid)
    api POST /networks '{"label": "upgrade-dmz", "kind": "vrf"}'
    made="$made $status"
    wanted="201 201"
    dmz=$(json_field hid)
    addresses=(
        "\"item_hid\": \"$s1\", \"address\": \"192.0.2.101\", \"network_hid\": \"$mgmt\", \"is_primary\": true"
        "\"item_hid\": \"$s1\", \"address\": \"2001:0DB8:0000:0001:0000:0000:0000:0101\", \"role\": \"loopback\""
        "\"item_hid\": \"$s3\", \"address\": \"192.0.2.101\", \"network_hid\": \"$mgmt\", \"role\": \"secondary\""
        "\"item_hid\": \"$f1\", \"address\": \"192.0.2.101\", \"network_hid\": \"$dmz\""
        "\"group_hid\": \"$witness_stack\", \"address\": \"192.0.2.100\", \"network_hid\": \"$mgmt\", \"is_primary\": true"
        "\"group_hid\": \"$witness_cluster\", \"address\": \"203.0.113.50\", \"network_hid\": \"$dmz\", \"role\": \"virtual\""
        "\"group_hid\": \"$witness_cluster\", \"address\": \"2001:db8:0:1::50\", \"is_primary\": true"
    )
    if previous_at 0006; then
        addresses+=("\"item_hid\": \"$s1\", \"address\": \"2001:0DB8:0000:0001:0000:0000:0000:0111\", \"network_hid\": \"$mgmt\", \"is_primary\": true")
    fi
    for member in "${addresses[@]}"; do
        api POST /addresses "{$member}"
        made="$made $status"
        wanted="$wanted 201"
    done
    addresses_made=${#addresses[@]}
    expect "pkg two networks and $addresses_made addresses: of items and of groups, of both families, one address under two networks and twice under one of them" \
        "$made" "$wanted"
    if previous_at 0006; then
        api GET "/items/$s1"
        expect "pkg the first switch has a primary management address of each family, and a loopback address that is not primary" \
            "$status $(json 'sorted([a["family"], a["address"], a["role"], a["is_primary"]] for a in d["addresses"])')" \
            '200 [[4, "192.0.2.101", "management", true], [6, "2001:db8:0:1::101", "loopback", false], [6, "2001:db8:0:1::111", "management", true]]'
    fi
    expect "pkg GET /reports/duplicates of $previous_version lists the pair that is under one network" \
        "$(duplicates 192.0.2.101)" '[["upgrade-mgmt", 2, 2]]'

    # What the previous release counts of the cluster, and of the stack of one switch.
    # witness_kept keeps these, and what all the items come to, for the new version to
    # count the same.
    if previous_at 0006; then
        expect "pkg $previous_version counts the cluster as two managed nodes of two components, and the switch that is alone in its stack with its whole support weight of 1.25" \
            "$(counted_now '?filter=group.name:eq:upgrade-cluster') $(counted_now '?filter=group.name:eq:upgrade-lone')" \
            '[2, 2, 2, 1.0, "0.00", "1800.00"] [1, 1, 1, 1.25, "18000.00", "0.00"]'
    else
        expect "pkg $previous_version counts the cluster as one managed node of two components, with the support weight and the cost of two" \
            "$(counted_now '?filter=group.name:eq:upgrade-cluster')" '[2, 2, 1, 1.0, "0.00", "1800.00"]'
    fi

    # What came with revisions 0007 to 0011, where the previous release has it.
    if previous_at 0007; then witness_places; fi
    if previous_at 0008; then witness_money; fi
    if previous_at 0009; then witness_renewals; fi
    if previous_at 0010; then witness_circuits; fi
    if previous_at 0011; then witness_references; fi
}

# day_from_today DAYS: the day that many days after today, or before it. The days that
# are asked for are well clear of today, so that the application's day and this
# host's agree on which side of today each of them is.
day_from_today() {
    python3 -c 'import sys
from datetime import date, timedelta
print((date.today() + timedelta(days=int(sys.argv[1]))).isoformat())' "$1"
}

# said_of HID LIST JSON: change a record of a list that is already made, as
# witness_said does for an item: JSON is the fields, without the row_version. Prints
# the status.
said_of() {
    api GET "/$2/$1"
    api PATCH "/$2/$1" "{\"row_version\": $(json_field row_version), $3}"
    echo "$status"
}

# witness_places: what came with revision 0007, made through the API of the previous
# release for an upgrade to carry: a region with a region beneath it, a site with a
# street address that deliveries go to, a site that is a draft, a building with a room
# in it and a room of the draft site; two contacts, one of them the technical contact
# of the region and the other the shipping contact of the site, and a building where
# nobody takes shipments; two operators, one with nobody behind it; and the two people
# of the owner from before. Then what was made before is put there: the item with
# every value is in the room and has an operator of its own, the first item is planned
# for the room of the draft site, the first stack is in the building with an operator
# of its own, so that its switches and their minor items are there and have that
# operator from it, and the site has the open operator. A migration that makes the
# items table anew, or a table that refers to a place, has all of that to carry.
#
# witness_structure runs this where previous_at says that the previous release is at
# revision 0007, after it has made its own, so $witness_stack is set. Every name is
# invented.
witness_places() {
    local land north site new building room hall pat sam made wanted busy open hid

    api POST /regions '{"name": "Upgrade Land", "code": "UWL", "ship_address1": "5 Witness Road", "ship_city": "Riverton", "ship_instructions": "Ring the upgrade desk a day ahead"}'
    made=$status
    land=$(json_field hid)
    api POST /regions "{\"name\": \"North\", \"parent_region_hid\": \"$land\"}"
    made="$made $status"
    north=$(json_field hid)
    api POST /sites "{\"name\": \"Upgrade Site\", \"region_hid\": \"$north\", \"code\": \"UWS\", \"address1\": \"1 Witness Square\", \"city\": \"Riverton\", \"state\": \"NY\", \"postal_code\": \"00000\", \"country\": \"US\", \"ship_same_as_address\": true, \"tags\": [\"upgrade-witness\"]}"
    made="$made $status"
    site=$(json_field hid)
    witness_site=$site
    api POST /sites "{\"name\": \"Upgrade New Site\", \"region_hid\": \"$north\", \"record_status\": \"draft\"}"
    made="$made $status"
    new=$(json_field hid)
    api POST /locations "{\"name\": \"Building 7\", \"site_hid\": \"$site\", \"kind\": \"building\"}"
    made="$made $status"
    building=$(json_field hid)
    api POST /locations "{\"name\": \"Room 701\", \"site_hid\": \"$site\", \"parent_location_hid\": \"$building\", \"kind\": \"room\", \"ship_instructions\": \"Hand to the room keeper\"}"
    made="$made $status"
    room=$(json_field hid)
    witness_room=$room
    api POST /locations "{\"name\": \"Hall\", \"site_hid\": \"$new\", \"kind\": \"room\"}"
    hall=$(json_field hid)
    expect "pkg $previous_version holds places: a region with a region beneath it, a site there whose deliveries go to its street address, a site that is a draft, a building with a room in it, and a room of the draft site, each with its path" \
        "$made $status $(json_field path)" \
        "201 201 201 201 201 201 201 Upgrade Land > North > Upgrade New Site > Hall"

    api POST /contacts '{"name": "Upgrade Pat", "email": "upgrade.pat@example.net", "phone": "+1 555 0181", "organization": "Upgrade Witness Team"}'
    made=$status
    pat=$(json_field hid)
    api POST /contacts '{"name": "Upgrade Sam", "email": "upgrade.sam@example.net"}'
    made="$made $status"
    sam=$(json_field hid)
    wanted="201 201"
    for hid in "\"contact_hid\": \"$pat\", \"role\": \"technical\", \"region_hid\": \"$land\"" \
        "\"contact_hid\": \"$sam\", \"role\": \"shipping\", \"site_hid\": \"$site\"" \
        "\"role\": \"shipping\", \"location_hid\": \"$building\", \"stop_inheritance\": true"; do
        api POST /contact-assignments "{$hid}"
        made="$made $status"
        wanted="$wanted 201"
        witness_undo+=("contact-assignments/$(json_field hid)")
    done
    api POST /operators "{\"label\": \"UW7\", \"description\": \"Upgrade witness, with a person\", \"colour\": \"#1f6feb\", \"contact_hid\": \"$pat\"}"
    made="$made $status"
    busy=$(json_field hid)
    api POST /operators '{"label": "UW8"}'
    made="$made $status $(json_field is_open)"
    open=$(json_field hid)
    api POST "/owners/$witness_owner/members" "{\"contact_hid\": \"$pat\"}"
    made="$made $status $(json_field role)"
    witness_undo+=("owners/$witness_owner/members/$(json_field hid)")
    api POST "/owners/$witness_owner/members" "{\"contact_hid\": \"$sam\", \"role\": \"alternate\"}"
    # The alternate is taken out before the primary, which is not removed while
    # another person remains.
    witness_undo=("${witness_undo[@]:0:3}" "owners/$witness_owner/members/$(json_field hid)" "${witness_undo[@]:3}")
    expect "pkg and people: two contacts, the technical contact of the region, the shipping contact of the site and a building where nobody takes shipments, two operators, one with nobody behind it, and the two people of the owner from before, the first of them its primary" \
        "$made $status $(json_field role)" "$wanted 201 201 true 201 primary 201 alternate"
    witness_undo+=("operators/$busy" "operators/$open" "contacts/$pat" "contacts/$sam"
        "locations/$hall" "locations/$room" "locations/$building" "sites/$new" "sites/$site"
        "regions/$north" "regions/$land")

    # What was made before is put there.
    made=$(said_of "$witness_full" items "\"location_hid\": \"$room\", \"operator_hid\": \"$busy\"")
    made="$made $(said_of "$witness_item" items "\"planned_location_hid\": \"$hall\"")"
    made="$made $(said_of "$witness_stack" device-groups "\"location_hid\": \"$building\", \"operator_hid\": \"$open\"")"
    made="$made $(said_of "$site" sites "\"operator_hid\": \"$busy\"")"
    api GET "/items/$witness_switch"
    expect "pkg the item with every value is put in the room, with an operator of its own, the first item is planned for the room of the draft site, the first stack is put in the building, with the open operator, and the site is given the other: the first switch of the stack is where the stack is and has its operator, with nothing of its own" \
        "$made $(json '[d["location_hid"], d["operator_hid"]] + [[d["effective"][k]["label"], d["effective"][k]["source"]] for k in ("location_hid", "operator_hid")]')" \
        '200 200 200 200 [null, null, ["Upgrade Land > North > Upgrade Site > Building 7", "device_group"], ["UW8", "device_group"]]'

    witness_lists+=("regions /regions?include_drafts=true&include_archived=true&limit=1000"
        "sites /sites?include_drafts=true&include_archived=true&limit=1000"
        "locations /locations?include_drafts=true&include_archived=true&limit=1000"
        "contacts /contacts?include_drafts=true&include_archived=true&limit=1000"
        "operators /operators?include_drafts=true&include_archived=true&limit=1000"
        "contact-assignments /contact-assignments?limit=1000")
    witness_answers+=('tree|/geography/tree?include_drafts=true&include_archived=true|(lambda walk: [[walk(walk, r) for r in d["roots"]]] + [[d[k]["items"], d[k]["component_count"]] for k in ("totals", "unplaced", "hidden")])(lambda walk, n: [n["path"], n["items"], n["component_count"], n["planned"], n["planned_groups"]] + [walk(walk, c) for c in n["children"]])|GET /geography/tree counts at each place, the drafts among them, the items and the components it counted, and what is planned for each'
        "room|/locations/$room/effective|[[c[\"role\"], c[\"source\"], c[\"source_path\"], c[\"stopped\"], [p[\"name\"] for p in c[\"contacts\"]]] for c in d[\"contacts\"]] + [[d[k][\"source\"], d[k][\"value\"]] for k in (\"ship_address\", \"ship_instructions\")]|the room has in force what it had: the technical contact of the region, no shipping contact, because the search stops at its building, the street address of its site as its shipping address, and instructions of its own"
        'operators|/reports/summary?by=operator|sorted([r["label"] or "", r["items"], r["component_count"]] for r in d["rows"])|GET /reports/summary?by=operator counts the items of each operator in force, and of nobody, as it counted them')
}

# witness_money: what came with revision 0008, made through the API of the previous
# release for an upgrade to carry: a support agreement with two contracts in it, one
# of which says nothing of its own and one of which overrides what it has from the
# agreement, a contract that stands by itself and was renewed once, so that it has an
# earlier term, one that has expired, and one whose renewal is pending; a next term
# on a contract and on the agreement; coverage under them, one ended by a person, one
# of an item that was retired afterwards, which ended it, and two items under more
# than one contract; purchase requests, one with two lines, on
# one of which two items arrived, a draft and a cancelled one; external systems, one
# of them retired, and registrations of an item and of a group, one pending and one
# removed, one confirmed at a moment written with no zone; capacity lines of both
# sides, one a draft, one ended, one retired and one in a category of the site's own;
# and choices of the site's own in the list of capacity categories.
#
# witness_structure runs this where previous_at says that the previous release is at
# revision 0008, after witness_places, so the places are there. No release before
# 0.6.0 can store any of it: the upgrade to 0.6.0 starts from a release that could
# not, and this is for the upgrades after it. Every name is invented.
witness_money() {
    local vendor reseller agreement plain overriding alone expired request line system vault old
    local made wanted hid staff last_year next_year ended entry arrived pending

    last_year=$(day_from_today -200)
    next_year=$(day_from_today 400)
    ended=$(day_from_today -30)

    # Choices: one of the site's own, and a label of the site's for a default.
    api POST /choices '{"list": "capacity_category", "value": "on-call", "label": "On-call rota"}'
    made=$status
    api GET '/choices?list=capacity_category'
    staff=$(json '([c["hid"] + " " + str(c["row_version"]) for c in d if c["value"] == "staff"] or ["none 0"])[0]')
    api PATCH "/choices/${staff% *}" "{\"row_version\": ${staff#* }, \"label\": \"Our own people\"}"
    expect "pkg $previous_version holds a capacity category of the site's own, on-call, and a label of the site's for staff" \
        "$made $status $(json_field label)" "201 200 Our own people"

    # A support agreement, and contracts in it and beside it.
    api GET /vendors
    vendor=$(json '[v["hid"] for v in d["items"] if v["name"] == "Upgrade Witness Networks"][0]')
    api POST /vendors '{"name": "Upgrade Witness Reseller"}'
    made=$status
    reseller=$(json_field hid)
    api POST /agreements "{\"name\": \"Upgrade Witness Enterprise Agreement\", \"number\": \"UW-EA-0001\", \"vendor_hid\": \"$vendor\", \"reseller_hid\": \"$reseller\", \"starts_on\": \"$last_year\", \"ends_on\": \"$next_year\", \"support_level\": \"24x7, four-hour response\", \"purchase_reference\": \"UW-PO-0001\", \"account_manager\": \"Upgrade Jordan, upgrade.jordan@example.com, +1 555 0182\", \"support_contact\": \"Upgrade support desk, +1 555 0183\", \"support_url\": \"https://support.example.com/upgrade\", \"annual_cost\": \"9600.00\", \"notes\": \"Made with the release before\", \"tags\": [\"upgrade-witness\"]}"
    made="$made $status"
    agreement=$(json_field hid)
    api POST /contracts "{\"number\": \"UW-CON-1001\", \"agreement_hid\": \"$agreement\", \"purchase_reference\": \"UW-PO-0002\", \"annual_cost\": \"6100.00\"}"
    made="$made $status $(json '[d["vendor"]["name"], d["effective"]["ends_on"]["source"]]')"
    plain=$(json_field hid)
    api POST /contracts "{\"number\": \"UW-CON-1002\", \"agreement_hid\": \"$agreement\", \"ends_on\": \"$(day_from_today 300)\", \"support_level\": \"8x5, next business day\", \"tags\": [\"upgrade-spare\"]}"
    made="$made $status $(json '[d["effective"]["ends_on"]["source"], d["effective"]["support_level"]["source"], d["effective"]["support_url"]["source"]]')"
    overriding=$(json_field hid)
    api POST /contracts "{\"number\": \"UW-CON-1003\", \"vendor_hid\": \"$vendor\", \"reseller_hid\": \"$reseller\", \"starts_on\": \"$last_year\", \"ends_on\": \"$(day_from_today 60)\", \"purchase_reference\": \"UW-PO-0003\", \"annual_cost\": \"2400.00\", \"notes\": \"Stands by itself\"}"
    made="$made $status"
    alone=$(json_field hid)
    api POST /contracts "{\"number\": \"UW-CON-1004\", \"vendor_hid\": \"$vendor\", \"starts_on\": \"$(day_from_today -600)\", \"ends_on\": \"$last_year\", \"status\": \"expired\"}"
    expired=$(json_field hid)
    expect "pkg a vendor that is a reseller, a support agreement with the vendor from before, a contract in it that has its vendor and its period from the agreement, one that overrides the last day and the support level and has the rest from it, a contract that stands by itself, and one that has expired" \
        "$made $status $(json_field status)" \
        '201 201 201 ["Upgrade Witness Networks", "agreement"] 201 ["own", "own", "agreement"] 201 201 expired'

    # Purchases: a request with two lines, on one of which two items arrived, in the
    # room from before; a request that is a draft; and one that was cancelled.
    api POST /purchase-requests "{\"reference\": \"UW-REQ-1001\", \"requested_on\": \"$last_year\", \"status\": \"ordered\", \"notes\": \"Made with the release before\", \"lines\": [{\"catalog_entry_hid\": \"$witness_entry\", \"quantity\": 4, \"destination_site_hid\": \"$witness_site\", \"expected_on\": \"$next_year\"}, {\"catalog_entry_hid\": \"$witness_second\", \"quantity\": 2, \"notes\": \"Power supplies\"}]}"
    made=$status
    request=$(json_field hid)
    line=$(json 'd["lines"][0]["hid"]')
    api POST "/purchase-lines/$line/receive" "{\"row_version\": 1, \"items\": [{\"serial_number\": \"UWN0000Q001\"}, {\"serial_number\": \"UWN0000Q002\", \"asset_tag\": \"UW-AT-0202\"}], \"quantity\": 1, \"delivered_on\": \"$ended\", \"location_hid\": \"$witness_room\"}"
    made="$made $status $(json '[d["name"], d["received_quantity"], d["pending_quantity"], sorted(i["serial_number"] or i["name"] for i in d["items"])]')"
    for hid in $(json '" ".join(i["hid"] for i in d["items"])'); do witness_items+=("$hid"); done
    arrived=$(json '[i["hid"] for i in d["items"] if i["serial_number"] == "UWN0000Q002"][0]')
    api POST /purchase-requests '{"reference": "UW-REQ-1002", "status": "draft"}'
    made="$made $status"
    api POST /purchase-requests "{\"reference\": \"UW-REQ-1003\", \"status\": \"cancelled\", \"lines\": [{\"catalog_entry_hid\": \"$witness_entry\", \"quantity\": 1}]}"
    expect "pkg purchases: a request with two lines, on the first of which three of four items arrived, in the room from before, two with a serial number and one as a count, which is named for its line; a request that is a draft; and one that was cancelled" \
        "$made $status" '201 201 ["UW-REQ-1001/1", 3, 1, ["UW-REQ-1001/1-003", "UWN0000Q001", "UWN0000Q002"]] 201 201'

    # Coverage: three items under the first contract, one of which, an item that
    # arrived, is then retired, which ends no cover; one that was ended; a second
    # cover of one item under another contract; and one under the contract that has
    # expired, which covers nothing.
    api POST "/contracts/$plain/coverage" "{\"items\": [{\"item_hid\": \"$witness_full\"}, {\"item_hid\": \"$witness_switch\"}, {\"item_hid\": \"$arrived\"}, {\"item_hid\": \"$witness_third\", \"ends_on\": \"$ended\"}]}"
    made="$status $(json 'sorted([c["item"]["serial_number"], c["in_force"]] for c in d)')"
    api POST "/items/$arrived/retire" '{"row_version": 1}'
    made="$made $status"
    api POST "/contracts/$overriding/coverage" "{\"items\": [{\"item_hid\": \"$witness_third\", \"starts_on\": \"$(day_from_today -100)\"}]}"
    made="$made $status"
    api POST "/contracts/$alone/coverage" "{\"items\": [{\"item_hid\": \"$witness_switch\"}]}"
    made="$made $status"
    api POST "/contracts/$expired/coverage" "{\"items\": [{\"item_hid\": \"$witness_full\"}]}"
    made="$made $status $(json '[c["in_force"] for c in d]')"
    api POST "/contracts/$alone/renew" "{\"row_version\": 1, \"number\": \"UW-CON-2003\", \"ends_on\": \"$next_year\", \"purchase_reference\": \"UW-PO-0004\", \"annual_cost\": \"2600.00\"}"
    made="$made $status $(json '[d["number"], d["covered_items"]]')"
    api GET "/contracts/$alone/terms"
    expect "pkg coverage: four items under the first contract, one of which is then retired, which ends its cover that day, and one whose cover was ended by a person; a second cover of that one under another contract; one under the contract that has expired, which covers nothing; and the contract that stands by itself is renewed, with a new number, a new last day and a new purchase reference, and keeps its earlier term" \
        "$made $status $(json '[[t["number"], t["purchase_reference"], t["annual_cost"]] for t in d]')" \
        '201 [["UWN0000Q002", true], ["UWN0000S001", true], ["UWN0000S003", false], ["UWN0000X002", true]] 200 201 201 201 [false] 200 ["UW-CON-2003", 1] 200 [["UW-CON-1003", "UW-PO-0003", "2400.00"]]'

    # What D-150 brought: a contract whose term has ended and whose renewal is
    # pending, which covers still; a renewal that was entered early, on a contract
    # and on the agreement, each kept as the next term; and so two items that more
    # than one contract covers. The next term of the agreement begins before the last
    # day that the second contract has of its own: one that began after it would
    # leave that contract a period that ends before it starts, which is refused
    # (D-151).
    api POST /contracts "{\"number\": \"UW-CON-1005\", \"vendor_hid\": \"$vendor\", \"starts_on\": \"$(day_from_today -400)\", \"ends_on\": \"$(day_from_today -40)\", \"status\": \"renewal_pending\", \"account_manager\": \"Upgrade Jordan, +1 555 0182\"}"
    made="$status $(json '[d["covers_today"], d["lapsed"]]')"
    pending=$(json_field hid)
    api POST "/contracts/$pending/coverage" "{\"items\": [{\"item_hid\": \"$witness_third\"}]}"
    made="$made $status $(json '[c["in_force"] for c in d]')"
    api POST "/contracts/$overriding/renew" "{\"row_version\": 1, \"number\": \"UW-CON-3002\", \"starts_on\": \"$(day_from_today 301)\", \"ends_on\": \"$(day_from_today 666)\", \"annual_cost\": \"3100.00\"}"
    made="$made $status $(json '[d["number"], d["next_term"]["number"]]')"
    api POST "/agreements/$agreement/renew" "{\"row_version\": 1, \"starts_on\": \"$(day_from_today 200)\", \"ends_on\": \"$(day_from_today 766)\", \"purchase_reference\": \"UW-PO-0005\"}"
    made="$made $status $(json '[d["ends_on"], d["next_term"]["purchase_reference"]]')"
    api GET /reports/coverage
    expect "pkg a contract whose term ended forty days ago and whose renewal is pending, which covers an item still; a renewal entered early on a contract, and one on the agreement, each kept as the next term while the present one runs on; the coverage report counts three items in service as covered, two of them under more than one contract and one under the renewal that is pending, and the retired one as out of service under a contract that still runs" \
        "$made $status $(json '[d["totals"][k] for k in ("covered", "out_of_service", "overlapping", "renewal_pending")]')" \
        "201 [true, false] 201 [true] 200 [\"UW-CON-1002\", \"UW-CON-3002\"] 200 [\"$next_year\", \"UW-PO-0005\"] 200 [3, 1, 2, 1]"

    # External systems and registrations: of the first stack and of an item, one
    # pending, one confirmed at a moment written with no zone, and one removed.
    api POST /external-systems '{"name": "Upgrade Witness Watch", "kind": "monitoring", "url": "https://watch.example.net", "notes": "Made with the release before"}'
    made=$status
    system=$(json_field hid)
    api POST /external-systems '{"name": "Upgrade Witness Vault", "kind": "config_backup"}'
    made="$made $status"
    vault=$(json_field hid)
    api POST /external-systems '{"name": "Upgrade Witness Old Monitor", "kind": "monitoring"}'
    old=$(json_field hid)
    api POST "/external-systems/$old/retire" '{"row_version": 1}'
    made="$made $status"
    wanted="201 201 200"
    for hid in "\"system_hid\": \"$system\", \"group_hid\": \"$witness_stack\", \"external_id\": \"node-0001\", \"confirmed_at\": \"2026-11-02T15:00:00Z\"" \
        "\"system_hid\": \"$system\", \"item_hid\": \"$witness_full\", \"status\": \"pending\"" \
        "\"system_hid\": \"$vault\", \"item_hid\": \"$witness_full\", \"external_id\": \"upgrade-sw-02\", \"confirmed_at\": \"2026-11-03T09:00:00\"" \
        "\"system_hid\": \"$vault\", \"item_hid\": \"$witness_switch\", \"external_id\": \"upgrade-sw-01\""; do
        api POST /registrations "{$hid}"
        made="$made $status"
        wanted="$wanted 201"
    done
    api PATCH "/registrations/$(json_field hid)" '{"row_version": 1, "status": "removed"}'
    made="$made $status $(json_field status)"
    api GET "/items/$witness_full"
    expect "pkg external systems, one of them retired, and registrations: of the first stack, and of an item with two systems, pending with one and confirmed with the other at 09:00 written with no zone, which is kept as $zoneless_said; and one that was removed again" \
        "$made $(json 'sorted([x["system"]["name"], x["status"], x["confirmed_at"]] for x in d["registrations"])')" \
        "$wanted 200 removed [[\"Upgrade Witness Vault\", \"registered\", \"$zoneless_moment\"], [\"Upgrade Witness Watch\", \"pending\", null]]"

    # Capacity lines: other work, staff, a line in the category of the site's own
    # with a cost, a vendor and a site, a draft, one that has ended and one retired.
    made=""
    wanted=""
    for entry in '"side": "demand", "name": "Upgrade Witness Project", "quantity": "1", "units_each": "1.5"' \
        '"side": "supply", "category": "staff", "name": "Upgrade Witness Engineer", "quantity": "3", "units_each": "1.0"' \
        "\"side\": \"supply\", \"category\": \"on-call\", \"name\": \"Upgrade Witness Rota\", \"quantity\": \"2\", \"units_each\": \"0.25\", \"annual_cost\": \"4000.00\", \"vendor_hid\": \"$reseller\", \"site_hid\": \"$witness_site\", \"notes\": \"Made with the release before\"" \
        '"side": "supply", "category": "services", "name": "Upgrade Witness Assistant", "quantity": "1", "units_each": "1.0", "record_status": "draft"' \
        "\"side\": \"supply\", \"category\": \"professional_services\", \"name\": \"Upgrade Witness Partner\", \"quantity\": \"1\", \"units_each\": \"1.0\", \"starts_on\": \"$last_year\", \"ends_on\": \"$ended\"" \
        '"side": "supply", "category": "tools", "name": "Upgrade Witness Tooling", "quantity": "1", "units_each": "0.5"'; do
        api POST /capacity-lines "{$entry}"
        made="$made$status "
        wanted="${wanted}201 "
    done
    api POST "/capacity-lines/$(json_field hid)/retire" '{"row_version": 1}'
    made="$made$status"
    api GET /reports/capacity
    expect "pkg capacity lines: other work, staff, a line in the category of the site's own, with a cost, a vendor and a site, a draft, one that has ended and one that is retired: the supply is 3.5 units, and 4.5 with the draft, against 1.5 units of other work" \
        "$made $status $(json '[d["active"]["other_demand"], d["active"]["supply"], d["with_drafts"]["supply"]]')" \
        "${wanted}200 200 [\"1.5\", \"3.5\", \"4.5\"]"

    witness_contracts="$plain $overriding $alone $expired $pending"
    witness_undo=("contracts/$plain" "contracts/$overriding" "contracts/$alone" "contracts/$expired" "contracts/$pending"
        "agreements/$agreement" "external-systems/$system" "external-systems/$vault" "${witness_undo[@]}")
    witness_lists+=("agreements /agreements?include_drafts=true&include_archived=true&limit=1000"
        "contracts /contracts?include_drafts=true&include_archived=true&limit=1000"
        "contract-coverage /contract-coverage?limit=1000"
        "purchase-requests /purchase-requests?limit=1000"
        "purchase-lines /purchase-lines?limit=1000"
        "external-systems /external-systems?include_drafts=true&include_archived=true&limit=1000"
        "registrations /registrations?limit=1000"
        "capacity-lines /capacity-lines?include_drafts=true&include_archived=true&limit=1000")
    witness_answers+=("terms|/contracts/$alone/terms|[[t[\"number\"], t[\"starts_on\"], t[\"ends_on\"], t[\"annual_cost\"], t[\"purchase_reference\"], t[\"renewed_at\"], t[\"renewed_by_name\"]] for t in d]|the contract that was renewed has the earlier term it had, which is read from the audit trail: its number, its period, its cost, its purchase reference, and when and by whom it was renewed"
        'coverage|/reports/coverage|d["totals"]|GET /reports/coverage counts what it counted: the items in service, those of them that are covered and that are not, the one that is covered though it is retired, and those whose cover runs out soon'
        'capacity|/reports/capacity|[{k: v for k, v in d[view].items() if k != "by_category"} for view in ("active", "with_drafts")] + [[[c["category"], c["label"], c["lines"], c["units"], c["annual_cost"]] for c in d[view]["by_category"]] for view in ("active", "with_drafts")]|GET /reports/capacity answers the balance it answered, with and without the draft: demand, supply by category, the category of the site among them under its label, balance, coverage and cost'
        'by-contract|/reports/summary?by=contract|sorted([r["label"] or "", r["items"], r["component_count"]] for r in d["rows"])|GET /reports/summary?by=contract has the rows it had: an item in the row of each contract that covers it'
        "portfolio|/vendors/$vendor/portfolio|[d[\"totals\"], [[k[\"kind\"], k[\"items\"], k[\"covered\"]] for k in d[\"kinds\"]], [[m[\"pid\"], m[\"items\"], m[\"covered\"], m[\"covered_until\"]] for m in d[\"models\"]], [a[\"name\"] for a in d[\"agreements\"]], sorted(c[\"number\"] for c in d[\"contracts\"])]|the portfolio of the vendor from before is what it was: its totals, its kinds and models with what is covered of each and until when, its agreement and its contracts")
}

# witness_renewals: what came with revision 0009, made through the API of the previous
# release for an upgrade to carry: the contacts of the agreement from before, an
# account manager and a support contact, and a contract in it that names an account
# manager of its own in place of the agreement's; the flag not to renew on the second
# model, and so on its items, one of which says otherwise for itself, and on a switch
# of the first model by itself; a support agreement whose renewal is entered early with
# its two members, one of which is to have a new number, which waits on the
# agreement's next term, and one of which ends with the present term, while an
# endpoint that is not to be renewed is left behind with a cover that ends with it; a
# purchase request with a line that this inventory does not track and a line with a
# part number; a line that multiplies the engineers from before, with its target; the
# record of the capacity balance of the week, recorded by hand and then corrected;
# links on the second model, the region, the site and the room from before; and the
# renewal alert, seen by the Admin.
#
# witness_structure runs this where previous_at says that the previous release is at
# revision 0009, after witness_money, so the contracts, the places and the people are
# there. No release before 0.7.0 can store any of it: the upgrade to 0.7.0 starts from a
# release that could not, and this is for the upgrades after it. Every name is
# invented, and every address is of a domain reserved for examples.
witness_renewals() {
    local vendor agreement plain overriding wireless member ender pat sam land made hid
    local engineer start end next_start next_end record wanted undo=()
    local -A item=()

    witness_renewed=yes
    read -r plain overriding _ <<<"$witness_contracts"
    api GET '/agreements?limit=1000'
    agreement=$(json '[a["hid"] for a in d["items"] if a["number"] == "UW-EA-0001"][0]')
    vendor=$(json '[a["vendor_hid"] for a in d["items"] if a["number"] == "UW-EA-0001"][0]')
    api GET '/contacts?limit=1000'
    pat=$(json '[c["hid"] for c in d["items"] if c["email"] == "upgrade.pat@example.net"][0]')
    sam=$(json '[c["hid"] for c in d["items"] if c["email"] == "upgrade.sam@example.net"][0]')
    api GET '/regions?limit=1000'
    land=$(json '[r["hid"] for r in d["items"] if r["name"] == "Upgrade Land"][0]')
    api GET "$every_item&filter=serial_number:in:UWN0000S004,UWN0000S009,UWN0000F001,UWN0000F002,UWN0000W001,UWN0000A001"
    for hid in $(json '" ".join(i["serial_number"] + "=" + i["hid"] for i in d["items"])'); do item[${hid%=*}]=${hid#*=}; done

    # The contacts of an agreement and of a contract, each a contact record from before.
    api POST "/agreements/$agreement/contacts" "{\"contact_hid\": \"$pat\", \"role\": \"account_manager\"}"
    made=$status
    undo+=("agreements/$agreement/contacts/$(json_field hid)")
    api POST "/agreements/$agreement/contacts" "{\"contact_hid\": \"$sam\", \"role\": \"support_contact\"}"
    made="$made $status"
    undo+=("agreements/$agreement/contacts/$(json_field hid)")
    api POST "/contracts/$overriding/contacts" "{\"contact_hid\": \"$sam\", \"role\": \"account_manager\"}"
    made="$made $status"
    undo+=("contracts/$overriding/contacts/$(json_field hid)")
    api GET "/contracts/$plain"
    made="$made $(json '[[c["contact"]["name"] for c in d["effective"][k]["value"]] + [d["effective"][k]["source"]] for k in ("account_managers", "support_contacts")]')"
    api GET "/contracts/$overriding"
    expect "pkg $previous_version holds the contacts of an agreement and of a contract: the agreement from before names an account manager and a support contact, a contract in it that names none has both from it, and the contract that names an account manager of its own has that one in place of the agreement's, and the support contact from it" \
        "$made $(json '[[c["contact"]["name"] for c in d["effective"][k]["value"]] + [d["effective"][k]["source"]] for k in ("account_managers", "support_contacts")]')" \
        '201 201 201 [["Upgrade Pat", "agreement"], ["Upgrade Sam", "agreement"]] [["Upgrade Sam", "own"], ["Upgrade Sam", "agreement"]]'

    # The flag not to renew, on the second model and so on its items, of which the
    # first of the cluster says otherwise for itself, and on a switch of the first model
    # by itself, which no contract covers. The second model has its links as well.
    api GET "/catalog-entries/$witness_second"
    api PATCH "/catalog-entries/$witness_second" "{\"row_version\": $(json_field row_version), \"do_not_renew\": true, \"links\": [{\"url\": \"https://docs.example.com/uw-24s/datasheet.pdf\", \"text\": \"Data sheet\"}, {\"url\": \"https://docs.example.com/uw-24s\", \"text\": \"\"}]}"
    made="$status $(json '[d["do_not_renew"], [[l["text"], l["url"]] for l in d["links"]]]')"
    made="$made $(said_of "${item[UWN0000F001]}" items '"do_not_renew": false') $(said_of "${item[UWN0000S004]}" items '"do_not_renew": true')"
    api GET "$every_item&filter=serial_number:in:UWN0000F001,UWN0000F002,UWN0000S003,UWN0000S004&sort=serial_number"
    expect "pkg the flag not to renew: on the second model, whose items have it from there but for the first of the cluster, which says otherwise for itself; and on a switch of the first model by itself, while another of that model has the model's, which is not set; the second model has two links, one with no text" \
        "$made $(json '[[i["serial_number"], i["do_not_renew"], i["effective"]["do_not_renew"]["value"], i["effective"]["do_not_renew"]["source"]] for i in d["items"]]')" \
        '200 [true, [["Data sheet", "https://docs.example.com/uw-24s/datasheet.pdf"], ["", "https://docs.example.com/uw-24s"]]] 200 200 [["UWN0000F001", false, false, "own"], ["UWN0000F002", null, true, "catalog"], ["UWN0000S003", null, false, "catalog"], ["UWN0000S004", true, true, "own"]]'

    # A support agreement whose renewal is entered early, with its two members. The
    # first is to have a new number with the next term, which waits on it; it covers
    # the switch that took the place of one in the first stack, which follows, and an
    # endpoint that is not to be renewed, which is left behind: its cover ends with the
    # present term. The second ends with the present term, with the agreement's dates
    # as its own, and covers a controller.
    start=$(day_from_today -200)
    end=$(day_from_today 80)
    next_start=$(day_from_today 81)
    next_end=$(day_from_today 446)
    api POST /agreements "{\"name\": \"Upgrade Witness Wireless Agreement\", \"number\": \"UW-EA-0003\", \"vendor_hid\": \"$vendor\", \"starts_on\": \"$start\", \"ends_on\": \"$end\", \"support_level\": \"8x5, next business day\"}"
    made=$status
    wireless=$(json_field hid)
    api POST /contracts "{\"number\": \"UW-CON-1007\", \"agreement_hid\": \"$wireless\", \"annual_cost\": \"700.00\"}"
    made="$made $status"
    member=$(json_field hid)
    api POST /contracts "{\"number\": \"UW-CON-1008\", \"agreement_hid\": \"$wireless\"}"
    made="$made $status"
    ender=$(json_field hid)
    api POST "/contracts/$member/coverage" "{\"items\": [{\"item_hid\": \"${item[UWN0000S009]}\"}, {\"item_hid\": \"${item[UWN0000A001]}\"}]}"
    made="$made $status"
    api POST "/contracts/$ender/coverage" "{\"items\": [{\"item_hid\": \"${item[UWN0000W001]}\"}]}"
    made="$made $status"
    api POST "/agreements/$wireless/renew" "{\"row_version\": 1, \"starts_on\": \"$next_start\", \"ends_on\": \"$next_end\", \"purchase_reference\": \"UW-PO-0009\", \"members\": [{\"contract_hid\": \"$member\", \"renewal\": \"new_number\", \"number\": \"UW-CON-2007\", \"annual_cost\": \"750.00\"}, {\"contract_hid\": \"$ender\", \"renewal\": \"ends\"}]}"
    made="$made $status $(json '[[m["number"], m["renewal"], m["left_behind"]] for m in d["members"]] + [d["left_behind"], d["ends_on"], d["next_term"]["starts_on"]]')"
    api GET "/contracts/$member"
    made="$made | $(json '[d["number"], d["ends_with_term"], d["effective"]["ends_on"]["value"], d["next_term"]["number"], d["next_term"]["starts_on"], d["next_term"]["with_agreement"]]')"
    api GET "/contracts/$ender"
    made="$made $(json '[d["number"], d["ends_with_term"], d["next_term"], d["starts_on"], d["ends_on"], d["agreement"]["name"]]')"
    api GET "/contracts/$member/coverage"
    expect "pkg a support agreement whose renewal is entered early with its two members: the first keeps its number and its period, and the new number waits on the agreement's next term; it covers a switch, which follows, and an endpoint that is not to be renewed, which is left behind, its cover ending with the present term; the second ends with the present term, with the agreement's dates as its own, and stays in the agreement" \
        "$made $(json 'sorted([c["item"]["serial_number"], c["ends_on"]] for c in d["items"])')" \
        "201 201 201 201 201 200 [[\"UW-CON-2007\", \"new_number\", 1], [\"UW-CON-1008\", \"ends\", 0], 1, \"$end\", \"$next_start\"] | [\"UW-CON-1007\", false, \"$end\", \"UW-CON-2007\", \"$next_start\", true] [\"UW-CON-1008\", true, null, \"$start\", \"$end\", \"Upgrade Witness Wireless Agreement\"] [[\"UWN0000A001\", \"$end\"], [\"UWN0000S009\", null]]"

    # A request bought through procurement: a line of tape that this inventory does
    # not track, which has no model and waits for nothing, and a spare switch of the
    # first model with the part number that procurement gave it.
    api POST /purchase-requests "{\"reference\": \"UW-REQ-1004\", \"status\": \"ordered\", \"lines\": [{\"part_number\": \"UW-TAPE-25\", \"description\": \"Hook-and-loop tape, 25 m\", \"quantity\": 10}, {\"catalog_entry_hid\": \"$witness_entry\", \"part_number\": \"UW-48P=\", \"description\": \"Spare switch, as procurement wrote it\", \"quantity\": 1, \"destination_site_hid\": \"$witness_site\"}]}"
    expect "pkg a purchase request with a line that this inventory does not track, with the part number and the description that procurement gave and no model, and a line of the first model with a part number: the request waits for the one line that is tracked" \
        "$status $(json '[[l["name"], l["tracked"], (l["catalog"] or {}).get("pid"), l["part_number"], l["quantity"], l["pending_quantity"]] for l in d["lines"]] + [d["quantity"], d["pending_quantity"]]')" \
        '201 [["UW-REQ-1004/1", false, null, "UW-TAPE-25", 10, 0], ["UW-REQ-1004/2", true, "UW-48P", "UW-48P=", 1, 1], 1, 1]'

    # A line that multiplies: tools that make half of the engineers from before half
    # as able again, which is three quarters of a unit more, counted under tools.
    api GET '/capacity-lines?limit=1000'
    engineer=$(json '[l["hid"] for l in d["items"] if l["name"] == "Upgrade Witness Engineer"][0]')
    api POST /capacity-lines "{\"side\": \"supply\", \"category\": \"tools\", \"name\": \"Upgrade Witness Automation\", \"effect\": \"multiply\", \"factor\": \"1.5\", \"share\": \"0.5\", \"applies_to\": [\"$engineer\"]}"
    made="$status $(json '[d["effect"], d["factor"], d["share"], [a["name"] for a in d["applies_to"]], d["quantity"], d["units_each"]]')"
    api GET /reports/capacity
    expect "pkg a line that multiplies, of tools that make half of the three engineers from before half as able again: 0.75 units more under tools, and a supply of 4.25 units" \
        "$made $status $(json '[d["active"]["supply"], [[m["name"], m["units"], [[a["name"], a["units"]] for a in m["applies_to"]]] for m in d["active"]["multiplying_lines"]]]')" \
        '201 ["multiply", "1.5", "0.5", ["Upgrade Witness Engineer"], null, null] 200 ["4.25", [["Upgrade Witness Automation", "0.75", [["Upgrade Witness Engineer", "3"]]]]]'

    # The capacity balance of the week, recorded by hand in place of what the service
    # recorded when it started, and then corrected, with the reason.
    api POST /capacity-records '{"note": "Recorded by hand with the release before"}'
    made="$status $(json '[d["active"]["supply"], d["adjusted"]]')"
    record=$(json_field hid)
    api PATCH "/capacity-records/$record" "{\"row_version\": $(json_field row_version), \"note\": \"The demand of the project was counted short\", \"active\": {\"demand\": \"2.50\"}}"
    made="$made $status $(json '[d["active"]["demand"], d["active"]["supply"], d["active"]["balance"], d["adjusted"], d["note"]]')"
    api GET '/capacity-records?limit=1000'
    expect "pkg the capacity balance of the week is recorded by hand, in place of what the service recorded when it started, and then corrected with the reason: a demand of 2.5 against a supply of 4.25 is a balance of 1.75, the record says that it was adjusted, and it is the one record of the week" \
        "$made $status $(json_field total)" \
        '201 ["4.25", false] 200 ["2.5", "4.25", "1.75", true, "The demand of the project was counted short"] 200 1'

    # Links on the three places from before, and what an item shows of its model's.
    made="$(said_of "$land" regions '"links": [{"url": "https://wiki.example.net/upgrade-land", "text": "Region page"}]')"
    made="$made $(said_of "$witness_site" sites '"links": [{"url": "https://wiki.example.net/upgrade-site", "text": ""}]')"
    made="$made $(said_of "$witness_room" locations '"links": [{"url": "https://intranet.example.net/upgrade-site/room-701/plan.pdf", "text": "Floor plan"}, {"url": "http://intranet.example.net/upgrade-site/room-701/racks", "text": "Racks"}]')"
    api GET "/items/${item[UWN0000F002]}"
    made="$made $(json '[l["text"] for l in d["catalog"]["links"]]')"
    api GET "/locations/$witness_room"
    expect "pkg links on each kind of record that takes them: the second model, whose items show its links; the region; the site, with a link that has no text; and the room, with two in their order, one of them over http" \
        "$made $(json '[[l["text"], l["url"]] for l in d["links"]]')" \
        '200 200 200 ["Data sheet", ""] [["Floor plan", "https://intranet.example.net/upgrade-site/room-701/plan.pdf"], ["Racks", "http://intranet.example.net/upgrade-site/room-701/racks"]]'

    # The renewal alert after sign-in: the contract whose renewal is pending is on its
    # list, which the Admin has not seen; once seen, it is not shown again.
    api GET /renewals/alert
    made="$status $(json '[d["show"], d["lapsed"]["count"], d["renewal_pending"]["count"], d["renewal_pending"]["new"], d["ending"]["count"], d["overdue"]]')"
    api POST /renewals/alert/seen "{\"version\": \"$(json_field version)\"}"
    made="$made $status"
    api GET /renewals/alert
    expect "pkg the renewal alert after sign-in shows the Admin the contract whose renewal is pending, which is new to them; once they have seen it, it is not shown again" \
        "$made $(json '[d["show"], d["renewal_pending"]["count"], d["renewal_pending"]["new"]]')" \
        '200 [true, 0, 1, 1, 0, 0] 200 [false, 1, 0]'

    # What no contract covers and is not to be renewed, counted by model, as the items
    # themselves say it.
    api GET "$every_item"
    wanted=$(json 'sorted([pid, count] for pid, count in __import__("collections").Counter(i["catalog"]["pid"] for i in d["items"] if i["record_status"] == "active" and i["is_major"] and (i["effective"]["lifecycle_state"]["value"] or "") in ("Assigned", "Test", "Prod", "Down") and not i["covered"] and i["effective"]["do_not_renew"]["value"]).items())')
    api GET /reports/coverage
    expect "pkg the coverage report counts by itself, by model, each item in service that no contract covers and that is not to be renewed, as the items say it, and leaves them off what no contract covers: $wanted" \
        "$status $(json 'sorted([m["pid"], m["count"]] for m in d["sections"]["not_renewed"]["by_model"])') $(json 'd["totals"]["not_renewed"] == sum(m["count"] for m in d["sections"]["not_renewed"]["by_model"]) > 0')" \
        "200 $wanted true"

    # Taken out first by the upgrade pass: the contacts are removed outright, and the
    # two contracts and then their agreement are retired.
    witness_undo=("${undo[@]}" "contracts/$member" "contracts/$ender" "agreements/$wireless" "${witness_undo[@]}")
    witness_lists+=("agreement-contacts /agreements/$agreement/contacts?limit=1000"
        "contract-contacts /contracts/$overriding/contacts?limit=1000"
        "capacity-records /capacity-records?limit=1000")
    witness_answers+=('renewals|/reports/renewals|d["totals"]|GET /reports/renewals counts on each of its lists what it counted: what ends soon, what has lapsed, what is pending and overdue, what ends with its term, and what more than one contract covers'
        'alert|/renewals/alert|[d["show"], d["overdue"]] + [[d[k]["count"], d[k]["new"]] for k in ("lapsed", "renewal_pending", "ending")]|GET /renewals/alert shows the Admin, who has seen it, nothing new, and counts what it counted'
        'not-renewed|/reports/coverage|sorted([m["pid"], m["count"]] for m in d["sections"]["not_renewed"]["by_model"])|GET /reports/coverage counts by model, as it did, the items in service that no contract covers and that are not to be renewed')
}

# The six weights of the settings, a default and a minimum of each kind, and beside them
# the side a new circuit counts at.
weight_settings="default_item_weight minimum_item_weight default_site_weight minimum_site_weight default_circuit_weight minimum_circuit_weight circuit_cost_side"

# put_setting KEY VALUE: give a setting a value as the Admin, VALUE being JSON, null
# returning it to its default. Prints the status and the value in force.
put_setting() {
    api GET /settings
    api PUT "/settings/$1" "{\"row_version\": $(json '[s["row_version"] for s in d if s["key"] == "'"$1"'"][0]'), \"value\": $2}"
    echo "$status $(json_field value)"
}

# witness_circuits: what came with revision 0010, made through the API of the previous
# release for an upgrade to carry: a circuit of each shape, three carriers, which are
# vendors, contacts of a carrier and of circuits, a circuit group, the weights of
# places, and the settings that weigh what has none and say where a new circuit counts.
# The first circuit is between the room and the hall of the draft site, from before,
# with the item with every value on its A side and the cluster on its Z side; the local
# exchange is its second carrier, with a number of its own; it has four cost lines with
# dates, a rate that ended and a credit that ends, and a site contact of its own for its
# Z side. The second has its far end in the carrier's network, with a note and two
# rates below its port's, and names an account manager of its own in place of the
# carrier's. The third is a dark fiber that a business partner lends, switched to count
# at its Z side. The carrier names an account manager and a support desk. Two of the
# circuits are in a group. The region, the site and the room from before are given
# weights, and once the circuits are made the Admin sets the six weights and makes z
# the side that a new circuit counts at, which changes none of them.
#
# witness_structure runs this where previous_at says that the previous release is at
# revision 0010, after witness_renewals, so the places, the people and the cluster are
# there. No release before 0.8.0 can store any of it: the upgrade to 0.8.0 starts from a
# release that could not, and this is for the upgrades after it. Every name is
# invented, and every address is of a domain reserved for examples.
witness_circuits() {
    local land building hall pat sam telecom exchange partner morgan desk link internet dark group
    local made wanted entry key value
    local undo=() settings=()

    witness_circuited=yes
    api GET '/regions?limit=1000'
    land=$(json '[r["hid"] for r in d["items"] if r["name"] == "Upgrade Land"][0]')
    api GET '/locations?include_drafts=true&limit=1000'
    building=$(json '[l["hid"] for l in d["items"] if l["name"] == "Building 7"][0]')
    hall=$(json '[l["hid"] for l in d["items"] if l["name"] == "Hall"][0]')
    api GET '/contacts?limit=1000'
    pat=$(json '[c["hid"] for c in d["items"] if c["email"] == "upgrade.pat@example.net"][0]')
    sam=$(json '[c["hid"] for c in d["items"] if c["email"] == "upgrade.sam@example.net"][0]')

    # The carriers, and the account manager and the support desk of the first, each a
    # contact record, named once on the carrier.
    api POST /vendors '{"name": "Upgrade Witness Telecom", "notes": "A fictional carrier"}'
    made=$status
    telecom=$(json_field hid)
    api POST /vendors '{"name": "Upgrade Witness Exchange", "notes": "A fictional local exchange carrier"}'
    made="$made $status"
    exchange=$(json_field hid)
    api POST /vendors '{"name": "Upgrade Witness Fiber", "notes": "A fictional business partner that lends its dark fiber"}'
    made="$made $status"
    partner=$(json_field hid)
    api POST /contacts '{"name": "Upgrade Morgan", "email": "upgrade.morgan@example.org", "phone": "+1 555 0184", "organization": "Upgrade Witness Telecom"}'
    made="$made $status"
    morgan=$(json_field hid)
    api POST /contacts '{"name": "Upgrade Witness Repair Desk", "email": "upgrade.repair@example.org", "phone": "+1 555 0185", "organization": "Upgrade Witness Telecom"}'
    made="$made $status"
    desk=$(json_field hid)
    api POST "/vendors/$telecom/contacts" "{\"contact_hid\": \"$morgan\", \"role\": \"account_manager\"}"
    made="$made $status"
    undo+=("vendors/$telecom/contacts/$(json_field hid)")
    api POST "/vendors/$telecom/contacts" "{\"contact_hid\": \"$desk\", \"role\": \"support_contact\"}"
    made="$made $status"
    undo+=("vendors/$telecom/contacts/$(json_field hid)")
    api GET "/vendors/$telecom"
    expect "pkg $previous_version holds three carriers, which are vendors: a carrier, a local exchange carrier and a business partner that lends its dark fiber; the carrier names its account manager and its support desk, each a contact record" \
        "$made $(json '[[c["role"], c["priority"], c["contact"]["name"]] for c in d["contacts"]]')" \
        '201 201 201 201 201 201 201 [["account_manager", 1, "Upgrade Morgan"], ["support_contact", 1, "Upgrade Witness Repair Desk"]]'

    # Between two locations from before, with a second carrier, cost lines with dates,
    # a rate that ended and a credit that ends, a device on each side, and a site
    # contact of its own for the Z side.
    api POST /circuits "{\"name\": \"Upgrade Witness Link\", \"enterprise_circuit_id\": \"UW-EC-0001\", \"description\": \"Between the room and the hall\", \"circuit_type\": \"point_to_point\", \"port_mbps\": \"1000\", \"a_location_hid\": \"$witness_room\", \"a_note\": \"demarc in the basement\", \"z_location_hid\": \"$hall\", \"carrier_hid\": \"$telecom\", \"carrier_circuit_number\": \"UWT/0001/000/UWTL\", \"billing_account\": \"UW-BA-0001\", \"billing_contract\": \"UW-MSA-0001\", \"installed_on\": \"$(day_from_today -400)\", \"activated_on\": \"$(day_from_today -390)\", \"support_weight\": \"0.75\", \"owner_hid\": \"$witness_owner\", \"notes\": \"Made with the release before\", \"tags\": [\"upgrade-witness\"]}"
    made=$status
    link=$(json_field hid)
    api POST "/circuits/$link/carriers" "{\"vendor_hid\": \"$exchange\", \"role\": \"local_exchange\", \"circuit_number\": \"UWX-0001\", \"notes\": \"Hands it over at the hall\"}"
    made="$made $status"
    for entry in "\"description\": \"Port, first rate\", \"monthly_cost\": \"900.00\", \"starts_on\": \"$(day_from_today -390)\", \"ends_on\": \"$(day_from_today -191)\"" \
        "\"description\": \"Port\", \"monthly_cost\": \"800.00\", \"starts_on\": \"$(day_from_today -190)\"" \
        "\"description\": \"Local loop\", \"monthly_cost\": \"150.00\", \"vendor_hid\": \"$exchange\"" \
        "\"description\": \"Promotional credit\", \"monthly_cost\": \"-50.00\", \"ends_on\": \"$(day_from_today 100)\", \"notes\": \"For the first year\""; do
        api POST "/circuits/$link/costs" "{$entry}"
        made="$made $status"
    done
    api POST "/circuits/$link/devices" "{\"devices\": [{\"item_hid\": \"$witness_full\", \"side\": \"a\"}, {\"group_hid\": \"$witness_cluster\", \"side\": \"z\", \"notes\": \"The pair that shares it\"}]}"
    made="$made $status"
    api POST "/circuits/$link/contacts" "{\"contact_hid\": \"$sam\", \"side\": \"z\", \"role\": \"technical\"}"
    made="$made $status"
    undo+=("circuits/$link/contacts/$(json_field hid)")
    api GET "/circuits/$link"
    expect "pkg a circuit between the room and the hall of the draft site, from before, counted at its A side, the site of the room: the local exchange is its second carrier, with a number of its own; of its four cost lines the first rate has ended and the credit has not, so it costs 900.00 a month and 10800.00 a year; the item with every value is on its A side and the cluster on its Z side; it has the carrier's account manager and support desk, and for its Z side a technical contact of its own in place of the region's" \
        "$made $(json '[d["cost_side"], d["cost_site_path"], d["speed"], [[c["vendor"], c["role"], c["circuit_number"]] for c in d["carriers"]], [[c["description"], c["in_date"]] for c in d["costs"]], d["monthly_cost"], d["annual_cost"], sorted(x["side"] for x in d["devices"]), [d["effective"][k]["source"] for k in ("account_managers", "support_contacts")], [[e["role"], e["source"], [c["contact"]["name"] for c in e["value"]]] for e in d["effective"]["site_contacts"]["z"]]]')" \
        '201 201 201 201 201 201 201 201 ["a", "Upgrade Land > North > Upgrade Site", "1G", [["Upgrade Witness Exchange", "local_exchange", "UWX-0001"]], [["Local loop", true], ["Port", true], ["Port, first rate", false], ["Promotional credit", true]], "900.00", "10800.00", ["a", "z"], ["vendor", "vendor"], [["technical", "own", ["Upgrade Sam"]]]]'

    # Its far end in the carrier's network, with a note, and rates below its port's; it
    # names an account manager of its own in place of the carrier's.
    api POST /circuits "{\"name\": \"Upgrade Witness Internet\", \"enterprise_circuit_id\": \"UW-EC-0002\", \"circuit_type\": \"internet\", \"port_mbps\": \"1000\", \"down_mbps\": \"500\", \"up_mbps\": \"50\", \"a_location_hid\": \"$building\", \"z_note\": \"carrier network\", \"carrier_hid\": \"$telecom\", \"carrier_circuit_number\": \"UWT/0002/000/UWTL\", \"activated_on\": \"$(day_from_today -100)\"}"
    made=$status
    internet=$(json_field hid)
    api POST "/circuits/$internet/costs" '{"description": "Port", "monthly_cost": "500.00"}'
    made="$made $status"
    api POST "/circuits/$internet/contacts" "{\"contact_hid\": \"$sam\", \"role\": \"account_manager\"}"
    made="$made $status"
    undo+=("circuits/$internet/contacts/$(json_field hid)")
    api GET "/circuits/$internet"
    expect "pkg a circuit whose far end is in the carrier's network, with no location and a note of where it ends, and two rates below the speed of its port; it names an account manager of its own in place of the carrier's, and has the carrier's support desk" \
        "$made $(json '[d["z_side"], d["z_note"], d["speed"], [d["effective"][k]["value"] for k in ("down_mbps", "up_mbps")], [[d["effective"][k]["source"], [c["contact"]["name"] for c in d["effective"][k]["value"]]] for k in ("account_managers", "support_contacts")], d["monthly_cost"]]')" \
        '201 201 201 [null, "carrier network", "1G / 500M / 50M", ["500.00", "50.00"], [["own", ["Upgrade Sam"]], ["vendor", ["Upgrade Witness Repair Desk"]]], "500.00"]'

    # A dark fiber that a business partner lends, with no number of the carrier's,
    # switched to count at its Z side, the draft site of the hall.
    api POST /circuits "{\"name\": \"Upgrade Witness Dark Fiber\", \"enterprise_circuit_id\": \"UW-EC-0003\", \"circuit_type\": \"dark_fiber\", \"port_mbps\": \"10000\", \"a_location_hid\": \"$building\", \"z_location_hid\": \"$hall\", \"carrier_hid\": \"$partner\", \"production\": false, \"notes\": \"Lit for failover tests only\"}"
    made="$status $(json_field cost_side)"
    dark=$(json_field hid)
    api POST "/circuits/$dark/costs" "{\"description\": \"Fiber lease\", \"monthly_cost\": \"300.00\", \"starts_on\": \"$(day_from_today -30)\"}"
    made="$made $status $(said_of "$dark" circuits '"cost_side": "z"')"
    api GET "/circuits/$dark"
    made="$made $(json '[d["cost_side"], d["cost_site_path"], d["speed"], d["production"], d["carrier_circuit_number"]]')"

    # A group of two of them.
    api POST /circuit-groups "{\"name\": \"Upgrade Witness Links\", \"description\": \"The circuits between the places\", \"owner_hid\": \"$witness_owner\", \"tags\": [\"upgrade-witness\"]}"
    made="$made $status"
    group=$(json_field hid)
    api POST "/circuit-groups/$group/members" "{\"circuit_hids\": [\"$link\", \"$dark\"]}"
    made="$made $status"
    api GET "/circuit-groups/$group"
    expect "pkg a dark fiber that a business partner lends, with no number of the carrier's and not for production, switched to count at its Z side, the draft site of the hall; and a circuit group of it and the first, which counts both as in service and costs 1200.00 a month" \
        "$made $(json '[d["circuits"], d["in_service"], d["monthly_cost"], d["annual_cost"]]')" \
        '201 a 201 200 ["z", "Upgrade Land > North > Upgrade New Site", "10G", false, null] 201 201 [2, 2, "1200.00", "14400.00"]'

    # The weights of the places from before, and then the settings: the six weights,
    # and z for the side a new circuit counts at, which changes no circuit there is.
    made="$(said_of "$land" regions '"support_weight": "1.5"') $(said_of "$witness_site" sites '"support_weight": "2"') $(said_of "$witness_room" locations '"support_weight": "0.25"')"
    wanted="200 200 200"
    for entry in default_item_weight=1 minimum_item_weight=0.75 default_site_weight=1 minimum_site_weight=1.5 default_circuit_weight=0.5 minimum_circuit_weight=0.6 'circuit_cost_side="z"'; do
        key=${entry%%=*}
        value=${entry#*=}
        made="$made $(put_setting "$key" "$value")"
        wanted="$wanted 200 ${value//\"/}"
        settings+=("settings/$key")
    done
    api GET "/circuits/$link"
    made="$made $(json_field cost_side)"
    api GET /reports/capacity
    expect "pkg weights on the region, the site and the room from before, and the six weights and the side a new circuit counts at set by the Admin: the circuit from before still counts at its A side; the capacity report counts 3.75 of places, and 5.25 with the draft site at the default raised to the minimum, and 1.95 of circuits, the two with none of their own at the default raised to the minimum" \
        "$made $(json '[[d[v]["places_weight"], d[v]["circuits_weight"], d[v]["defaulted"]["sites"], d[v]["defaulted"]["circuits"], d[v]["raised"]["sites"], d[v]["raised"]["circuits"]] for v in ("active", "with_drafts")]')" \
        "$wanted a [[\"3.75\", \"1.95\", 0, 2, 0, 2], [\"5.25\", \"1.95\", 1, 2, 1, 2]]"

    # Taken out first by the upgrade pass: the contacts named by the circuits and by
    # the carrier are removed outright, the circuits, their group and the two contacts
    # of the carrier are retired, and the settings are blank, or a, once more.
    witness_undo=("${undo[@]}" "circuits/$link" "circuits/$internet" "circuits/$dark" "circuit-groups/$group"
        "contacts/$morgan" "contacts/$desk" "${settings[@]}" "${witness_undo[@]}")
    witness_lists+=("circuits /circuits?include_drafts=true&include_archived=true&limit=1000"
        "circuit-link /circuits/$link"
        "circuit-internet /circuits/$internet"
        "circuit-dark /circuits/$dark"
        "circuit-link-contacts /circuits/$link/contacts?limit=1000"
        "circuit-internet-contacts /circuits/$internet/contacts?limit=1000"
        "vendor-contacts /vendors/$telecom/contacts?limit=1000"
        "circuit-groups /circuit-groups?include_drafts=true&include_archived=true&limit=1000"
        "circuit-group-members /circuit-groups/$group/members?limit=1000")
    witness_answers+=('costs-by-carrier|/reports/circuit-costs?by=carrier|[d["fiscal_year"], d["totals"], sorted([r["label"] or "", r["circuits"], r["cost"], r["monthly_cost"], r["annual_cost"]] for r in d["rows"])]|GET /reports/circuit-costs counts by the carrier that bills each line what it counted: how many circuits, what the year costs, and what a month and a year cost'
        'costs-by-site|/reports/circuit-costs?by=site|sorted([r["label"] or "", r["circuits"], r["monthly_cost"], r["annual_cost"]] for r in d["rows"])|and by the site that each circuit counts at, its A side or the Z side it was switched to'
        'costs-by-group|/reports/circuit-costs?by=group|sorted([r["label"] or "", r["circuits"], r["monthly_cost"], r["annual_cost"]] for r in d["rows"])|and by the group of the circuits'
        'weights|/reports/capacity|[[d[v][k] for k in ("support_weight", "items_weight", "places_weight", "circuits_weight", "defaulted", "raised")] + [sorted([r["path"] or "", r["support_weight"]] for r in d[v]["demand_by_region"])] for v in ("active", "with_drafts")]|GET /reports/capacity counts the support weight in its parts as it did, the items, the places and the circuits, with what counted at a default and what was raised to a minimum, and the demand of each region'
        "weights-set|/settings|sorted([s[\"key\"], s[\"value\"], s[\"is_default\"]] for s in d if s[\"key\"] in \"$weight_settings\".split())|GET /settings has the six weights and the side a new circuit counts at as the Admin set them")
}

# witness_references: what came with revision 0011, made through the API of the previous
# release for an upgrade to carry: on each of the six kinds of record that take one, the
# catalog entry, the region, the site and the room from before, the first circuit and the
# item with every value, a file of its own and a link; and one file more, on all six at
# once. The content of the files is in the store beside the database, and each must
# come back from it byte for byte after the upgrade.
#
# witness_structure runs this where previous_at says that the previous release is at
# revision 0011, after witness_circuits, so the places, the circuit and the item are
# there. No release before 0.9.0 can store any of it: the upgrade to 0.9.0 starts from a
# release that could not, and this is for the upgrades after it. Every name is
# invented, and every address is of a domain reserved for examples.
witness_references() {
    local land link entry records="" records_of type value hid made="" wanted="" number=0 sums="" hids=()

    witness_referenced=yes
    api GET '/regions?limit=1000'
    land=$(json '[r["hid"] for r in d["items"] if r["name"] == "Upgrade Land"][0]')
    api GET '/circuits?limit=1000'
    link=$(json '[c["hid"] for c in d["items"] if c["name"] == "Upgrade Witness Link"][0]')
    for entry in "catalog-entries $witness_entry pdf data_sheet" "regions $land pdf map" \
        "sites $witness_site png photograph" "locations $witness_room pdf floor_plan" \
        "circuits $link pdf letter_of_authorization" "items $witness_full png photograph"; do
        read -r records_of hid type value <<<"$entry"
        number=$((number + 1))
        reference_file "$work/witness-$number.$type" "$type" 0.05
        upload "$work/witness-$number.$type" "witness-$number.$type" "$value" "Upgrade witness file $number" "$hid"
        made="$made $status"
        wanted="$wanted 201"
        witness_files+=("$(json_field hid):$work/witness-$number.$type")
        witness_undo=("reference-files/$(json_field hid)" "${witness_undo[@]}")
        api POST /reference-files/links "{\"title\": \"Upgrade witness link $number\", \"kind\": \"other\", \"url\": \"https://www.example.net/upgrade/witness-$number\", \"notes\": \"Made with the release before\", \"attach_to\": [\"$hid\"]}"
        made="$made $status"
        wanted="$wanted 201"
        witness_undo=("reference-files/$(json_field hid)" "${witness_undo[@]}")
        records="${records:+$records, }\"$hid\""
        witness_lists+=("references-$records_of /$records_of/$hid/references?limit=1000")
    done
    reference_file "$work/witness-all.pdf" pdf 0.1
    upload "$work/witness-all.pdf" witness-all.pdf other "Upgrade witness on every kind of record" "$witness_entry"
    made="$made $status"
    hid=$(json_field hid)
    api POST "/reference-files/$hid/attachments" "{\"records\": [${records#*, }]}"
    made="$made $status $(json_field attachment_count)"
    witness_files+=("$hid:$work/witness-all.pdf")
    witness_undo=("reference-files/$hid" "${witness_undo[@]}")
    for entry in "${witness_files[@]}"; do
        hids+=("${entry%%:*}")
        sums="$sums $(sha "${entry#*:}")"
    done
    expect "pkg $previous_version holds a file and a link on each of the six kinds of record from before, the catalog entry, the region, the site, the room, the first circuit and the item with every value, and one file more on all six, and gives back each file byte for byte" \
        "$made $(stored_sums "${hids[@]}" | xargs)" "$wanted 201 200 6$sums"
    witness_lists+=("references /reference-files?limit=1000")
}

# counted_now [QUERY]: what a release counts of a view of the items: items, components,
# managed nodes and the support weight as a number, the estimated value and the annual
# support cost. The first four are in the summary. The money is in the management
# report, and in the summary of a release from before there was one. QUERY is the query
# of both requests, with its question mark.
counted_now() {
    local first
    api GET "/reports/summary${1:-}"
    first=$(json '(lambda t: [t["items"], t["component_count"], t["managed_node_count"], float(t["support_weight"])] + [t[k] for k in ("est_value", "annual_support_cost") if k in t])(d["totals"])')
    if [ "$(json '"est_value" in d["totals"]')" = true ]; then
        echo "$first"
        return 0
    fi
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
# had, the first stack as it says of itself, the networks, the addresses, the owners,
# the choices,
# what the items are counted as, and the tables of all of it as the database file has
# them. It runs when everything is made, also what the file of a migration makes.
witness_kept() {
    local hid table entry name path expression held=""
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
    keep choices
    api GET '/owners?limit=1000'
    keep owners
    witness_tables="items vendors catalog_entries owners tags choices"
    if [ "${#witness_groups[@]}" -gt 0 ]; then
        witness_tables="$witness_tables item_replacements device_groups device_group_members networks addresses"
        api GET "$every_group"
        keep device-groups
        expect "pkg and the ${#witness_groups[@]} device groups, the draft among them" \
            "$status $(json_field total)" "200 ${#witness_groups[@]}"
        for hid in "${witness_groups[@]}"; do
            api GET "/device-groups/$hid/members?include_past=true&limit=1000"
            keep "members-$hid"
        done
        api GET "/device-groups/$witness_stack"
        keep stack
        api GET '/networks?limit=1000'
        keep networks
        api GET "$every_address"
        keep addresses
        expect "pkg and the $addresses_made addresses" "$status $(json_field total)" "200 $addresses_made"
        # What the previous release counts, to compare with what the new version counts
        # of the same items: all of them, or the view that the file of a migration
        # names, the cluster, and the stack that is one switch where there is one.
        counted_before=$(counted_now "$counted_view")
        cluster_before=$(counted_now '?filter=group.name:eq:upgrade-cluster')
        if [ -n "$witness_lone" ]; then lone_before=$(counted_now '?filter=group.name:eq:upgrade-lone'); fi
        duplicates_before=$(duplicates 192.0.2.101)
    fi
    # What came after the groups: each list record for record, and each answer that
    # is worked out of the records by what its expression makes of it.
    for entry in "${witness_lists[@]}"; do
        api GET "${entry#* }"
        keep "${entry%% *}"
        held="$held${entry%% *} $(json 'd["total"] if isinstance(d, dict) else len(d)'), "
    done
    for entry in "${witness_answers[@]}"; do
        IFS='|' read -r name path expression _ <<<"$entry"
        api GET "$path"
        answers_before[$name]="$status $(json "$expression")"
    done
    if [ -n "$witness_site" ]; then
        witness_tables="$witness_tables contacts operators regions sites locations contact_assignments owner_members"
        check "pkg and what came after the groups, the records of each list: ${held%, }" test -n "$held"
    fi
    if [ -n "$witness_contracts" ]; then
        witness_tables="$witness_tables agreements contracts contract_coverage purchase_requests purchase_lines external_systems registrations capacity_lines"
    fi
    if [ -n "$witness_renewed" ]; then
        witness_tables="$witness_tables contract_contacts capacity_line_targets capacity_records renewal_alert_views"
    fi
    if [ -n "$witness_circuited" ]; then
        witness_tables="$witness_tables circuits circuit_carriers circuit_costs circuit_devices vendor_contacts circuit_contacts circuit_groups circuit_group_members"
    fi
    if [ -n "$witness_referenced" ]; then
        witness_tables="$witness_tables reference_files reference_attachments"
    fi
    # And the tables beside the inventory that the file of a migration names.
    witness_tables="$witness_tables${more_tables:+ $more_tables}"
    for table in $witness_tables; do
        columns_before[$table]=$(table_read "$table" columns)
        keys_before[$table]=$(table_read "$table" keys)
        rows_before[$table]=$(table_rows "$table" "$(table_columns "$table")")
        # Where a file says that rows of the table are meant to change, or that rows
        # may be added to it, the others are kept by themselves as well.
        if [ -n "${rows_apart[$table]:-}${may_add[$table]:-}$unwritten" ]; then
            rest_of[$table]=$(table_read "$table" hids "${rows_apart[$table]:-}")
            rest_before[$table]=$(table_rows "$table" "$(table_columns "$table")" "${rest_of[$table]}")
        fi
    done
    check "pkg and its items table is read from the database file: $(printf '%s\n' "${columns_before[items]}" | wc -l) columns, $(printf '%s\n' "${keys_before[items]}" | wc -l) indexes and foreign keys, ${rows_before[items]%% *} rows" \
        test "${rows_before[items]%% *}" = "${#witness_items[@]}"
    if [ "${#witness_groups[@]}" -gt 0 ]; then
        expect "pkg and so are the tables of the replacements, the groups, their members, the networks and the addresses: their rows" \
            "${rows_before[item_replacements]%% *} ${rows_before[device_groups]%% *} ${rows_before[device_group_members]%% *} ${rows_before[networks]%% *} ${rows_before[addresses]%% *}" \
            "1 ${#witness_groups[@]} $members_made 2 $addresses_made"
    fi
}

# meant_in HOW LIST: the fields of the records of a list that the comparison passes
# over, because the file of a migration or of a release says that they are meant to
# change. Only the new version changes anything: where the previous release serves
# again, HOW is exact and nothing is passed over.
meant_in() {
    if [ "$1" != exact ]; then printf '%s' "${meant[$2]:-}"; fi
}

# how_of HOW LIST: how the records of a list are compared with those that were kept:
# as HOW has it, and on the new version with records beside them let be, where a file
# says that the new version may add some, and while a migration of the upgrade has no
# file to say what it adds.
how_of() {
    if [ "$1" != exact ] && [ -n "${may_add[$2]:-}$unwritten" ]; then
        printf '%s more' "$1"
    else
        printf '%s' "$1"
    fi
}

# but_for HOW LIST: the words that say either in the line of that comparison.
but_for() {
    if [ -n "$(meant_in "$1" "$2")" ]; then
        printf ', but for what is meant to change, which is looked at by itself'
    fi
    case $(how_of "$1" "$2") in
        *more) printf ', beside what the new version may have added' ;;
    esac
}

# as_before NOW BEFORE: an answer that is worked out of the records, as the new version
# gave it, NOW, shown in the shape of the one that was kept, BEFORE: each is a status
# and what json printed. A newer version may give an answer more fields, as it may a
# record: a field that the kept answer has not is left out, also within what it holds,
# so that the coverage report may count a section more, and the rest is shown as it is.
as_before() {
    python3 -c '
import json, sys

def split(text):
    status, _, rest = text.partition(" ")
    try:
        return status, json.loads(rest)
    except ValueError:
        return status, None

def shaped(now, was):
    if isinstance(now, dict) and isinstance(was, dict):
        return {key: shaped(value, was[key]) for key, value in now.items() if key in was}
    if isinstance(now, list) and isinstance(was, list) and len(now) == len(was):
        return [shaped(*pair) for pair in zip(now, was)]
    return now

status, now = split(sys.argv[1])
_, was = split(sys.argv[2])
if isinstance(now, (dict, list)):
    print(status, json.dumps(shaped(now, was), sort_keys=True))
else:
    print(sys.argv[1])' "$1" "$2"
}

# witness_carried HOW WHEN: the items and the history of each, the groups, their
# memberships, the networks, the addresses, the owners and the choices are as witness_kept found
# them. HOW is "fields" on the new version, which may give a record more fields, and
# "exact" where the previous release serves again. WHEN begins the lines.
#
# What the new version is meant to change, or to say differently of what it holds, is
# passed over in "fields" by name, as the file of its migration or of its release has
# it in $meant, and that file then looks at it by itself, in its changed_ function.
witness_carried() {
    local how=$1 when=$2 hid found differing="" entry name path expression words listed=""
    [ -n "$witness_entry" ] || return 0
    api GET "$every_item"
    expect "pkg $when every item from before is as it was, field for field and at the row_version it had (${#witness_items[@]} items)$(but_for "$how" items)" \
        "$status $(unchanged items "$(how_of "$how" items)" "$(meant_in "$how" items)")" "200 same"
    for hid in "${witness_items[@]}"; do
        api GET "/items/$hid/history?limit=1000"
        found=$(unchanged "history-$hid" "$how")
        [ "$found" = same ] || differing="$differing$hid: $found. "
    done
    expect "pkg $when the history of each is as it was, event for event" "$differing" ""
    if [ "${#witness_groups[@]}" -gt 0 ]; then
        api GET "$every_group"
        expect "pkg $when every device group is as it was, field for field and at the row_version it had (${#witness_groups[@]} groups)$(but_for "$how" device-groups)" \
            "$status $(unchanged device-groups "$(how_of "$how" device-groups)" "$(meant_in "$how" device-groups)")" "200 same"
        differing=""
        for hid in "${witness_groups[@]}"; do
            api GET "/device-groups/$hid/members?include_past=true&limit=1000"
            found=$(unchanged "members-$hid" "$(how_of "$how" members)" "$(meant_in "$how" members)")
            [ "$found" = same ] || differing="$differing$hid: $found. "
        done
        expect "pkg $when every membership of each is as it was, those that were ended too, with the day they ended$(but_for "$how" members)" "$differing" ""
        api GET "/device-groups/$witness_stack"
        expect "pkg $when the first stack says of itself what it said: its serial number and where that is from, its master, its members, and whatever else $previous_version said of it$(but_for "$how" stack)" \
            "$status $(unchanged stack "$how" "$(meant_in "$how" stack)")" "200 same"
        api GET '/networks?limit=1000'
        found=$(unchanged networks "$(how_of "$how" networks)" "$(meant_in "$how" networks)")
        api GET "$every_address"
        expect "pkg $when the two networks and the $addresses_made addresses are as they were$(but_for "$how" networks)$(but_for "$how" addresses)" \
            "$found $status $(unchanged addresses "$(how_of "$how" addresses)" "$(meant_in "$how" addresses)")" "same 200 same"
    fi
    if [ "${#witness_lists[@]}" -gt 0 ]; then
        differing=""
        for entry in "${witness_lists[@]}"; do
            name=${entry%% *}
            api GET "${entry#* }"
            found=$(unchanged "$name" "$(how_of "$how" "$name")" "$(meant_in "$how" "$name")")
            [ "$found" = same ] || differing="$differing$name: $status $found. "
            listed="${listed:+$listed, }$name"
        done
        expect "pkg $when every record of what came after the groups is as it was, field for field and at the row_version it had, the drafts and the retired among them: $listed" \
            "$differing" ""
        if [ "${#witness_files[@]}" -gt 0 ]; then
            hid=""
            found=""
            for entry in "${witness_files[@]}"; do
                hid="$hid ${entry%%:*}"
                found="$found $(sha "${entry#*:}")"
            done
            # shellcheck disable=SC2086  # The HIDs are words of their own.
            expect "pkg $when the content of each of the ${#witness_files[@]} files from before comes back from the store byte for byte" \
                "$(stored_sums $hid | xargs)" "${found# }"
        fi
        for entry in "${witness_answers[@]}"; do
            IFS='|' read -r name path expression words <<<"$entry"
            api GET "$path"
            found="$status $(json "$expression")"
            if [ "$how" != exact ]; then found=$(as_before "$found" "${answers_before[$name]}"); fi
            expect "pkg $when $words" "$found" "${answers_before[$name]}"
        done
    fi
    api GET '/owners?limit=1000'
    expect "pkg $when every owner is the record it was$(but_for "$how" owners)" \
        "$status $(unchanged owners "$(how_of "$how" owners)" "$(meant_in "$how" owners)")" "200 same"
    api GET /choices
    case $(how_of "$how" choices) in
        *more)
            expect "pkg $when every choice from before is the record it was, those of the site's own and the labels of the site's among them$(but_for "$how" choices)" \
                "$status $(unchanged choices "$how more" "$(meant_in "$how" choices)")" "200 same"
            ;;
        *)
            expect "pkg $when every choice is the record it was, those of the site's own and the labels of the site's among them, and no choice is added$(but_for "$how" choices)" \
                "$status $(unchanged choices "$how" "$(meant_in "$how" choices)")" "200 same"
            ;;
    esac
    if [ "$how" != exact ]; then particular changed "$when"; fi
}

# columns_then TABLE: the names of the columns that the table had when witness_kept
# read it.
columns_then() { printf '%s\n' "${columns_before[$1]}" | cut -d' ' -f1 | xargs; }

# columns_meant TABLE: the columns that a table is to have after the migrations of the
# upgrade, as table_read columns prints them: those it had, in their places, each as the
# files say that it is declared now where they say it is declared otherwise, and after
# them those that the files say are added.
columns_meant() {
    python3 -c '
import sys
before, altered, added = (text.splitlines() for text in sys.argv[1:4])
now = {line.split(" ", 1)[0]: line for line in altered if line}
print("\n".join([now.get(line.split(" ", 1)[0], line) for line in before] + [line for line in added if line]))' \
        "${columns_before[$1]}" "${altered_columns[$1]:-}" "${new_columns[$1]:-}"
}

# every_line_in BEFORE NOW: whether every line of the first text is a line of the second.
every_line_in() {
    python3 -c '
import sys
sys.exit(0 if set(sys.argv[1].splitlines()) <= set(sys.argv[2].splitlines()) else 1)' "$1" "$2"
}

# tables_carried WHEN [migrated]: every table of the inventory, read from the database
# file, is as witness_kept found it.
#
# With nothing more said, each has the columns, the indexes, uniquenesses and foreign
# keys, and the rows it had: for an upgrade with no migration, which changes nothing
# that is held, and where the previous release serves again.
#
# With "migrated", each has every column it had, as it was, and after them those that
# the files of the migrations say are added, and no other; the indexes, uniquenesses and
# foreign keys likewise; and every row holds what it held in the columns it had, but
# for the rows that a file says are meant to change. While a migration of the upgrade
# has no file, nobody has said what is added: what a table had must then still be
# there, its rows too, and what is there beside it is not looked at.
tables_carried() {
    local when=$1 how=${2:-exact} table differing="" columns keys added

    if [ "$how" = exact ]; then
        for table in $witness_tables; do
            [ "$(table_read "$table" columns)" = "${columns_before[$table]}" ] || differing="$differing$table: columns. "
            [ "$(table_read "$table" keys)" = "${keys_before[$table]}" ] || differing="$differing$table: keys. "
            [ "$(table_rows "$table" "$(columns_then "$table")")" = "${rows_before[$table]}" ] || differing="$differing$table: rows. "
        done
        expect "pkg $when every table of the inventory has the columns, the indexes, uniquenesses and foreign keys, and the rows it had, each row as it was: $(echo "$witness_tables" | wc -w) tables ($witness_tables)" \
            "$differing" ""
        return 0
    fi
    for table in $witness_tables; do
        differing=""
        added=""
        columns=$(table_read "$table" columns)
        keys=$(table_read "$table" keys)
        if [ -n "$unwritten" ]; then
            every_line_in "${columns_before[$table]}" "$columns" || differing="${differing}columns. "
            every_line_in "${keys_before[$table]}" "$keys" || differing="${differing}keys. "
            added=", and whatever migration ${unwritten// /, }, which has no file yet, adds to them"
        else
            if [ -n "${new_columns[$table]:-}${altered_columns[$table]:-}" ]; then
                [ "$columns" = "$(columns_meant "$table")" ] || differing="${differing}columns. "
                if [ -n "${altered_columns[$table]:-}" ]; then
                    added=", but for $(printf '%s\n' "${altered_columns[$table]}" | cut -d' ' -f1 | xargs | sed 's/ /, /g'), which the migration declares as it says"
                fi
                if [ -n "${new_columns[$table]:-}" ]; then
                    added="$added, and after its columns $(printf '%s\n' "${new_columns[$table]}" | cut -d' ' -f1 | xargs | sed 's/ /, /g')"
                fi
            else
                [ "$columns" = "${columns_before[$table]}" ] || differing="${differing}columns. "
            fi
            if [ -n "${new_keys[$table]:-}" ]; then
                [ "$keys" = "$(printf '%s\n' "${keys_before[$table]}" "${new_keys[$table]}" | LC_ALL=C sort)" ] || differing="${differing}keys. "
                added="$added, and with its keys $(printf '%s\n' "${new_keys[$table]}" | wc -l) more"
            else
                [ "$keys" = "${keys_before[$table]}" ] || differing="${differing}keys. "
            fi
        fi
        if [ -n "${rest_of[$table]+kept}" ]; then
            [ "$(table_rows "$table" "$(columns_then "$table")" "${rest_of[$table]}")" = "${rest_before[$table]}" ] || differing="${differing}rows. "
            if [ -n "${rows_apart[$table]:-}" ]; then
                added="$added; the rows that are meant to change are left out, and looked at by themselves"
            fi
            if [ -n "${may_add[$table]:-}" ]; then
                added="$added; the migration may add rows beside them"
            elif [ -z "$unwritten" ] && [ "$(table_rows "$table" hid | cut -d' ' -f1)" != "${rows_before[$table]%% *}" ]; then
                differing="${differing}rows added or gone. "
            fi
        else
            [ "$(table_rows "$table" "$(columns_then "$table")")" = "${rows_before[$table]}" ] || differing="${differing}rows. "
        fi
        expect "pkg $when the $table table has the columns and the indexes, uniquenesses and foreign keys it had, each as it was, and every row of it holds what it held in those columns (${rows_before[$table]%% *} rows)$added" \
            "$differing" ""
    done
}

# carried_inventory: what the upgrade to this version did with the inventory of the
# previous release, by the API and by the database file. Where there is no migration,
# the schema stays where it was and nothing that is held is changed. Where there is
# one, what it adds and what it is meant to change is what its file says, and the rest
# must be as it was.
carried_inventory() {
    local full how=exact
    if migrating; then how=migrated; fi
    witness_carried fields "after the upgrade,"
    tables_carried "after the upgrade," "$how"

    # The uniquenesses are tried as well as read: a duplicate must still be refused.
    api GET "/items/$witness_full"
    full="$(json '[d["catalog_entry_hid"], d["serial_number"], d["asset_tag"]]')"
    api POST /items "{\"catalog_entry_hid\": \"$witness_entry\", \"serial_number\": \"uwn0000x002\"}"
    expect "pkg the serial number is still unique within a model: a second UWN0000X002 of UW-48P, written in lower case, is refused" \
        "$full $status $(json 'd["errors"][0]["field"]')" "[\"$witness_entry\", \"UWN0000X002\", \"UW-AT-0002\"] 409 serial_number"
    api POST /items '{"asset_tag": "uw-at-0003", "name": "Upgrade witness, a second draft"}'
    expect "pkg and the asset tag among all items: a second UW-AT-0003, which the draft has, is refused" \
        "$status $(json 'd["errors"][0]["field"]')" "409 asset_tag"
    if [ "${#witness_groups[@]}" -gt 0 ]; then
        api POST /device-groups '{"type": "custom", "name": "UPGRADE-STACK"}'
        expect "pkg and the name of a group: a second upgrade-stack, written in capitals, is refused" \
            "$status $(json 'd["errors"][0]["field"]')" "409 name"

        expect "pkg the inventory is counted as $previous_version counted it: items, components, managed nodes, support weight, value and cost ($counted_before)${counted_view:+, but for the items that are meant to be counted otherwise, which are looked at by themselves}" \
            "$(counted_now "$counted_view")" "$counted_before"
        if [ -n "$witness_lone" ]; then
            expect "pkg and so are the cluster, by how it is managed, and the stack that is one switch alone, with no discount" \
                "$(counted_now '?filter=group.name:eq:upgrade-cluster') $(counted_now '?filter=group.name:eq:upgrade-lone')" \
                "$cluster_before $lone_before"
        else
            expect "pkg and so is the cluster, by how it is managed" \
                "$(counted_now '?filter=group.name:eq:upgrade-cluster')" "$cluster_before"
        fi
        expect "pkg GET /reports/duplicates lists the address that is twice under one network as it did" \
            "$(duplicates 192.0.2.101)" "$duplicates_before"
    fi
    # Last, what is new is tried on what was carried over, by the files that have it.
    particular after
}

# witness_undone: take out again, with the new version, what witness_places,
# witness_money, witness_renewals, witness_circuits and witness_references made, so that
# the rest of the upgrade pass starts from lists, a tree and reports as empty as those of
# a new installation. The items and the groups are retired by then. Nothing is deleted
# but what the API removes outright, an assignment, a person of an owner, a contact that
# a contract, a vendor or a circuit names, and a reference, which is erased with its
# content first: a capacity line, an external system, a
# contract, an agreement, a circuit, a circuit group, an operator, a contact and a place
# are retired, a registration is marked as removed, a coverage is ended with a day, a
# purchase request is cancelled, and a setting is returned to its default. A circuit is
# retired before the places of its sides, which are not retired while it is not.
witness_undone() {
    local entry made="" wanted="" day
    day=$(day_from_today -30)
    if [ -n "$witness_contracts" ]; then
        api GET '/capacity-lines?include_drafts=true&limit=1000'
        for entry in $(json '" ".join(x["hid"] + ":" + str(x["row_version"]) for x in d["items"])'); do
            api POST "/capacity-lines/${entry%:*}/retire" "{\"row_version\": ${entry#*:}}"
            made="$made$status "
            wanted="${wanted}200 "
        done
        api GET '/registrations?limit=1000'
        for entry in $(json '" ".join(x["hid"] + ":" + str(x["row_version"]) for x in d["items"] if x["status"] != "removed")'); do
            api PATCH "/registrations/${entry%:*}" "{\"row_version\": ${entry#*:}, \"status\": \"removed\"}"
            made="$made$status "
            wanted="${wanted}200 "
        done
        api GET '/contract-coverage?limit=1000'
        for entry in $(json '" ".join(x["contract_hid"] + "/coverage/" + x["hid"] + ":" + str(x["row_version"]) for x in d["items"] if x["in_force"] or x["left_service"])'); do
            api PATCH "/contracts/${entry%:*}" "{\"row_version\": ${entry#*:}, \"ends_on\": \"$day\", \"left_service\": false}"
            made="$made$status "
            wanted="${wanted}200 "
        done
        api GET '/purchase-requests?limit=1000'
        for entry in $(json '" ".join(x["hid"] + ":" + str(x["row_version"]) for x in d["items"] if x["status"] != "cancelled")'); do
            api PATCH "/purchase-requests/${entry%:*}" "{\"row_version\": ${entry#*:}, \"status\": \"cancelled\"}"
            made="$made$status "
            wanted="${wanted}200 "
        done
    fi
    for entry in "${witness_undo[@]}"; do
        case $entry in
            # A reference is erased outright, with its content (P-160).
            contact-assignments/* | owners/*/members/* | */contacts/* | reference-files/*)
                api DELETE "/$entry"
                wanted="${wanted}204 "
                ;;
            settings/*)
                put_setting "${entry#settings/}" null >/dev/null
                wanted="${wanted}200 "
                ;;
            *)
                api GET "/$entry"
                api POST "/$entry/retire" "{\"row_version\": $(json_field row_version)}"
                wanted="${wanted}200 "
                ;;
        esac
        made="$made$status "
    done
    api GET /geography/tree
    expect "pkg what came after the groups is taken out again with $version, $(echo "$wanted" | wc -w) records: whatever references there were are erased, the assignments, the people of the owner and whatever contacts the agreements, the contracts, the vendors and the circuits named are removed, the operators, the contacts and the places are retired, whatever there was of capacity lines, registrations, coverage, purchase requests, external systems, contracts, agreements, circuits and circuit groups is retired, marked as removed, ended or cancelled, and whatever weights were set are blank again; the tree of places is empty" \
        "$made$status $(json 'd["roots"]')" "${wanted}200 []"
}

previous_release() {
    local engineer_hid group_hid held

    section "the previous release, $previous_version, with accounts and a changed configuration"
    previous_package
    pair_said
    install_previous

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

    # A previous release that already keeps the inventory is given some to carry over,
    # and with it what the files of this pair make for their migration or release.
    witness_inventory
    particular before

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
    schema_then=$(schema_sum /var/lib/hirdir/hirdir.db)
    events_then=$(table_rows audit_events "$(table_columns audit_events)")
    events_hids_then=$(table_read audit_events hids)
}

upgrade() {
    local backup renewed created name line put_in="" missing="" unsaid=""

    section "apt upgrades $previous_version to $version"
    upgrade_days=$(date -u +%F)
    if apt_get install /srv/debs/hirdir-new.deb; then
        upgrade_days="$upgrade_days $(date -u +%F)"
        pass "pkg apt upgrades hirdir $previous_version to $version"
    else
        fail "pkg apt upgrades hirdir $previous_version to $version"
        tail -n 30 "$work/apt.log"
    fi
    cp "$work/apt.log" "$work/install.log"
    # Read before anything is asked of the new version: a sign-in is an event too.
    if ! migrating || [ -n "$writes_no_event" ]; then no_event_written "$events_then" "$events_hids_then"; fi
    expect "pkg the installed version is $version" "$(installed_version)" "$version"

    backup=$(sed -n 's/^hirdir: the database as it was before this upgrade is kept at //p' "$work/install.log")
    check "pkg the upgrade says where it kept a backup of the database (${backup:-nowhere})" test -n "$backup"
    check "pkg that backup exists" inside test -s "${backup:-/nonexistent}"
    expect "pkg the backup holds the database as it was before the upgrade: its schema is at revision $revision_before" \
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
    # out at its default, and changes nothing that was there. Which settings those are
    # is read from the two packages. Where the new version has none that the previous
    # one had not, the file is left as it is.
    new_settings >"$work/new-settings.txt"
    if [ -s "$work/new-settings.txt" ]; then
        expect "pkg the settings file holds every line the operator had, each as it was and in its order, with the new settings put in among them" \
            "$(settings_kept "$work/settings-before.toml")" "kept more"
        while IFS=$'\t' read -r name line; do
            grep -qxF -- "$line" "$work/settings-now.toml" || missing="$missing$name "
            case $name in "["*) continue ;; esac
            put_in="${put_in:+$put_in, }$name"
            grep -q "^hirdir: /etc/hirdir/config.toml has the new settings of this version.*[ ,]${name}[,.].*Nothing you set was changed" "$work/install.log" ||
                unsaid="$unsaid$name "
        done <"$work/new-settings.txt"
        expect "pkg the value the operator set is still set, and every setting that $version has and $previous_version had not is there, commented out at its default, under its heading ($put_in)" \
            "$(inside grep -cx 'session_hours = 11' /etc/hirdir/config.toml 2>&1) $missing" "1 "
        expect "pkg the file as it was is kept beside it" \
            "$(inside bash -c 'cat /etc/hirdir/config.toml.*.bak | sha256sum' 2>&1)" "$(sha256sum <"$work/settings-before.toml")"
        expect "pkg the upgrade says which settings it put in, each by its name, and that nothing the operator set was changed" \
            "$unsaid" ""
    else
        expect "pkg $version has no setting that $previous_version had not, and the file is as the operator left it, with no copy made beside it" \
            "$(settings_kept "$work/settings-before.toml") $(inside bash -c 'ls /etc/hirdir | grep -c "\.bak$"' 2>&1)" "kept same 0"
        check "pkg and the upgrade says nothing of the settings file" \
            bash -c "! grep -q '/etc/hirdir/config.toml' '$work/install.log'"
    fi
    expect "pkg run again, hirdir-setup --settings finds nothing to change" \
        "$(inside hirdir-setup --settings --yes 2>&1)" \
        "Nothing to change: /etc/hirdir/config.toml has every setting of this version of hirdir."
    # From 0.7.0 the application writes a complete file of its own (D-187): from the
    # file the operator edited, it sets what that file sets, and nothing else.
    if inside hirdir admin config --help >/dev/null 2>&1; then
        expect "pkg hirdir admin config --current writes a complete file that sets what the one the operator edited sets, session_hours = 11, and nothing else, with every other key of this version commented out at its default" \
            "$(inside bash -c 'hirdir admin config --current | /opt/hirdir/python/bin/python3 -I -c "import json, sys, tomllib; print(json.dumps({k: v for k, v in tomllib.loads(sys.stdin.read()).items() if v}))"; hirdir admin config --current | grep -c "^# [a-z_]* = "; hirdir admin config | grep -c "^# [a-z_]* = "' 2>&1 | xargs)" \
            "{access: {session_hours: 11}} $(($(shipped_settings "$deb" | grep -c '^# [a-z_]* = ') - 1)) $(shipped_settings "$deb" | grep -c '^# [a-z_]* = ')"
    fi

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

    if ! migrating; then
        expect "pkg hirdir admin check: the schema is at revision $head, where it was, because $version has no migration after it" \
            "$(inside hirdir admin check 2>&1 | sed -n 's/^schema revision: *//p')" "$head (this version expects $head)"
    else
        expect "pkg hirdir admin check: $crossing brought the schema from $revision_before to $head" \
            "$(inside hirdir admin check 2>&1 | sed -n 's/^schema revision: *//p')" "$head (this version expects $head)"
    fi
    check "pkg hirdir admin check exits 0" inside hirdir admin check
    created=$(migrations "$deb" tables "$revision_before")
    if ! migrating; then
        expect "pkg and the schema is the same, statement for statement: every table, index and trigger" \
            "$(schema_sum /var/lib/hirdir/hirdir.db)" "$schema_then"
    elif [ -n "$created" ]; then
        expect "pkg every table that the migration creates is there ($created)" "$(tables_there "$created")" "$created"
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
        local row_version hid retired wanted place
        api GET /vendors
        expect "pkg the vendor from before is as it was" "$status $(unchanged vendors)" "200 same"
        expect "pkg and every vendor there was is marked reviewed" \
            "$(json '[len(d["items"]) > 0, sorted({v.get("review_status") for v in d["items"]})]')" '[true, ["reviewed"]]'
        api GET "/catalog-entries/$witness_entry"
        expect "pkg the catalog entry from before has its value, and its support weight to two places" \
            "$status $(json_field est_value) $(json_field support_weight)" "200 18000.00 $witness_weight_after"
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
        expect "pkg the catalog entry and the $(($(echo "$wanted" | wc -w) - 1)) items that were not retired, of ${#witness_items[@]}, can be retired with $version" \
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
            expect "pkg the ${#witness_groups[@]} groups are retired, and the $addresses_made addresses and then the two networks are removed, with $version" \
                "$retired$(json_field total)" "${wanted}0"
            if [ "${#witness_undo[@]}" -gt 0 ]; then witness_undone; fi
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
    # From 0.7.0 the file that the package ships is the one the application writes
    # (D-187), and with --current the application sets in it what the file sets.
    if inside hirdir admin config --help >/dev/null 2>&1; then
        expect "pkg hirdir admin config writes the very file that the package ships, every key at its default and commented out, and with --current it sets in it what the file in force sets, which is nothing" \
            "$(inside bash -c 'hirdir admin config | cmp - /usr/share/hirdir/config.toml && hirdir admin config --current | cmp - /etc/hirdir/config.toml && echo same' 2>&1)" same
    fi
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
    # From 0.9.0 the content of reference files is kept there, beside the database.
    if dpkg --compare-versions "$version" ge 0.9.0; then
        expect "pkg and so does /var/lib/hirdir/files, the store of reference files, which the package makes" \
            "$(inside stat -c '%a %U:%G' /var/lib/hirdir/files 2>&1)" "750 hirdir:hirdir"
    fi
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
load_order=(tags vendors catalog-entries contacts vendor-contacts operators regions sites locations contact-assignments owners owner-members networks external-systems agreements contracts contract-contacts purchase-requests purchase-lines items device-groups device-group-members item-replacements addresses contract-coverage registrations capacity-lines circuit-groups circuits circuit-carriers circuit-costs circuit-contacts circuit-devices)
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
# of docs/interfaces.md: 20 MB and 100,000 rows. The first three files name a column that
# no record has, so hirdir refuses each at its first line, whatever its size; the third
# is of 30 MB, which nginx lets through for a reference file.
limit_files() {
    python3 -c '
import sys

work = sys.argv[1]
limit = 20 * 1024 * 1024
head, line = b"no_such_column\n", b"x" * 99 + b"\n"
for name, size in (("at-the-limit.csv", limit), ("over-the-limit.csv", limit + 1), ("thirty.csv", 30 * 1024 * 1024)):
    with open(f"{work}/{name}", "wb") as out:
        out.write(head)
        out.write(line * ((size - len(head)) // len(line)))
        out.write(b"y" * ((size - len(head)) % len(line)))
with open(f"{work}/too-many-rows.csv", "wb") as out:
    out.write(b"label\n")
    out.writelines(b"row-%06d\n" % number for number in range(1, 100_002))' "$work"
}

# The tables that hirdir admin reset clears: the inventory, those of 0.4.0, of 0.5.0, of
# 0.6.0, of 0.7.0 and of 0.8.0 among it, and what was stored about it. A test in packaging/tests/
# fails when a table that a reset clears is not named here.
inventory_tables="tags vendors owners owner_members catalog_entries regions sites locations contacts operators contact_assignments items item_replacements device_groups device_group_members networks addresses idempotency_keys import_jobs import_rows tag_links agreements contracts contract_coverage purchase_requests purchase_lines external_systems registrations capacity_lines capacity_line_targets capacity_records contract_contacts renewal_alert_views circuits circuit_carriers circuit_costs circuit_devices vendor_contacts circuit_contacts circuit_groups circuit_group_members reference_files reference_attachments"

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
    local before items_before tags_before groups_before places_before cover_before name entity rows item_rows hid filter wanted exported limit made

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
    places_before=$(people_and_places)
    cover_before=$(records_of)

    for name in "${load_order[@]}"; do
        entity=${name//-/_}
        rows=$(table 'len(rows)' "examples/$name.csv")
        send "/imports/preview?entity=$entity&file_name=$name.csv" "examples/$name.csv"
        expect "S12 POST $prefix/api/v1/imports/preview with examples/$name.csv as its body: each of its $rows rows is to be created" \
            "$status $(job_counts)" "201 [\"previewed\", $rows, $rows, 0, 0, 0]"
        hid=$(json 'd["job"]["hid"]')
        apply_job "/imports/$hid/apply"
        expect "S12 POST $prefix/api/v1/imports/{hid}/apply creates the $rows" \
            "$status $(job_counts)" "202 [\"applied\", $rows, $rows, 0, 0, 0]"
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
    # What 0.5.0 added to them: regions, sites and locations, contacts and their
    # assignments, and the members of owners, with the items and the groups placed.
    examples_places "$places_before"
    # What 0.6.0 added to them: support agreements, contracts and what they cover,
    # purchase requests and their lines, external systems and registrations, capacity
    # lines, and a replacement.
    examples_cover "$cover_before"

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
    # The one licence of the examples is of quantity 1: a quantity multiplies weight and
    # cost, and 250 of it made nearly all of the examples' cost.
    api GET /reports/summary
    made=$(json 'float(d["totals"]["support_weight"])')
    api GET /reports/management
    expect "pkg the examples weigh and cost what examples/ says: a support weight of 32 and an annual support cost of 67140.00 in all, with the licence for 250 devices counted once" \
        "$made $(json 'd["totals"]["annual_support_cost"]') $(table '[r["quantity"] for r in rows if r["name"] == "NetConfig Manager"]' examples/items.csv)" \
        '32.0 67140.00 ["1"]'

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
        apply_job "/imports/$hid/apply"
        expect "S13 applied, the second import of examples/$name.csv changes nothing" \
            "$status $(job_counts)" "202 [\"applied\", $rows, 0, 0, $rows, 0]"
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
    # snippet of the package tells it: client_max_body_size 100m, the limit of a reference
    # file, which is larger than an import's.
    large_file "$work/large.csv" Cisco C9300-48P
    check "pkg a file of $large_rows items is written that is larger than 1 MB ($(megabytes "$work/large.csv"))" \
        test "$(stat -c %s "$work/large.csv")" -gt 1048576
    send "/imports/preview?entity=items&file_name=large.csv" "$work/large.csv"
    expect "pkg nginx lets it through under $prefix/, and it is previewed: $large_rows items to create" \
        "$status $(job_counts)" "201 [\"previewed\", $large_rows, $large_rows, 0, 0, 0]"
    hid=$(json 'd["job"]["hid"]')
    apply_job "/imports/$hid/apply" --header 'Idempotency-Key: package-test-large-import'
    expect "pkg and applied in the background, with an Idempotency-Key" \
        "$status $(job_counts)" "202 [\"applied\", $large_rows, $large_rows, 0, 0, 0]"
    authorized POST "$prefix/api/v1/imports/$hid/apply" --header 'Idempotency-Key: package-test-large-import'
    expect "pkg sent again with the same key, the apply is answered with the first answer, the job as it was begun, and marked as replayed" \
        "$status $(header idempotency-replayed) $(job_counts)" "202 true [\"applying\", $large_rows, $large_rows, 0, 0, 0]"
    authorized GET "$prefix/api/v1/items" --get --data-urlencode 'filter=hostname:glob:pkgtest-sw-*' --data-urlencode 'limit=1'
    expect "pkg and the $large_rows items are there once" "$status $(json_field total)" "200 $large_rows"

    limit_files
    limit=$((20 * 1024 * 1024))
    send '/imports/preview?entity=tags' "$work/at-the-limit.csv"
    expect "pkg a body of exactly 20 MB passes nginx and is answered by hirdir, which refuses the file for its unknown column" \
        "$status $(header content-type) $(json 'd["errors"][0]["field"]')" "422 application/problem+json column"
    send '/imports/preview?entity=tags' "$work/over-the-limit.csv"
    expect "pkg a body of 20 MB and one byte passes nginx, which takes the 100 MB of a reference file, and is refused by hirdir itself: a 413 that is a problem document, which names the limit, with the request ID that every answer of hirdir carries" \
        "$status $(header content-type) $(json '"is at most 20 MB" in d["detail"]') $([ -n "$(header x-request-id)" ] && echo request-id)" \
        "413 application/problem+json true request-id"
    expect "pkg sent straight to the service, past nginx, a body of that size is refused by hirdir in the same way" \
        "$(past_nginx $((limit + 1)))" "413 application/problem+json"
    send '/imports/preview?entity=tags' "$work/thirty.csv"
    expect "pkg an import of 30 MB is answered by hirdir with the same 413 problem document: hirdir reads the rest of the body before it answers, so nginx, still sending, does not turn the answer into a 502" \
        "$status $(header content-type) $(json '"is at most 20 MB" in d["detail"]')" "413 application/problem+json true"
    send '/imports/preview?entity=tags' "$work/too-many-rows.csv"
    expect "pkg a file of 100,001 rows, which nginx takes, is refused by hirdir with its own 413, and nginx passes that on as it is" \
        "$status $(header content-type) $(json_field title)" "413 application/problem+json Too large"
    check "pkg with the request ID that every answer of hirdir carries" test -n "$(header x-request-id)"

    client_commands "$filter"
    structure
    health_and_counting
    geography
    operators_and_plans
    cover_and_purchases
    first_file
    multiplied_and_seen

    # A file and a link on a location of the examples, from 0.9.0, for the reset to clear
    # with the content of the file.
    api GET '/locations?limit=1'
    hid=$(json '[l["hid"] for l in d["items"]][0]')
    reference_file "$work/reset-plan.pdf" pdf 0.2
    upload "$work/reset-plan.pdf" reset-plan.pdf floor_plan "Plan before the reset" "$hid"
    made=$status
    api POST /reference-files/links "{\"title\": \"Plan kept elsewhere\", \"kind\": \"floor_plan\", \"url\": \"https://www.example.net/plans/reset\", \"attach_to\": [\"$hid\"]}"
    expect "pkg a file and a link on a location of the examples, from 0.9.0, for the reset to clear" "$made $status" "201 201"

    # hirdir admin reset is how a site clears test data, on the server and nowhere else.
    # Here it clears the examples and what structure(), geography(),
    # operators_and_plans(), cover_and_purchases() and multiplied_and_seen() made beside
    # them, a replacement among it, before the backup puts back what the checks need.
    local code=0
    inside hirdir admin reset --yes >"$work/reset.out" 2>&1 || code=$?
    expect "pkg hirdir admin reset refuses while the service is running, and says to stop it" \
        "$code $(grep -c 'stop it first' "$work/reset.out")" "1 1"
    code=0
    inside hirdir admin load-examples >"$work/load-examples.out" 2>&1 || code=$?
    expect "pkg hirdir admin load-examples refuses while the service is running too, and says to stop it" \
        "$code $(grep -c 'stop it first' "$work/load-examples.out")" "1 1"
    check "pkg systemctl stop hirdir, to put the inventory back as it was" inside systemctl stop hirdir.service
    code=0
    inside bash -c 'echo no | hirdir admin reset' >"$work/reset.out" 2>&1 || code=$?
    expect "pkg with the service stopped it asks for the word reset, and without it changes nothing: every table that a reset clears holds rows, the replacements, groups, members, networks and addresses of 0.4.0, the regions, sites, locations, contacts, operators, assignments and members of owners of 0.5.0, the agreements, contracts, coverage, purchase requests, purchase lines, external systems, registrations and capacity lines of 0.6.0, and the targets of a capacity line, the records of the capacity balance, the contacts of the contracts and the renewal alerts that were seen of 0.7.0, and the circuits, their carriers, cost lines, devices and contacts, the contacts of vendors and the circuit groups with their members of 0.8.0, and the references and what they are on of 0.9.0 too" \
        "$code $(grep -c 'nothing was changed' "$work/reset.out") $(inventory_left)" "1 1 $inventory_tables users"
    code=0
    inside hirdir admin reset --yes >"$work/reset.out" 2>&1 || code=$?
    expect "pkg hirdir admin reset --yes clears the inventory, every one of those tables, and keeps the accounts" \
        "$code $(inventory_left)" "0 users"
    expect "pkg it erases the content of the file from the store, says so, and its backup holds it beside it" \
        "$(grep -c '^the content of 1 files was erased from /var/lib/hirdir/files; the backup holds it in /var/lib/hirdir/backups/files$' "$work/reset.out") $(inside find /var/lib/hirdir/files -type f ! -path '*/.incoming/*' 2>&1 | wc -l) $(inside test -f "/var/lib/hirdir/backups/files/$(sha "$work/reset-plan.pdf" | cut -c1-2)/$(sha "$work/reset-plan.pdf")" && echo held)" \
        "1 0 held"
    expect "pkg it took a backup first and says how to put it back" \
        "$(grep -c '^backup: /var/lib/hirdir/backups/hirdir-' "$work/reset.out") $(grep -c 'hirdir admin restore /var/lib/hirdir/backups/hirdir-' "$work/reset.out")" "1 1"

    # hirdir admin load-examples loads the examples into the empty inventory that the
    # reset left, from the copy inside the application, which a host whose dpkg leaves
    # out /usr/share/doc has too, and a reset takes them again (P-166).
    local example_files
    example_files=$(inside bash -c 'ls /usr/share/doc/hirdir/examples/*.csv | wc -l')
    code=0
    inside hirdir admin load-examples >"$work/load-examples.out" 2>&1 || code=$?
    expect "pkg hirdir admin load-examples loads each of the $example_files files of the examples, from inside the application, into the inventory that the reset emptied" \
        "$code $(grep -c '^loading the examples from /opt/hirdir/.*/hirdir/examples:$' "$work/load-examples.out") $(grep -cE '^ +[0-9,]+  [a-z-]+[.]csv$' "$work/load-examples.out") $(grep -c '^loaded [0-9,]* records of the examples$' "$work/load-examples.out")" \
        "0 1 $example_files 1"
    expect "pkg the examples inside the application are those in /usr/share/doc/hirdir/examples" \
        "$(inside bash -c 'cd /usr/share/doc/hirdir/examples && for f in *.csv; do cmp -s "$f" /opt/hirdir/venv/lib/python*/site-packages/hirdir/examples/"$f" || echo "$f"; done; echo same')" same
    code=0
    inside hirdir admin load-examples >"$work/load-examples.out" 2>&1 || code=$?
    expect "pkg a second hirdir admin load-examples refuses, since the inventory holds the examples, and changes nothing" \
        "$code $(grep -c '^hirdir: the inventory is not empty' "$work/load-examples.out")" "1 1"
    code=0
    inside hirdir admin reset --yes >"$work/reset.out" 2>&1 || code=$?
    expect "pkg hirdir admin reset takes the examples again, every one of the tables of the inventory, and keeps the accounts" \
        "$code $(inventory_left)" "0 users"
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

# ---- reference files --------------------------------------------------------------------

# reference_file PATH png|pdf MEGABYTES: write a file of about that size that is what its
# name says, a PNG picture or a PDF, made of bytes that no other file has, so that no
# two are ever the same content.
reference_file() {
    python3 -c '
import os, sys, zlib

path, kind, size = sys.argv[1], sys.argv[2], int(float(sys.argv[3]) * 1024 * 1024)
if kind == "png":
    def chunk(name, data):
        body = name + data
        return len(data).to_bytes(4, "big") + body + zlib.crc32(body).to_bytes(4, "big")
    width = 1024
    height = max(1, size // (width * 3 + 1))
    rows = b"".join(b"\x00" + os.urandom(width * 3) for _ in range(height))
    header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 2, 0, 0, 0])
    content = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows, 0))
               + chunk(b"IEND", b""))
else:
    head, tail = b"%PDF-1.7\n% A fictional document, for the package test\n%", b"\n%%EOF\n"
    content = head + os.urandom(max(0, size - len(head) - len(tail))) + tail
with open(path, "wb") as out:
    out.write(content)' "$@"
}

# sha FILE: the SHA-256 of a file on the host.
sha() { sha256sum "$1" | cut -d' ' -f1; }

# upload FILE NAME KIND TITLE RECORD...: POST a file as the body of a request to
# /reference-files under $prefix, to be put on the records named by their HIDs, as the
# web UI and hirdir references add do. A large file has two minutes. The pass that
# installs no nginx sends it inside the container, straight to the service, as api does.
upload() {
    local file=$1 query
    query=$(python3 -c '
import sys, urllib.parse
print(urllib.parse.urlencode([("file_name", sys.argv[1]), ("kind", sys.argv[2]), ("title", sys.argv[3])]
                             + [("attach_to", record) for record in sys.argv[4:]]))' "${@:2}")
    if [ "$mode" = failed-upgrade ]; then
        # Not into /tmp: systemd mounts a tmpfs there inside the container, over the
        # directory that docker cp writes into, so a file copied there is never seen.
        docker cp --quiet "$file" "$container:/srv/upload" || true
        inside /opt/hirdir/python/bin/python3 -I -c '
import sys, urllib.error, urllib.request

with open("/srv/upload", "rb") as sent:
    request = urllib.request.Request(
        "http://127.0.0.1:8715/api/v1/reference-files?" + sys.argv[2],
        data=sent.read(),
        method="POST",
        headers={"Content-Type": "application/octet-stream", "Authorization": "Bearer " + sys.argv[1]},
    )
try:
    answer = urllib.request.urlopen(request, timeout=120)
except urllib.error.HTTPError as error:
    answer = error
print(answer.code)
sys.stdout.write(answer.read().decode())' "$token" "$query" >"$work/answer" 2>&1 || true
        status=$(head -n 1 "$work/answer")
        tail -n +2 "$work/answer" >"$work/body"
        return 0
    fi
    authorized POST "$prefix/api/v1/reference-files?$query" --header 'Content-Type: application/octet-stream' \
        --data-binary "@$file" --max-time 120
}

# downloaded HID FILE: download the content of a reference through nginx, asking for it
# compressed, and say how it came: its status, whether it is FILE byte for byte, its
# type, and the headers that keep a browser from running it.
downloaded() {
    authorized GET "$prefix/api/v1/reference-files/$1/content" --header 'Accept-Encoding: gzip' --max-time 120
    local same=differs
    if [ "$(sha "$work/body")" = "$(sha "$2")" ]; then same=same; fi
    printf '%s %s %s %s %s %s encoding:%s' "$status" "$same" "$(header content-type)" \
        "$(header content-disposition | cut -d';' -f1)" "$(header x-content-type-options)" \
        "$(header content-security-policy | grep -o sandbox)" "$(header content-encoding)"
}

# stored_sums HID...: the SHA-256 of the content of each reference, downloaded straight
# from the service inside the container with the token in $token, one to a line, or the
# status where it was not given. For every pass, the one with no nginx among them.
stored_sums() {
    inside /opt/hirdir/python/bin/python3 -I -c '
import hashlib, sys, urllib.error, urllib.request

for hid in sys.argv[2:]:
    request = urllib.request.Request(
        f"http://127.0.0.1:8715/api/v1/reference-files/{hid}/content",
        headers={"Authorization": "Bearer " + sys.argv[1]},
    )
    try:
        print(hashlib.sha256(urllib.request.urlopen(request, timeout=60).read()).hexdigest())
    except urllib.error.HTTPError as error:
        print(error.code)' "$token" "$@" 2>&1
}

# in_clean COMMAND...: run a command in the second container, which has never had hirdir.
in_clean() { docker exec --env DEBIAN_FRONTEND=noninteractive "$clean_container" "$@"; }
clean_container=""

# clean_install: start a second container from the same image, with no port published,
# and install the package in it, as on another host. Prints nothing; says how it went.
clean_install() {
    local state=starting
    clean_container=$container-clean
    if ! docker run --detach --name "$clean_container" --privileged --cgroupns=private \
        --tmpfs /run --tmpfs /run/lock "$image" >/dev/null 2>"$work/docker-run-clean.log"; then
        cat "$work/docker-run-clean.log"
        return 1
    fi
    for _ in $(seq 60); do
        state=$(in_clean systemctl is-system-running 2>/dev/null || true)
        case $state in running | degraded) break ;; esac
        sleep 1
    done
    in_clean mkdir -p /srv/debs
    docker cp --quiet "$deb" "$clean_container:/srv/debs/hirdir-new.deb"
    in_clean chmod -R a+rX /srv/debs
    in_clean apt-get -o Dpkg::Use-Pty=0 --yes update >"$work/apt-clean.log" 2>&1 &&
        in_clean apt-get -o Dpkg::Use-Pty=0 --yes install /srv/debs/hirdir-new.deb >>"$work/apt-clean.log" 2>&1
}

# clean_downloads USERNAME ACCESS_CODE HID...: in the second container, sign in straight
# to the service and download the content of each reference. Prints the HID and the
# SHA-256 of what came, or the status, one to a line.
clean_downloads() {
    in_clean /opt/hirdir/python/bin/python3 -I -c '
import hashlib, json, sys, urllib.error, urllib.request

def call(path, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request("http://127.0.0.1:8715/api/v1" + path, data=body, headers=headers)
    return urllib.request.urlopen(request, timeout=60)

signed = call("/auth/sign-in", json.dumps({"username": sys.argv[1], "access_code": sys.argv[2]}).encode())
token = json.load(signed)["token"]
for hid in sys.argv[3:]:
    try:
        print(hid, hashlib.sha256(call(f"/reference-files/{hid}/content", token=token).read()).hexdigest())
    except urllib.error.HTTPError as error:
        print(hid, error.code)' "$@" 2>&1
}

# reference_files: S51 and S53 through nginx under the prefix, and what the acceptance
# test cannot reach: the limits of nginx and of hirdir, which differ, and a backup
# restored on another host with the files beside it. The inventory is backed up first
# and put back at the end, as files() does.
reference_files() {
    section "reference files uploaded and downloaded through nginx under $prefix/, and restored on another host"
    local before backup made region site room photo plan survey listed clean_restore names wanted

    before=$(inside hirdir admin backup 2>/dev/null || true)
    check "pkg hirdir admin backup keeps the inventory as it is before any reference file is uploaded (${before:-no backup})" \
        inside test -s "${before:-/nonexistent}"
    api POST /regions '{"name": "Reference Land"}'
    made=$status
    region=$(json_field hid)
    api POST /sites "{\"name\": \"Reference Site\", \"region_hid\": \"$region\"}"
    made="$made $status"
    site=$(json_field hid)
    api POST /locations "{\"name\": \"Reference Room\", \"site_hid\": \"$site\", \"kind\": \"room\"}"
    expect "pkg a region, a site in it and a room at the site, to put the files on" "$made $status" "201 201 201"
    room=$(json_field hid)

    # A picture and a PDF of a few megabytes on the room, and on the site a file of 30 MB,
    # which is over the limit of an import and under that of a reference file.
    reference_file "$work/rack-row.png" png 3
    reference_file "$work/room-plan.pdf" pdf 4
    reference_file "$work/site-survey.pdf" pdf 30
    upload "$work/rack-row.png" rack-row.png photograph "Rack row" "$room"
    photo=$(json_field hid)
    expect "S51 through nginx under $prefix/, a picture of $(megabytes "$work/rack-row.png") is uploaded to the room: a file, typed image/png, of its size and its checksum, which the page shows, on the room" \
        "$status $(json '[d["form"], d["media_type"], d["size_bytes"], d["sha256"], d["shown_in_page"], [a["record_hid"] for a in d["attachments"]]]')" \
        "201 [\"file\", \"image/png\", $(stat -c %s "$work/rack-row.png"), \"$(sha "$work/rack-row.png")\", true, [\"$room\"]]"
    upload "$work/room-plan.pdf" room-plan.pdf floor_plan "Room plan" "$room"
    plan=$(json_field hid)
    expect "S51 and a PDF of $(megabytes "$work/room-plan.pdf"), a floor plan, which is downloaded rather than shown" \
        "$status $(json '[d["media_type"], d["size_bytes"], d["sha256"], d["shown_in_page"]]')" \
        "201 [\"application/pdf\", $(stat -c %s "$work/room-plan.pdf"), \"$(sha "$work/room-plan.pdf")\", false]"
    upload "$work/site-survey.pdf" site-survey.pdf other "Site survey" "$site"
    survey=$(json_field hid)
    expect "S53 a file of $(megabytes "$work/site-survey.pdf") on the site, over the 20 MB of an import and under the 100 MB of a reference file, passes nginx and is taken" \
        "$status $(json '[d["size_bytes"], d["sha256"]]')" "201 [$(stat -c %s "$work/site-survey.pdf"), \"$(sha "$work/site-survey.pdf")\"]"
    api GET "/locations/$room/references?limit=1000"
    expect "S51 the room lists its two as its own and the survey of its site after them" \
        "$status $(json '[[r["hid"], r["source"]] for r in d["items"]]')" \
        "200 [[\"$photo\", \"own\"], [\"$plan\", \"own\"], [\"$survey\", \"site\"]]"
    expect "S51 the picture comes back through nginx byte for byte, as image/png, as an attachment, not to be sniffed, sandboxed, and not compressed again though the client asks for gzip" \
        "$(downloaded "$photo" "$work/rack-row.png")" "200 same image/png attachment nosniff sandbox encoding:"
    expect "S51 and so does the PDF, as application/pdf" \
        "$(downloaded "$plan" "$work/room-plan.pdf")" "200 same application/pdf attachment nosniff sandbox encoding:"
    expect "S53 and the file of 30 MB" \
        "$(downloaded "$survey" "$work/site-survey.pdf")" "200 same application/pdf attachment nosniff sandbox encoding:"
    # A body over the larger limit is refused by nginx before it reaches hirdir.
    truncate -s $((100 * 1024 * 1024 + 1)) "$work/over-the-reference-limit.pdf"
    upload "$work/over-the-reference-limit.pdf" too-large.pdf other "Too large" "$room"
    expect "S53 a body of 100 MB and one byte is refused by nginx: a 413 with the page of nginx, which is not a problem document and has no request ID of hirdir" \
        "$status $(header content-type) request-id:$(header x-request-id)" "413 text/html request-id:"
    rm -f "$work/over-the-reference-limit.pdf"

    # The backup holds the files beside it, once each, linked to the store.
    backup=$(inside hirdir admin backup 2>"$work/backup.log" || true)
    check "S53 hirdir admin backup prints the file it wrote ($backup), and says nothing more" \
        bash -c "[ -n '$backup' ] && [ ! -s '$work/backup.log' ]"
    made=""
    for listed in "$work/rack-row.png" "$work/room-plan.pdf" "$work/site-survey.pdf"; do
        names=$(sha "$listed")
        made="$made $(inside bash -c "s=/var/lib/hirdir/files/${names:0:2}/$names; b=/var/lib/hirdir/backups/files/${names:0:2}/$names; [ \"\$(stat -c %i \"\$s\")\" = \"\$(stat -c %i \"\$b\")\" ] && stat -c '%a:%U' \"\$b\"" 2>&1 || echo not-linked)"
    done
    expect "S53 the content of each of the three is in /var/lib/hirdir/backups/files/, under its checksum, a hard link to the file in the store, the hirdir user's alone" \
        "$made" " 640:hirdir 640:hirdir 640:hirdir"
    expect "pkg /var/lib/hirdir/backups/files/ is the hirdir user's alone, as the backups are" \
        "$(inside stat -c '%a %U:%G' /var/lib/hirdir/backups/files 2>&1)" "750 hirdir:hirdir"

    # Another host: the package installed, the backup copied there, and then the files
    # beside it, as docs/install.md says to.
    rm -rf "$work/copied" && mkdir -p "$work/copied"
    docker cp --quiet "$container:$backup" "$work/copied/" || true
    docker cp --quiet "$container:/var/lib/hirdir/backups/files" "$work/copied/files" || true
    if clean_install; then
        pass "S53 the package installs on a second, clean host"
    else
        fail "S53 the package installs on a second, clean host"
        tail -n 20 "$work/apt-clean.log"
    fi
    in_clean systemctl stop hirdir.service || true
    docker cp --quiet "$work/copied/${backup##*/}" "$clean_container:/var/lib/hirdir/backups/" || true
    in_clean chown -R hirdir:hirdir /var/lib/hirdir/backups || true
    clean_restore=0
    in_clean hirdir admin restore "/var/lib/hirdir/backups/${backup##*/}" >"$work/restore-clean.log" 2>&1 || clean_restore=$?
    expect "S53 copied there without the files beside it, the backup is not restored: hirdir admin restore says that the three files are missing, names them, and changes nothing" \
        "$clean_restore $(grep -c "3 of the 3 reference files" "$work/restore-clean.log") $(grep -c 'Nothing was changed' "$work/restore-clean.log") $(grep -c "$photo (rack-row.png)" "$work/restore-clean.log") $(in_clean test -e /var/lib/hirdir/hirdir.db.before-restore && echo aside || echo none)" \
        "1 1 1 1 none"
    docker cp --quiet "$work/copied/files" "$clean_container:/var/lib/hirdir/backups/files" || true
    in_clean chown -R hirdir:hirdir /var/lib/hirdir/backups || true
    clean_restore=0
    in_clean hirdir admin restore "/var/lib/hirdir/backups/${backup##*/}" >"$work/restore-clean.log" 2>&1 || clean_restore=$?
    expect "S53 with the files/ beside it, hirdir admin restore puts the backup in place and the content of the three into the store" \
        "$clean_restore $(grep -c '^the content of 3 files was taken from /var/lib/hirdir/backups/files$' "$work/restore-clean.log")" "0 1"
    in_clean systemctl start hirdir.service || true
    for _ in $(seq 30); do
        if in_clean /opt/hirdir/python/bin/python3 -I -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8715/api/v1/health/ready", timeout=2)' 2>/dev/null; then break; fi
        sleep 1
    done
    wanted="$photo $(sha "$work/rack-row.png")
$plan $(sha "$work/room-plan.pdf")
$survey $(sha "$work/site-survey.pdf")"
    expect "S53 there, the Admin signs in with the access code from the first host, and every file comes back byte for byte" \
        "$(clean_downloads "$admin" "$admin_code" "$photo" "$plan" "$survey")" "$wanted"
    expect "S53 and hirdir admin check there counts the three, and exits 0" \
        "$(in_clean hirdir admin check 2>&1 | grep -c '^reference files: 3 with content, kept in 3 files of ') $(in_clean hirdir admin check >/dev/null 2>&1 && echo 0)" "1 0"
    expect "S53 the store there holds each file once, linked to the files beside the backup as a backup links them, the hirdir user's alone" \
        "$(in_clean bash -c 'find /var/lib/hirdir/files -type f ! -path "*/.incoming/*" -printf "%m:%u:%n\n" | sort | uniq -c | xargs' 2>&1)" "3 640:hirdir:2"
    docker rm --force "$clean_container" >/dev/null 2>&1 || true
    clean_container=""

    # Back on this host, the inventory as it was before the files: the restore sets their
    # content aside, beside the store, as it does the database.
    check "pkg systemctl stop hirdir, to put the inventory back as it was before the files" inside systemctl stop hirdir.service
    clean_restore=0
    inside hirdir admin restore "${before:-/nonexistent}" >"$work/restore.log" 2>&1 || clean_restore=$?
    expect "pkg hirdir admin restore of the backup taken before them sets aside the content of the three, which that backup does not name, in /var/lib/hirdir/files.before-restore/" \
        "$clean_restore $(grep -c '^the content of 3 files that the restored database does not name is kept at /var/lib/hirdir/files.before-restore$' "$work/restore.log") $(inside bash -c 'find /var/lib/hirdir/files -type f ! -path "*/.incoming/*" | wc -l; find /var/lib/hirdir/files.before-restore -type f | wc -l' 2>&1 | xargs)" \
        "0 1 0 3"
    check "pkg systemctl start hirdir" inside systemctl start hirdir.service
    if wait_ready; then
        pass "pkg hirdir answers again through nginx"
    else
        fail "pkg hirdir answers again through nginx (got $status)"
    fi
    api GET '/reference-files?limit=1'
    made="$status $(json_field total)"
    api GET '/regions?include_drafts=true&include_archived=true&limit=1000'
    expect "pkg and there is no reference and no Reference Land, for the checks that follow" \
        "$made $status $(json '[r["name"] for r in d["items"] if r["name"] == "Reference Land"]')" "200 0 200 []"
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

# matches PATTERN FILE: how many lines of a file match an extended pattern. Where
# nothing matches it prints 0 and does not fail, so that it can be kept in a variable:
# under set -e a grep that finds nothing would stop the pass there.
matches() { grep -c -E -- "$1" "$2" || true; }

# printed_columns FILE COLUMN...: the cells of the named columns of a table that a client
# command printed, a row on a line with a colon between its cells. The table is found by
# its heading, which names the columns in capitals, and each cell is read from where its
# heading begins to where the next one does, so that a blank cell stays a cell.
printed_columns() {
    python3 -c '
import re, sys

lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
wanted = [name.upper() for name in sys.argv[2:]]
for at, line in enumerate(lines):
    heads = [(found.group(), found.start()) for found in re.finditer(r"\S+", line)]
    if set(wanted) <= {name for name, _ in heads}:
        break
else:
    sys.exit()
starts = [start for _, start in heads] + [None]
places = {name: (starts[n], starts[n + 1]) for n, (name, _) in enumerate(heads)}
for row in lines[at + 1:]:
    if not row.strip():
        break
    print(":".join(row[slice(*places[name])].strip() for name in wanted))' "$@"
}

# cli_run OUT ARGUMENT...: run a client command with its output in OUT and what it says in
# $work/cli.err. Sets $code to what it exited with.
cli_run() {
    local out=$1
    shift
    code=0
    cli "$@" >"$out" 2>"$work/cli.err" || code=$?
}

client_commands() {
    section "the client commands of the package: hirdir import, export, items, groups, report, geography, locations, regions, sites, operators, agreements, contracts, purchases, systems, registrations, capacity and vendors"
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

    client_places
    client_cover
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

    # S21: the master is replaced, and the stack is the same record. The master that is
    # replaced is the one intended and, here, the one seen as well.
    old=${switches[2]}
    api GET "/device-groups/$stack"
    api PATCH "/device-groups/$stack" "{\"row_version\": $(json_field row_version), \"observed_master_hid\": \"$old\"}"
    expect "S21 the master that is to be replaced is seen to be master too: the one intended and the one seen are the same switch" \
        "$status $(json '[d["serial_number"], d["serial_source"], d["master_as_intended"]]')" '200 ["PKG0000S003", "observed", true]'
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
    expect "S21 the new switch has the role of the one that left, the master intended, and not its observation: nobody has seen it as master, so no master is seen and the serial number is the intended one's" \
        "$(json '[d["master"]["serial_number"], d["observed_master_hid"], d["observed_master"], d["master_observed_at"], d["serial_source"]]')" \
        '["PKG0000S009", null, null, null, "intended"]'
    printf '%s\n' 'group,item,role' 'pkgtest-stack,PKG0000S001,master' 'pkgtest-stack,PKG0000S004,master' >"$work/two-masters.csv"
    send "/imports/preview?entity=device_group_members&file_name=two-masters.csv" "$work/two-masters.csv"
    made="$status $(job_counts)"
    printf '%s\n' 'group,item,observed_master' 'pkgtest-stack,PKG0000S001,true' 'pkgtest-stack,PKG0000S004,true' >"$work/two-seen.csv"
    send "/imports/preview?entity=device_group_members&file_name=two-seen.csv" "$work/two-seen.csv"
    expect "S19 a file of members that names two intended masters of the stack is previewed with its second row rejected, and so is one that names two observed masters" \
        "$made $status $(job_counts)" '201 ["previewed", 2, 0, 1, 0, 1] 201 ["previewed", 2, 0, 1, 0, 1]'

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
    api GET "$every_address"
    made=$(json '[sum(1 for a in d["items"] if a["family"] == 6), d["total"] <= 1000]')
    api GET '/addresses?filter=family:eq:6&limit=1000'
    made="$made $(json '[d["total"], sorted({a["family"] for a in d["items"]}), sum(1 for a in d["items"] if a["address"] == "2001:db8::10")]')"
    api GET '/addresses?sort=-family&limit=1000'
    expect "pkg GET $prefix/api/v1/addresses filters by the family of an address, finding the IPv6 addresses there are and no other, and sorts by it" \
        "$made $status $(json '[a["family"] for a in d["items"]] == sorted((a["family"] for a in d["items"]), reverse=True)')" \
        "$(json '[sum(1 for a in d["items"] if a["family"] == 6), True]') $(json '[sum(1 for a in d["items"] if a["family"] == 6), [6], 1]') 200 true"
    api POST /exports '{"entity": "addresses", "format": "csv", "columns": ["address", "family"], "filter": "family:eq:6"}'
    expect "pkg and POST $prefix/api/v1/exports writes the family as a column when it is asked for, and filters by it" \
        "$status $(table '[head, sorted({r["family"] for r in rows}), sum(1 for r in rows if r["address"] == "2001:db8::10")]')" \
        '200 [["hid", "address", "family"], ["6"], 1]'

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
    # The moment of an observation. A person who says again what is observed has looked
    # again, and the moment is now. It is not cleared by itself, it is not in the
    # future, and with no zone it is in the application's time zone, which is
    # America/New_York on an installation that has not changed it.
    api PATCH "/items/$item" '{"row_version": 4, "observed_status": "online"}'
    expect "pkg observed online is stated again, as it is, with no moment: the moment is now and no longer the one given before, at the next row_version" \
        "$status $(json '[d["observed_status"], d["observed_at"] not in (None, "2026-11-02T15:00:00Z"), d["row_version"]]')" \
        '200 ["online", true, 5]'
    api PATCH "/items/$item" '{"row_version": 5, "observed_at": null}'
    made="$status $(json 'd["errors"][0]["field"]')"
    api PATCH "/items/$item" "{\"row_version\": 5, \"observed_status\": \"online\", \"observed_at\": \"$(date -u --date='+3 days' +%FT%TZ)\"}"
    made="$made $status $(json 'd["errors"][0]["field"]')"
    api PATCH "/items/$item" '{"row_version": 5, "observed_status": "online", "observed_at": "2026-11-03T09:00:00"}'
    expect "pkg the moment is not cleared by itself, and one that is three days ahead is refused; one written with no zone is in the application's time zone, so nine in the morning in New York is two in the afternoon in UTC" \
        "$made $status $(json '[d["observed_at"], d["row_version"]]')" \
        '422 observed_at 422 observed_at 200 ["2026-11-03T14:00:00Z", 6]'
    made=""
    for number in '2026-11-03T09:00:00' '2026-11-03T09:00:00Z' '2026-11-03T14:00:00Z' '2026-11-03T09:00:00-05:00'; do
        authorized GET "$prefix/api/v1/items" --get --data-urlencode "filter=hostname:eq:pkgtest-health-01 observed_at:eq:$number"
        made="$made$status $(json_field total) "
    done
    expect "pkg a filter on the moment reads a value with no zone the same way: 09:00 finds the item; 09:00Z, which is that hour in UTC, does not; 14:00Z and 09:00-05:00, which are that moment, do" \
        "$made" "200 1 200 0 200 1 200 1 "
    authorized GET "$prefix/api/v1/items" --get --data-urlencode 'filter=hostname:eq:pkgtest-health-01 observed_at:gte:2026-11-03T09:00 observed_at:lt:2026-11-03T09:01'
    made="$status $(json_field total)"
    authorized GET "$prefix/api/v1/items" --get --data-urlencode 'filter=hostname:eq:pkgtest-health-01 observed_at:gte:2026-11-03T09:00Z observed_at:lt:2026-11-03T09:01Z'
    expect "pkg and so does a filter for a stretch of time: the minute from 09:00 holds the item when it is written with no zone, and not when it is written with Z" \
        "$made $status $(json_field total)" "200 1 200 0"
    api PATCH "/items/$item" '{"row_version": 6, "observed_status": null}'
    expect "pkg the observation is taken back: its moment goes with it, and the condition alone decides the health" \
        "$status $(json '[d["observed_status"], d["observed_at"], d["lifecycle_state"]]') $(health)" \
        '200 [null, null, "Prod"] ["degraded", ["its condition is degraded"]]'
    authorized GET "$prefix/api/v1/items" --get --data-urlencode 'filter=health:eq:degraded hostname:glob:pkgtest-*'
    expect "pkg GET $prefix/api/v1/items finds it by its health, which is stored nowhere" \
        "$status $(json '[i["hostname"] for i in d["items"]]')" '200 ["pkgtest-health-01"]'
    api GET "/items/$item/history"
    expect "pkg each of those changes is in its history, the condition and the observation as fields like any other, and a second look as a change of the moment alone" \
        "$status $(json '[sorted(c["field"] for c in e["changes"]) for e in d["items"][:6]]')" \
        '200 [["observed_at", "observed_status"], ["observed_at"], ["observed_at"], ["condition", "observed_at", "observed_status"], ["observed_at", "observed_status"], ["condition"]]'
    summary 'hostname:eq:pkgtest-health-01'
    expect "pkg GET $prefix/api/v1/reports/summary counts it as one component that is degraded" \
        "$status $(totals) $(json 'd["totals"]["by_health"]')" \
        '200 [1, 1, 1, 1.0] {"degraded": 1, "failed": 0, "good": 0, "unknown": 0}'

    # A condition that a site adds to the list says nothing of health either way, and
    # the reason for a health that is not known names the condition that is there.
    api POST /choices '{"list": "item_condition", "value": "on-the-bench", "label": "On the bench"}'
    made=$status
    api POST /items "{\"catalog_entry_hid\": \"$model\", \"serial_number\": \"PKG0000H002\", \"hostname\": \"pkgtest-health-02\", \"lifecycle_state\": \"Prod\", \"condition\": \"on-the-bench\"}"
    expect "pkg a condition of the site's own is added to the list, and an item that has it has a health that is not known: the reason names the condition and says that it says nothing of health" \
        "$made $status $(json_field condition) $(health)" \
        '201 201 on-the-bench ["unknown", ["its condition is on-the-bench, which says nothing of its health, and nothing is observed"]]'
    second=$(json_field hid)
    api PATCH "/items/$second" '{"row_version": 1, "condition": "untested"}'
    made="$status $(health)"
    api PATCH "/items/$second" '{"row_version": 2, "condition": "on-the-bench", "observed_status": "present"}'
    expect "pkg untested, its health is not known either, and the reason says untested; with the site's condition again and observed present, what is observed decides: good" \
        "$made $status $(json 'd["health"]["value"]')" \
        '200 ["unknown", ["its condition is untested, and nothing is observed"]] 200 good'

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

    # The item list sorted by health: the worst first, and what is not known before the
    # good. Four of the items made here have the four kinds between them.
    api PATCH "/items/$first" '{"row_version": 1, "condition": "failed"}'
    made=$status
    authorized GET "$prefix/api/v1/items" --get --data-urlencode 'sort=health' \
        --data-urlencode 'filter=hostname:in:pkgtest-health-01,pkgtest-lone-01,pkgtest-lone-02,pkgtest-fw-01'
    expect "pkg GET $prefix/api/v1/items sorted by health puts the worst first: failed, degraded, unknown, good" \
        "$made $status $(json '[[i["hostname"], i["health"]["value"]] for i in d["items"]]')" \
        '200 200 [["pkgtest-fw-01", "failed"], ["pkgtest-health-01", "degraded"], ["pkgtest-lone-01", "unknown"], ["pkgtest-lone-02", "good"]]'
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
    api POST "/device-groups/$cluster/members" "{\"members\": [{\"item_hid\": \"$other\", \"role\": \"member\"}]}"
    made="$status $(json 'd["errors"][0]["field"]')"
    api GET "/items/$first"
    api POST "/items/$first/replace" "{\"row_version\": $(json_field row_version), \"reason\": \"rma\", \"new_item_hid\": \"$other\"}"
    check "pkg an item that is Released joins no group: it is refused as a member of the cluster again, and as the item that takes a member's place in a replacement ($made $status)" \
        bash -c "[ '$made $status' = '422 item_hid 422' ] && grep -q \"has left the team's hands\" '$work/body'"
    api GET "/items/$first"
    api POST "/items/$first/transition" "{\"to\": \"Archived\", \"reason\": \"disposed\", \"row_version\": $(json_field row_version), \"force\": true}"
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

# ---- regions, sites, locations, contacts and the people of an owner --------------------------

# places PATH...: for each path, the items and the components that the tree of the last
# answer has at or beneath that place, or null where the tree has no such place.
places() {
    python3 -c '
import json, sys

found = {}

def walk(node):
    found[node["path"]] = [node["items"], node["component_count"]]
    for child in node["children"]:
        walk(child)

for root in json.load(open(sys.argv[1], encoding="utf-8"))["roots"]:
    walk(root)
print(json.dumps([found.get(path) for path in sys.argv[2:]]))' "$work/body" "$@"
}

# What the three counts beside the tree of the last answer say, each as items and
# components: totals, unplaced and hidden.
beside() {
    json '[[d[k]["items"], d[k]["component_count"]] for k in ("totals", "unplaced", "hidden")]'
}

# Whether the roots of the last tree, what is nowhere and what is hidden add up to the
# totals, in items and in components.
adds_up() {
    json 'all(sum(r[k] for r in d["roots"]) + d["unplaced"][k] + d["hidden"][k] == d["totals"][k] for k in ("items", "component_count"))'
}

# in_force ROLE: what the last answer of .../effective has for one role: the level it
# is from, the path of that level, whether a level stopped the search, and the names.
in_force() {
    json '[[c["source"], c["source_path"], c["stopped"], [p["name"] for p in c["contacts"]]] for c in d["contacts"] if c["role"] == "'"$1"'"][0]'
}

# examples_within PATH: how many items examples/items.csv has at or beneath a place, in
# the view a list shows by default: its own location, or that of the item it is in, and
# neither a draft nor an archived one. With no path, those that are nowhere.
examples_within() {
    python3 -c '
import csv, sys

rows = list(csv.DictReader(open("examples/items.csv", encoding="utf-8", newline="")))
known = {r[key]: r for r in rows for key in ("serial_number", "hostname", "asset_tag", "name") if r[key]}

def own(r, field):
    while not r[field] and r["parent"]:
        r = known[r["parent"]]
    return r[field]

def within(r, path):
    where = own(r, "location")
    return (where == path or where.startswith(path + " > ")) if path else not where

view = [r for r in rows if r["record_status"] == "active" and own(r, "lifecycle_state") != "Archived"]
print(sum(1 for r in view if within(r, sys.argv[1])))' "${1:-}"
}

# location_at PATH: the HID of the location that has that path.
location_at() {
    authorized GET "$prefix/api/v1/locations" --get --data-urlencode "filter=location:within:$1" \
        --data-urlencode 'include_drafts=true'
    json '[l["hid"] for l in d["items"] if l["path"] == "'"$1"'"][0]'
}

# How many regions, sites, locations, contacts, operators, contact assignments and
# members of owners there are, the drafts and the retired among them, on one line.
people_and_places() {
    local name counted=""
    for name in regions sites locations contacts operators contact-assignments; do
        api GET "/$name?include_drafts=true&include_archived=true&limit=1000"
        counted="$counted$(json 'd["total"] if isinstance(d, dict) else len(d)') "
    done
    api GET '/owners?include_archived=true&limit=1000'
    echo "$counted$(json 'sum(len(o["members"]) for o in d["items"])')"
}

# examples_places BEFORE: what the examples show of 0.5.0, looked for while they are
# loaded: the tree of places with what the files put in each, a draft site that the
# default view leaves out, the contacts of a room with the level each came from, an
# office that takes no shipments, and the one item that is with an owner outside the
# team. BEFORE is what people_and_places said before the files were loaded: after an
# upgrade, the places that the upgrade pass made are there, retired.
examples_places() {
    local name made room rack store office wanted=""
    room='Americas > Central > Site-2 > Building 1 > Floor 1 > Room 102'
    rack="$room > Rack A1"
    store='Americas > Central > Site-2 > Store Room'
    office='Americas > East > Site-1 > Comms Room'

    for name in regions sites locations contacts operators contact-assignments owner-members; do
        wanted="$wanted$(table 'len(rows)' "examples/$name.csv") "
    done
    expect "S12 the regions, the sites, the locations, the contacts, the operators, the assignments and the members of the owners of the examples are there, the draft site and its room among them: each list holds what its file holds ($wanted), beside what there was ($1)" \
        "$(people_and_places)" \
        "$(python3 -c 'import sys; print(*(int(a) + int(b) for a, b in zip(sys.argv[1].split(), sys.argv[2].split())))' "$1" "$wanted")"

    api GET '/geography/tree?locations=false'
    expect "S24 GET $prefix/api/v1/geography/tree?locations=false shows the regions and sites of the examples: Americas with its two regions, Central with Site-2 and East with Site-1, and not Site-3, which is a draft" \
        "$status $(json '(lambda walk: [walk(walk, r) for r in d["roots"]])(lambda walk, n: [n["level"], n["name"]] + [walk(walk, c) for c in n["children"]])')" \
        '200 [["region", "Americas", ["region", "Central", ["site", "Site-2"]], ["region", "East", ["site", "Site-1"]]]]'
    api GET '/geography/tree'
    expect "S24 with its locations, the tree counts at each place the items that examples/items.csv puts at or beneath it, a minor item where the item it is in is: Americas, Site-2, Room 102 and the rack within it, and those that are nowhere" \
        "$status $(places Americas 'Americas > Central > Site-2' "$room" "$rack" | python3 -c 'import json, sys; print(json.dumps([place[0] for place in json.load(sys.stdin)]))') $(json 'd["unplaced"]["items"]')" \
        "200 [$(examples_within Americas), $(examples_within 'Americas > Central > Site-2'), $(examples_within "$room"), $(examples_within "$rack")] $(examples_within)"
    expect "S24 and what is in the tree, what is nowhere and what is hidden add up to the totals" "$(adds_up)" true
    made=$(places "$rack")
    authorized GET "$prefix/api/v1/reports/summary" --get --data-urlencode "filter=location:within:$rack"
    expect "S24 the rack holds the components that the summary counts for the items within it, and the item list finds as many items there" \
        "$made" "[[$(json 'd["totals"]["items"]'), $(json 'd["totals"]["component_count"]')]]"
    api GET '/geography/tree?include_drafts=true&locations=false'
    expect "S24 asked for with the drafts, the tree has Site-3 too, with the one item that is there" \
        "$status $(places 'Americas > Central > Site-3')" "200 [[1, 1]]"

    api GET "/locations/$(location_at "$room")/effective"
    expect "S25 GET $prefix/api/v1/locations/{hid}/effective for Room 102 of the examples: the shipping contact of its site, the technical contact of its building and not the two of the region, the operational and the escalation contact of Americas, and nobody for the federal role" \
        "$status $(in_force shipping) $(in_force technical) $(in_force operational) $(in_force escalation) $(in_force federal)" \
        '200 ["site", "Americas > Central > Site-2", false, ["Sam Okafor"]] ["location", "Americas > Central > Site-2 > Building 1", false, ["Lee Marchetti"]] ["region", "Americas", false, ["Network Operations Desk"]] ["region", "Americas", false, ["Robin Achterberg"]] ["none", null, false, []]'
    expect "S25 its shipping address is the street address of its site, which says that deliveries go there and has no other entered, in place of the address of the region above; the instructions are those of the site, in place of the region's" \
        "$(json '[d["ship_address"]["source"], d["ship_address"]["same_as_address"], d["ship_address"]["value"]["address1"], d["ship_address"]["value"]["city"], d["ship_address"]["overrides_path"], d["ship_instructions"]["source"], d["ship_instructions"]["value"], d["ship_instructions"]["overrides_path"]]')" \
        '["site", true, "100 Example Way", "Springfield", "Americas > Central", "site", "Dock B, weekdays 08:00 to 15:00", "Americas"]'
    api GET "/locations/$(location_at 'Americas > Central > Site-3 > Suite 300')/effective"
    expect "S25 the room of the site that is a draft, which has no address at all, has the shipping address that its region has, taken whole, and the instructions of the region above that, by themselves" \
        "$status $(json '[d["ship_address"]["source"], d["ship_address"]["source_path"], d["ship_address"]["same_as_address"], d["ship_address"]["value"]["address1"], d["ship_instructions"]["source"], d["ship_instructions"]["source_path"]]')" \
        '200 ["region", "Americas > Central", false, "500 Depot Road", "region", "Americas"]'
    api GET "/locations/$(location_at "$store")/effective"
    expect "S26 the store room, which is in no building, has the two technical contacts of the region, in their order, and instructions of its own" \
        "$status $(in_force technical) $(json '[d["ship_instructions"]["source"], d["ship_instructions"]["value"]]')" \
        '200 ["region", "Americas", false, ["Dana Whitfield", "Robin Achterberg"]] ["own", "Leave with the store keeper; a signature is needed"]'
    api GET "/locations/$(location_at "$office")/effective"
    expect "S26 the small office says that nobody takes shipments there: its room has no shipping contact, and the search stopped at its site; its shipping address is the one its site has entered, which is not its street address" \
        "$status $(in_force shipping) $(json '[d["ship_address"]["source"], d["ship_address"]["same_as_address"], d["ship_address"]["value"]["address1"], d["ship_address"]["value"]["address2"]]')" \
        '200 ["site", "Americas > East > Site-1", true, []] ["site", false, "210 Sample Street", "Mail room"]'

    authorized GET "$prefix/api/v1/items" --get --data-urlencode 'filter=owner_exception:eq:true hostname:glob:site?-*' --data-urlencode 'include_archived=true'
    made=$(table '[[r["label"], r["exception_reason"]] for r in rows if r["is_external"] == "true"][0]' examples/owners.csv)
    expect "S28 one item of the examples is with an owner outside the team: it is marked as an exception, with the reason that examples/owners.csv gives for that owner, and has none of its own" \
        "$status $(json '[[i["hostname"], [i["owner"]["label"], i["owner_exception_reason"]], i["owner_exception"]] for i in d["items"]]')" \
        "200 $(table '[[r["hostname"], '"$made"', True] for r in rows if r["owner"] == '"$made"'[0]]' examples/items.csv)"

    # The operators of the examples: one label is open, a stack gives its switches its
    # operator, a controller domain the controllers of the cluster within it, a room
    # what is in it, and a site what is there.
    api GET '/operators?limit=1000'
    made="$status $(json 'sorted([o["label"], o["is_open"]] for o in d["items"] if o["is_open"])')"
    authorized GET "$prefix/api/v1/items" --get --data-urlencode 'filter=hostname:in:site2-sw-core-01,site2-wlc-01,site2-fw-oob-01,site1-sw-floor-01' --data-urlencode 'include_archived=true' --data-urlencode 'sort=hostname'
    expect "pkg the one operator of the examples that has nobody behind it is open; a switch of the core stack has the operator of its stack, a controller that of the domain its cluster is in, a firewall its own, and the switch of the small office that of its site, which is the open one" \
        "$made $status $(json '[[i["hostname"], i["effective"]["operator_hid"]["label"], i["effective"]["operator_hid"]["source"], i["effective"]["operator_hid"]["source_label"], i["effective"]["operator_hid"]["is_open"]] for i in d["items"]]')" \
        '200 [["OP6", true]] 200 [["site1-sw-floor-01", "OP6", "site", "Americas > East > Site-1", true], ["site2-fw-oob-01", "PR", "own", null, false], ["site2-sw-core-01", "LM", "device_group", "site2-sw-core", false], ["site2-wlc-01", "TL", "device_group", "site2-wireless", false]]'
    authorized GET "$prefix/api/v1/items" --get --data-urlencode 'filter=location:within:Americas > Central > Site-2 > Building 1 > Lab'
    made=$(json 'sorted({(i["effective"]["operator_hid"]["label"], i["effective"]["operator_hid"]["source"]) for i in d["items"]})')
    api GET '/reports/summary?by=operator&operators=true'
    expect "pkg what is in the lab has the operator of that room; the summary by operator has a row for each label that is in force for something and one for what nobody is assigned to, each item in one row, and with operators=true each row names its own operator" \
        "$made $status $(json '[sorted(r["label"] or "" for r in d["rows"]), sum(r["items"] for r in d["rows"]) == d["totals"]["items"], all([o["label"] for o in r["operators"]] == [r["label"]] for r in d["rows"])]')" \
        '[["RA", "location"]] 200 [["", "DW", "LM", "PR", "RA", "TL"], true, true]'

    # What is planned: a spare that is in the store room is meant for the site that is
    # a draft, and stays where it is until that site is in use.
    api GET '/items?filter=hostname:eq:site2-sw-access-08'
    made=$(json '[[i["location"]["name"], i["planned_location"]["path"], i["effective"]["planned_location_hid"]["source"]] for i in d["items"]]')
    api GET '/geography/tree?include_drafts=true&locations=false'
    expect "pkg a spare of the examples is in the store room and planned for the room of the draft site; the tree, asked for with the drafts, says that one item is planned for that site, and counts it where it is" \
        "$made $status $(json '(lambda walk: [n for r in d["roots"] for n in walk(walk, r)])(lambda walk, n: ([[n["name"], n["planned"], n["planned_groups"]]] if n["planned"] else []) + [m for c in n["children"] for m in walk(walk, c)])')" \
        '[["Store Room", "Americas > Central > Site-3 > Suite 300", "own"]] 200 [["Americas", 1, 0], ["Central", 1, 0], ["Site-3", 1, 0]]'
    api GET '/reports/management'
    made=$(json '[d["by"], sorted(r["label"] or "" for r in d["rows"]), sum(r["items"] for r in d["rows"]) == d["totals"]["items"]]')
    api GET '/reports/management?by=region'
    expect "pkg GET $prefix/api/v1/reports/management with no by is by site: a row for Site-2 and one for the items that are nowhere, which add up to the totals; by region, Americas and Central hold the same items, each of them once in the totals" \
        "$made $status $(json '[sorted([r["label"] or "", r["items"] == d["totals"]["items"] - [n["items"] for n in d["rows"] if n["key"] is None][0]] for r in d["rows"] if r["key"])]')" \
        '["site", ["", "Americas > Central > Site-2"], true] 200 [[["Americas", true], ["Americas > Central", true]]]'
}

# The records that 0.5.0 added, made through nginx under the prefix: scenarios S24 to
# S28 of docs/build-plan.md, each in small, and the location half of S18. files() runs
# this while the examples are loaded, so everything here has a name of its own, and the
# tree is asked for with a filter that finds these items alone. Every name is invented.
# What is made here stays, for hirdir admin reset to clear with the examples.
geography() {
    section "regions, sites, locations, contacts and the people of an owner through nginx under $prefix/"
    local land central east site building room other elsewhere staging made number
    local switch_model supply_model switches=() supply nowhere staged placed=""
    local pat sam lee robin desk assigned events team outside member second annex annex_room
    local view='serial_number:glob:PKG0000G*'
    local here='Package Test Land > Central > Package Test Site'

    # S24: paths, and roll-up counts at every level.
    api POST /regions '{"name": "Package Test Land", "code": "PTL", "ship_instructions": "Ring the package test desk a day ahead"}'
    made="$status $(json_field path)"
    land=$(json_field hid)
    api POST /regions "{\"name\": \"Central\", \"parent_region_hid\": \"$land\"}"
    made="$made $status $(json_field path)"
    central=$(json_field hid)
    api POST /regions "{\"name\": \"East\", \"parent_region_hid\": \"$land\"}"
    east=$(json_field hid)
    expect "S24 POST $prefix/api/v1/regions makes a region and two regions beneath it, whose names the examples have beneath a region of their own: each has its path" \
        "$made $status $(json_field path)" \
        "201 Package Test Land 201 Package Test Land > Central 201 Package Test Land > East"
    api POST /sites "{\"name\": \"Package Test Site\", \"region_hid\": \"$central\", \"code\": \"PTS\", \"address1\": \"1 Sample Square\", \"city\": \"Riverton\", \"ship_address1\": \"1 Sample Square\", \"ship_address2\": \"Rear gate\", \"ship_city\": \"Riverton\", \"ship_state\": \"NY\", \"ship_postal_code\": \"00000\", \"ship_country\": \"US\"}"
    made="$status $(json_field path)"
    site=$(json_field hid)
    api POST /locations "{\"name\": \"Building 9\", \"site_hid\": \"$site\", \"kind\": \"building\"}"
    made="$made | $status $(json_field path)"
    building=$(json_field hid)
    api POST /locations "{\"name\": \"Room 902\", \"site_hid\": \"$site\", \"parent_location_hid\": \"$building\", \"kind\": \"room\"}"
    room=$(json_field hid)
    expect "S24 POST $prefix/api/v1/sites and $prefix/api/v1/locations: a site in the region beneath, a building in it and a room in the building, each with its path" \
        "$made | $status $(json '[d["path"], d["depth"], d["kind"]]')" \
        "201 $here | 201 $here > Building 9 | 201 [\"$here > Building 9 > Room 902\", 1, \"room\"]"
    api POST /locations "{\"name\": \"Building 8\", \"site_hid\": \"$site\", \"kind\": \"building\"}"
    other=$(json_field hid)
    api POST /locations "{\"name\": \"Room 801\", \"site_hid\": \"$site\", \"parent_location_hid\": \"$other\", \"kind\": \"room\"}"
    elsewhere=$(json_field hid)
    api POST /locations "{\"name\": \"Staging\", \"site_hid\": \"$site\", \"record_status\": \"draft\"}"
    staging=$(json_field hid)
    api POST /locations "{\"name\": \"Room 902\", \"site_hid\": \"$site\", \"parent_location_hid\": \"$building\"}"
    made="$status $(json 'd["errors"][0]["field"]')"
    api POST /locations "{\"name\": \"Hall > Annex\", \"site_hid\": \"$site\"}"
    expect "pkg a second building with a room, and a location that is a draft; a second Room 902 in the same building is refused, and so is a name that holds the mark between the names of a path" \
        "$made $status $(json 'd["errors"][0]["field"]')" "409 name 422 name"

    api GET '/catalog-entries?filter=pid:eq:PT-48P'
    switch_model=$(json 'd["items"][0]["hid"]')
    api GET '/catalog-entries?filter=pid:eq:PT-PWR-715'
    supply_model=$(json 'd["items"][0]["hid"]')
    # Two switches in the room, one in the building, one that is nowhere, one in the
    # location that is a draft, and a power supply in the first switch of the room.
    made=""
    for number in "1:$room" "2:$room" "3:$building" "4:" "5:$staging"; do
        made=${number#*:}
        api POST /items "{\"catalog_entry_hid\": \"$switch_model\", \"serial_number\": \"PKG0000G00${number%%:*}\", \"hostname\": \"pkgtest-geo-0${number%%:*}\", \"lifecycle_state\": \"Prod\"${made:+, \"location_hid\": \"$made\"}}"
        placed="$placed$status "
        switches+=("$(json_field hid)")
    done
    api POST /items "{\"catalog_entry_hid\": \"$supply_model\", \"serial_number\": \"PKG0000G0P1\", \"parent_item_hid\": \"${switches[0]}\", \"position\": \"PS-A\"}"
    supply=$(json_field hid)
    expect "S24 five switches are made, two in the room, one in the building, one nowhere and one in the location that is a draft, and a power supply in the first: it is where its switch is, with the source parent_item" \
        "$placed$status $(json '[d["location_hid"], d["effective"]["location_hid"]["label"], d["effective"]["location_hid"]["source"], d["effective"]["location_hid"]["site"]]')" \
        "201 201 201 201 201 201 [null, \"$here > Building 9 > Room 902\", \"parent_item\", \"Package Test Site\"]"
    authorized GET "$prefix/api/v1/geography/tree" --get --data-urlencode "filter=$view"
    expect "S24 GET $prefix/api/v1/geography/tree for these items alone: three items and two components in the room, four and three in the building, the site and both regions above it, none in the other region" \
        "$status $(places "$here > Building 9 > Room 902" "$here > Building 9" "$here" 'Package Test Land > Central' 'Package Test Land' 'Package Test Land > East' "$here > Staging")" \
        '200 [[3, 2], [4, 3], [4, 3], [4, 3], [4, 3], [0, 0], null]'
    expect "S24 beside the tree: six items and five components in all, one of each nowhere, and one of each hidden, in the location that is a draft, which the tree leaves out; the three add up to the totals" \
        "$(beside) $(adds_up)" '[[6, 5], [1, 1], [1, 1]] true'
    authorized GET "$prefix/api/v1/geography/tree" --get --data-urlencode "filter=$view" --data-urlencode 'include_drafts=true' --data-urlencode "root=$here"
    expect "S24 asked for with the drafts and from the site alone, the tree is the site with the draft location in it and nothing hidden, beside the counts of the whole view" \
        "$status $(json '[[r["level"], r["name"], r["items"]] for r in d["roots"]]') $(places "$here > Staging") $(beside)" \
        '200 [["site", "Package Test Site", 5]] [[1, 1]] [[6, 5], [1, 1], [0, 0]]'
    api GET '/geography/tree'
    expect "S24 and over everything there is, the examples too, what is in the tree, what is nowhere and what is hidden add up to the totals" \
        "$status $(adds_up)" "200 true"
    made=""
    for number in "location:within:$here > Building 9 > Room 902" 'location:within:Package Test Land' "location:within:$site" 'location:empty:true' 'site:eq:Package Test Site' 'region:eq:East'; do
        authorized GET "$prefix/api/v1/items" --get --data-urlencode "filter=$view $number" --data-urlencode 'limit=1'
        made="$made$status $(json_field total) "
    done
    expect "S24 the item list finds by the same paths: three within the room, five within the region, the one in the draft location among them, five within the site by its HID, one that is nowhere, five by the name of the site and none by the name of the other region" \
        "$made" "200 3 200 5 200 5 200 1 200 5 200 0 "

    # S18, the half that came with 0.5.0: a switch is moved, and its minor item with it.
    api GET "/items/${switches[0]}"
    api PATCH "/items/${switches[0]}" "{\"row_version\": $(json_field row_version), \"location_hid\": \"$elsewhere\"}"
    made="$status $(json 'd["location"]["path"]')"
    api GET "/items/$supply"
    expect "S18 the first switch is moved to a room of the other building: its power supply is there too, from its parent, and nothing was written to it" \
        "$made | $status $(json '[d["effective"]["location_hid"]["label"], d["effective"]["location_hid"]["source"], d["location_hid"], d["row_version"]]')" \
        "200 $here > Building 8 > Room 801 | 200 [\"$here > Building 8 > Room 801\", \"parent_item\", null, 1]"
    authorized GET "$prefix/api/v1/geography/tree" --get --data-urlencode "filter=$view"
    expect "S18 and the tree follows: two items less in the room, two more in the other, and as many in the site" \
        "$status $(places "$here > Building 9 > Room 902" "$here > Building 8 > Room 801" "$here")" '200 [[1, 1], [2, 1], [4, 3]]'

    # S25: contacts are shown with the level they came from.
    made=""
    for number in 'Pat Whitfield:pat.whitfield' 'Sam Lindqvist:sam.lindqvist' 'Lee Raman:lee.raman' 'Robin Okafor:robin.okafor' 'Package Test Desk:pkgtest.desk'; do
        api POST /contacts "{\"name\": \"${number%%:*}\", \"email\": \"${number#*:}@example.net\", \"organization\": \"Package Test Team\"}"
        made="$made$status "
        case ${number%% *} in
            Pat) pat=$(json_field hid) ;;
            Sam) sam=$(json_field hid) ;;
            Lee) lee=$(json_field hid) ;;
            Robin) robin=$(json_field hid) ;;
            *) desk=$(json_field hid) ;;
        esac
    done
    api POST /contacts '{"name": "Somebody Else", "email": "PAT.WHITFIELD@example.net"}'
    expect "S25 POST $prefix/api/v1/contacts makes five contacts; a sixth with the email address of the first, written in capitals, is refused" \
        "$made$status $(json 'd["errors"][0]["field"]')" "201 201 201 201 201 409 email"
    api POST /contact-assignments "{\"contact_hid\": \"$pat\", \"role\": \"technical\", \"region_hid\": \"$land\"}"
    made=$status
    assigned=$(json_field hid)
    api POST /contact-assignments "{\"contact_hid\": \"$sam\", \"role\": \"shipping\", \"site_hid\": \"$site\"}"
    made="$made $status"
    api GET "/locations/$room/effective"
    expect "S25 a technical contact on the region and a shipping contact on the site: GET $prefix/api/v1/locations/{hid}/effective shows the room both, each with the level it came from, and an entry with nobody for a role that no level has" \
        "$made $status $(in_force technical) $(in_force shipping) $(in_force escalation)" \
        "201 201 200 [\"region\", \"Package Test Land\", false, [\"Pat Whitfield\"]] [\"site\", \"$here\", false, [\"Sam Lindqvist\"]] [\"none\", null, false, []]"
    api GET "/sites/$site/effective"
    made="$status $(json_field level) $(in_force shipping)"
    api GET "/regions/$central/effective"
    expect "pkg GET $prefix/api/v1/sites/{hid}/effective and $prefix/api/v1/regions/{hid}/effective answer the same for a site and a region: the site has the shipping contact as its own, and the region beneath has the technical contact of the one above and no shipping contact" \
        "$made | $status $(json_field level) $(in_force technical) $(in_force shipping)" \
        "200 site [\"own\", \"$here\", false, [\"Sam Lindqvist\"]] | 200 region [\"region\", \"Package Test Land\", false, [\"Pat Whitfield\"]] [\"none\", null, false, []]"

    # S26: an override on a building holds when the contact of the region changes.
    api POST /contact-assignments "{\"contact_hid\": \"$lee\", \"role\": \"technical\", \"location_hid\": \"$building\"}"
    made=$status
    api PATCH "/contact-assignments/$assigned" "{\"row_version\": 1, \"contact_hid\": \"$robin\"}"
    made="$made $status"
    api GET "/locations/$room/effective"
    made="$made $status $(in_force technical)"
    api GET "/locations/$elsewhere/effective"
    expect "S26 the building is given a technical contact of its own, and the one of the region is changed: the room keeps the building's, and the room of the other building shows the new one of the region" \
        "$made | $status $(in_force technical)" \
        "201 200 200 [\"location\", \"$here > Building 9\", false, [\"Lee Raman\"]] | 200 [\"region\", \"Package Test Land\", false, [\"Robin Okafor\"]]"
    # None here, and do not look further up: an assignment with no contact.
    api POST /contact-assignments "{\"role\": \"shipping\", \"location_hid\": \"$other\", \"stop_inheritance\": true}"
    made=$status
    api POST /contact-assignments "{\"contact_hid\": \"$desk\", \"role\": \"shipping\", \"location_hid\": \"$other\"}"
    made="$made $status"
    api GET "/locations/$elsewhere/effective"
    made="$made $status $(in_force shipping)"
    api GET "/locations/$room/effective"
    expect "S26 the other building says that nobody takes shipments there, and takes no shipping contact beside that: its room has none, the search stopped at the building, and the room of the first building has the site's still" \
        "$made | $status $(in_force shipping)" \
        "201 409 200 [\"location\", \"$here > Building 8\", true, []] | 200 [\"site\", \"$here\", false, [\"Sam Lindqvist\"]]"
    # The shipping address is taken whole, and the instructions by themselves.
    expect "S26 the room has the shipping address of its site and the instructions of the region above" \
        "$(json '[d["ship_address"]["source"], d["ship_address"]["value"]["address2"], d["ship_address"]["value"]["state"], d["ship_instructions"]["source"], d["ship_instructions"]["value"]]')" \
        '["site", "Rear gate", "NY", "region", "Ring the package test desk a day ahead"]'
    api GET "/locations/$building"
    api PATCH "/locations/$building" "{\"row_version\": $(json_field row_version), \"ship_address1\": \"9 Sample Square\", \"ship_city\": \"Riverton\"}"
    made=$status
    api GET "/locations/$room"
    api PATCH "/locations/$room" "{\"row_version\": $(json_field row_version), \"ship_instructions\": \"Hand to the room keeper\"}"
    made="$made $status"
    api GET "/locations/$room/effective"
    expect "S26 the building is given two lines of a shipping address, and the room instructions of its own: the room has the address of the building whole, with nothing of the site's in the lines the building left out, and its own instructions" \
        "$made $status $(json '[d["ship_address"]["source"], d["ship_address"]["source_path"], d["ship_address"]["value"], d["ship_instructions"]["source"], d["ship_instructions"]["value"]]')" \
        "200 200 200 [\"location\", \"$here > Building 9\", {\"address1\": \"9 Sample Square\", \"address2\": null, \"city\": \"Riverton\", \"country\": null, \"postal_code\": null, \"state\": null}, \"own\", \"Hand to the room keeper\"]"

    # S27: a site is moved to another region.
    api POST /contact-assignments "{\"contact_hid\": \"$desk\", \"role\": \"operational\", \"region_hid\": \"$central\"}"
    made=$status
    api POST /contact-assignments "{\"contact_hid\": \"$pat\", \"role\": \"operational\", \"region_hid\": \"$east\"}"
    made="$made $status"
    api GET "/locations/$room/effective"
    expect "S27 an operational contact on each of the two regions beneath: the room shows the one of the region its site is in" \
        "$made $status $(in_force operational)" \
        '201 201 200 ["region", "Package Test Land > Central", false, ["Package Test Desk"]]'
    authorized GET "$prefix/api/v1/items" --get --data-urlencode "filter=$view" --data-urlencode 'include_drafts=true' --data-urlencode 'sort=serial_number'
    keep placed
    api GET '/audit-events?limit=1'
    events=$(json_field total)
    api GET "/sites/$site"
    api PATCH "/sites/$site" "{\"row_version\": $(json_field row_version), \"region_hid\": \"$east\"}"
    made="$status $(json_field path)"
    api GET "/locations/$room"
    expect "S27 PATCH $prefix/api/v1/sites/{hid} gives the site the other region: its path and the path of the room follow, and the room was not written to" \
        "$made | $status $(json '[d["path"], d["row_version"]]')" \
        "200 Package Test Land > East > Package Test Site | 200 [\"Package Test Land > East > Package Test Site > Building 9 > Room 902\", 2]"
    api GET "/locations/$room/effective"
    made="$status $(in_force operational)"
    authorized GET "$prefix/api/v1/geography/tree" --get --data-urlencode "filter=$view"
    expect "S27 the room shows the operational contact of the region its site is in now, and the tree has the items beneath that region and none beneath the other" \
        "$made | $status $(places 'Package Test Land > East' 'Package Test Land > Central' 'Package Test Land' 'Package Test Land > East > Package Test Site')" \
        '200 ["region", "Package Test Land > East", false, ["Pat Whitfield"]] | 200 [[4, 3], [0, 0], [4, 3], [4, 3]]'
    authorized GET "$prefix/api/v1/items" --get --data-urlencode "filter=$view" --data-urlencode 'include_drafts=true' --data-urlencode 'sort=serial_number'
    made=$(python3 -c '
import json, sys

was, now = (json.load(open(path, encoding="utf-8"))["items"] for path in sys.argv[1:3])
same = [(i["hid"], i["row_version"], i["updated_at"]) for i in was] == [(i["hid"], i["row_version"], i["updated_at"]) for i in now]
regions = sorted({i["effective"]["location_hid"]["label"].split(" > ")[1] for i in now if i["effective"]["location_hid"]["label"]})
print(json.dumps([len(now), same, regions]))' "$work/kept-placed.json" "$work/body")
    authorized GET "$prefix/api/v1/items" --get --data-urlencode "filter=$view location:within:Package Test Land > East" --data-urlencode 'limit=1'
    expect "S27 no item was written to: each of the six is the record it was, at the row_version it had, and those that are somewhere show the new path; the item list finds five within the region the site is in now" \
        "$made $status $(json_field total)" '[6, true, ["East"]] 200 5'
    api GET '/audit-events?limit=1'
    expect "S27 and the move is one audit event, an update of the site that changed its region and nothing else" \
        "$status $(($(json_field total) - events)) $(json '[[e["record_type"], e["record_hid"], e["action"], e["changes"]] for e in d["items"]]')" \
        "200 1 [[\"site\", \"$site\", \"update\", [{\"field\": \"region_hid\", \"new\": \"$east\", \"old\": \"$central\"}]]]"

    # The reports, by site and by region.
    authorized GET "$prefix/api/v1/reports/summary" --get --data-urlencode "filter=$view" --data-urlencode 'by=site'
    made="$status $(json 'sorted([r["label"] or "", r["items"], r["component_count"]] for r in d["rows"])') $(json '[d["totals"]["items"], d["totals"]["component_count"]]')"
    authorized GET "$prefix/api/v1/reports/management" --get --data-urlencode "filter=$view" --data-urlencode 'by=region'
    expect "S27 the summary by site has a row for the site, labelled with its path, and one for the item that is nowhere; the management report by region has the items in the row of each region above them, and counts each once in its totals" \
        "$made | $status $(json 'sorted([r["label"] or "", r["items"]] for r in d["rows"])') $(json 'd["totals"]["items"]')" \
        '200 [["", 1, 1], ["Package Test Land > East > Package Test Site", 5, 4]] [6, 5] | 200 [["", 1], ["Package Test Land", 5], ["Package Test Land > East", 5]] 6'

    # A place is not retired while something is in it.
    api POST "/locations/$room/retire" '{"row_version": 2}'
    made="$status $(grep -c 'still holds 1 item' "$work/body")"
    api POST "/sites/$site/retire" '{"row_version": 2}'
    made="$made $status"
    api POST "/regions/$east/retire" '{"row_version": 1}'
    made="$made $status"
    api POST "/regions/$central/retire" '{"row_version": 1}'
    expect "pkg a room with an item in it is not retired, and the answer says what it still holds; nor is the site with its locations, nor the region with the site; the region that holds nothing now is" \
        "$made $status $(json_field record_status)" "409 1 409 409 200 retired"

    # A place is not brought back while what it is in is retired.
    api POST /locations "{\"name\": \"Annex\", \"site_hid\": \"$site\", \"kind\": \"building\"}"
    made=$status
    annex=$(json_field hid)
    api POST /locations "{\"name\": \"Annex Room\", \"site_hid\": \"$site\", \"parent_location_hid\": \"$annex\", \"kind\": \"room\"}"
    made="$made $status"
    annex_room=$(json_field hid)
    api POST "/locations/$annex_room/retire" '{"row_version": 1}'
    made="$made $status"
    api POST "/locations/$annex/retire" '{"row_version": 1}'
    made="$made $status"
    api PATCH "/locations/$annex_room" '{"row_version": 2, "record_status": "active"}'
    made="$made $status $(json 'd["errors"][0]["field"]')"
    api PATCH "/locations/$annex" '{"row_version": 2, "record_status": "active"}'
    made="$made $status"
    api PATCH "/locations/$annex_room" '{"row_version": 2, "record_status": "active"}'
    expect "pkg a building and the room in it are retired, the room first: the room is not brought back while its building is retired, and is once the building is" \
        "$made $status $(json_field record_status)" "201 201 200 200 422 record_status 200 200 active"

    # S28: an owner outside the team says why it is an exception, once, and what is
    # given to it is marked by that alone.
    authorized GET "$prefix/api/v1/owners" --get --data-urlencode 'filter=label:eq:Package Test Team'
    team=$(json 'd["items"][0]["hid"]')
    api POST /owners '{"label": "Package Test Facilities", "organization": "Building Services", "is_external": true}'
    made="$status $(json '[e["field"] for e in d["errors"]]')"
    api POST /owners '{"label": "Package Test Facilities", "organization": "Building Services", "is_external": true, "exception_reason": "Looks after the door controllers"}'
    expect "S28 POST $prefix/api/v1/owners refuses an owner outside the team that gives no reason, and takes it with one" \
        "$made $status $(json_field exception_reason)" '422 ["exception_reason"] 201 Looks after the door controllers'
    outside=$(json_field hid)
    nowhere=${switches[3]}
    api PATCH "/items/$nowhere" "{\"row_version\": 1, \"owner_hid\": \"$team\"}"
    made="$status $(json_field owner_exception)"
    api PATCH "/items/$nowhere" "{\"row_version\": 2, \"owner_hid\": \"$outside\", \"owner_exception_reason\": \"A reason of the item's own\"}"
    made="$made $status $(json '[e["field"] for e in d["errors"]]')"
    api PATCH "/items/$nowhere" "{\"row_version\": 2, \"owner_hid\": \"$outside\"}"
    expect "S28 an item with an owner of the team is no exception; given the owner outside the team, it has no reason of its own to give, and with nothing more said it is marked as an exception, with the reason of that owner" \
        "$made $status $(json '[d["owner"]["label"], d["owner_exception"], d["owner_exception_reason"]]')" \
        '200 false 422 ["owner_exception_reason"] 200 ["Package Test Facilities", true, "Looks after the door controllers"]'
    authorized GET "$prefix/api/v1/items" --get --data-urlencode "filter=$view owner_exception:eq:true"
    made="$status $(json '[i["serial_number"] for i in d["items"]]')"
    api GET "/items/${switches[0]}"
    api PATCH "/items/${switches[0]}" "{\"row_version\": $(json_field row_version), \"owner_hid\": \"$outside\"}"
    made="$made $status"
    api GET "/items/$supply"
    expect "S28 GET $prefix/api/v1/items?filter=owner_exception:eq:true finds it; a minor item of an item that is with such an owner is marked too, with the same reason, and has its owner from the item it is in" \
        "$made $(json '[d["owner_exception"], d["owner_exception_reason"], d["effective"]["owner_hid"]["source"]]')" \
        '200 ["PKG0000G004"] 200 [true, "Looks after the door controllers", "parent_item"]'
    api POST /device-groups "{\"type\": \"custom\", \"name\": \"pkgtest-doors\", \"owner_hid\": \"$outside\"}"
    made="$status $(json '[d["owner_exception"], d["owner_exception_reason"]]')"
    api GET "/owners/$outside"
    api PATCH "/owners/$outside" "{\"row_version\": $(json_field row_version), \"exception_reason\": \"Runs the door controllers\"}"
    made="$made $status"
    api GET "/items/${switches[0]}"
    made="$made $(json '[d["owner_exception_reason"], d["row_version"]]')"
    api PATCH "/items/$nowhere" "{\"row_version\": 3, \"owner_hid\": \"$team\"}"
    expect "S28 a device group that is given that owner is marked likewise; the reason is changed on the owner, and the item shows the new one with nothing written to it; an item given back to an owner of the team is no exception and shows no reason" \
        "$made $status $(json '[d["owner_exception"], d["owner_exception_reason"]]')" \
        '201 [true, "Looks after the door controllers"] 200 ["Runs the door controllers", 3] 200 [false, null]'

    # The people of an owner: one primary where there are any.
    api POST "/owners/$team/members" "{\"contact_hid\": \"$pat\", \"role\": \"alternate\"}"
    made="$status $(json 'd["errors"][0]["field"]')"
    api POST "/owners/$team/members" "{\"contact_hid\": \"$pat\"}"
    made="$made $status $(json_field role)"
    member=$(json_field hid)
    api POST "/owners/$team/members" "{\"contact_hid\": \"$lee\"}"
    made="$made $status $(json_field role)"
    second=$(json_field hid)
    api POST "/owners/$team/members" "{\"contact_hid\": \"$lee\"}"
    expect "pkg POST $prefix/api/v1/owners/{hid}/members: the first person of an owner is its primary, and is refused as an alternate; the second is an alternate; the same person a second time is refused" \
        "$made $status" "422 role 201 primary 201 alternate 409"
    api PATCH "/owners/$team/members/$second" '{"row_version": 1, "role": "primary"}'
    made=$status
    api GET "/owners/$team"
    made="$made $(json 'sorted([m["contact"]["name"], m["role"]] for m in d["members"])')"
    api DELETE "/owners/$team/members/$second"
    made="$made $status"
    api DELETE "/owners/$team/members/$member"
    made="$made $status"
    api DELETE "/owners/$team/members/$second"
    made="$made $status"
    api GET "/owners/$team"
    expect "pkg the second is made primary, and the first is an alternate by the same change; the primary is not removed while another remains, the alternate is, and then the primary, which leaves the owner with nobody" \
        "$made $(json 'd["members"]')" \
        '200 [["Lee Raman", "primary"], ["Pat Whitfield", "alternate"]] 409 204 204 []'
    api POST "/owners/$team/members" "{\"contact_hid\": \"$sam\"}"
    expect "pkg and it is given a person again, who is its primary" "$status $(json_field role)" "201 primary"

    # In a file of the people of an owner, the row of the primary is worked first,
    # wherever it stands.
    printf '%s\n' 'owner,contact,role' 'Package Test Facilities,robin.okafor@example.net,alternate' 'Package Test Facilities,pkgtest.desk@example.net,primary' >"$work/people.csv"
    send "/imports/preview?entity=owner_members&file_name=people.csv" "$work/people.csv"
    made="$status $(job_counts)"
    apply_job "/imports/$(json 'd["job"]["hid"]')/apply"
    made="$made $status $(job_counts)"
    api GET "/owners/$outside/members"
    expect "pkg a file of the people of an owner that has none, with the row of the alternate before that of the primary, is previewed and applied whole, and GET $prefix/api/v1/owners/{hid}/members lists the two as a page" \
        "$made $status $(json '[d["total"], sorted([m["contact"]["name"], m["role"]] for m in d["items"])]')" \
        '201 ["previewed", 2, 2, 0, 0, 0] 202 ["applied", 2, 2, 0, 0, 0] 200 [2, [["Package Test Desk", "primary"], ["Robin Okafor", "alternate"]]]'

    # Every record of the new kinds, the examples' and these, exported and imported back.
    for number in contacts operators regions sites locations contact_assignments owners owner_members; do
        api POST /exports "{\"entity\": \"$number\", \"format\": \"csv\", \"own_values\": true, \"include_archived\": true, \"include_drafts\": true}"
        cp "$work/body" "$work/back-$number.csv"
        staged=$(table 'len(rows)' "$work/back-$number.csv")
        send "/imports/preview?entity=$number&file_name=$number.csv" "$work/back-$number.csv"
        made="$status $(job_counts)"
        api POST /exports "{\"entity\": \"$number\", \"format\": \"json\", \"own_values\": true, \"include_archived\": true, \"include_drafts\": true}"
        cp "$work/body" "$work/back-$number.json"
        send "/imports/preview?file_name=$number.json" "$work/back-$number.json" application/json
        expect "pkg an export of every record of $number ($staged rows) is imported back as it is, as CSV and as JSON: every row finds its record by HID, unchanged" \
            "$made $status $(job_counts)" \
            "201 [\"previewed\", $staged, 0, 0, $staged, 0] 201 [\"previewed\", $staged, 0, 0, $staged, 0]"
    done
    api POST /exports '{"entity": "items", "format": "csv", "own_values": true, "include_drafts": true, "filter": "serial_number:glob:PKG0000G*", "sort": ["serial_number"]}'
    cp "$work/body" "$work/back-placed.csv"
    send "/imports/preview?entity=items&file_name=placed.csv" "$work/back-placed.csv"
    expect "pkg and an export of these items with their own values has the location of each as its path and its owner, no column for a reason of the item's own, and nothing for the minor item, which has both from its switch; it is imported back unchanged" \
        "$(table '["owner_exception_reason" in head, [[r["serial_number"], r["location"].rsplit(" > ", 1)[-1], r["owner"]] for r in rows]]' "$work/back-placed.csv") $status $(job_counts)" \
        '[false, [["PKG0000G001", "Room 801", "Package Test Facilities"], ["PKG0000G002", "Room 902", ""], ["PKG0000G003", "Building 9", ""], ["PKG0000G004", "", "Package Test Team"], ["PKG0000G005", "Staging", ""], ["PKG0000G0P1", "", ""]]] 201 ["previewed", 6, 0, 0, 6, 0]'
}

# What 0.5.0 added to the command line, on the examples: the tree of places, a location
# with what it has in force, the regions, a site that is moved and moved back, the
# management report by site, and the operators: listed, one handed over and left open
# again, one released, and the summary with the operators of each row. client_commands
# runs this, while the examples are loaded.
client_places() {
    local code=0 wanted site made room='Americas > Central > Site-2 > Building 1 > Floor 1 > Room 102'

    api GET '/geography/tree'
    wanted="$(json '[d["totals"]["items"], d["totals"]["component_count"]]' | tr -d '[],') | $(json '[d["unplaced"]["items"], d["unplaced"]["component_count"]]' | tr -d '[],') | $(places "$room > Rack A1" | tr -d '[],')"
    cli_run "$work/cli.tree" geography tree
    expect "S24 hirdir geography tree prints the regions, the sites and the locations of the examples with the items and the components that GET /geography/tree counts: all of them, those that are nowhere, and those of the rack" \
        "$code $(head -n 1 "$work/cli.tree" | xargs) | $(sed -n 's/^(all) *//p' "$work/cli.tree" | xargs) | $(sed -n 's/^(nowhere) *//p' "$work/cli.tree" | xargs) | $(sed -n 's/^ *Rack A1 *location *//p' "$work/cli.tree" | xargs)" \
        "0 PLACE LEVEL ITEMS COMPONENT_COUNT | $wanted"
    expect "S24 each place is beneath what it is in, and indented by how deep that is: Americas at the edge, and the rack six steps in" \
        "$(grep -c '^Americas ' "$work/cli.tree") $(grep -c '^            Rack A1 ' "$work/cli.tree")" "1 1"
    cli_run "$work/cli.tree" geography tree --root 'Americas > Central' --no-locations --include-drafts
    expect "S24 hirdir geography tree --root --no-locations --include-drafts starts from one region and stops at its sites, the draft among them" \
        "$code $(sed -n '2,4p' "$work/cli.tree" | awk '{print $1 ":" $2}' | xargs)" "0 Central:region Site-2:site Site-3:site"
    cli_run "$work/cli.place" locations show "$room"
    expect "S25 hirdir locations show takes a location by its path and prints what it has in force, each with the level it came from: the technical contact of the building, the shipping contact of the site, the shipping address, which is the street address of the site, and the instructions of the site" \
        "$code | $(sed -n 's/^technical: *//p' "$work/cli.place") | $(sed -n 's/^shipping: *//p' "$work/cli.place") | $(sed -n 's/^ship_address: *//p' "$work/cli.place") | $(sed -n 's/^ship_instructions: *//p' "$work/cli.place")" \
        "0 | Lee Marchetti lee.marchetti@example.net +1 555 0102 (from Americas > Central > Site-2 > Building 1) | Sam Okafor sam.okafor@example.net +1 555 0110 (from Americas > Central > Site-2) | 100 Example Way, Springfield, IL, 00000, US, its street address (from Americas > Central > Site-2) | Dock B, weekdays 08:00 to 15:00 (from Americas > Central > Site-2)"
    cli_run "$work/cli.regions" regions list --sort name
    expect "pkg hirdir regions list is a table of the three regions of the examples, each with its path" \
        "$code $(head -n 1 "$work/cli.regions" | xargs) | $(tail -n +2 "$work/cli.regions" | sed -E 's/^[0-9a-f-]{36} +//; s/  +.*//' | paste -sd ';')" \
        "0 HID PATH CODE RECORD_STATUS | Americas;Americas > Central;Americas > East"
    cli_run "$work/cli-regions.csv" regions list --format csv
    api POST /exports '{"entity": "regions", "format": "csv"}'
    expect "pkg and as csv it is the file that POST /exports gives for regions" \
        "$code $(sha256sum <"$work/cli-regions.csv")" "0 $(sha256sum <"$work/body")"

    api GET '/sites?filter=code:eq:S1'
    site=$(json 'd["items"][0]["hid"]')
    cli_run "$work/cli.move" sites move 'Americas > East > Site-1' 'Americas > Central'
    api GET "/sites/$site"
    expect "S27 hirdir sites move gives a site another region, and says what its path is now" \
        "$code $(cat "$work/cli.move" "$work/cli.err" | grep -c 'Americas > East > Site-1 is now Americas > Central > Site-1') $(json_field path)" \
        "0 1 Americas > Central > Site-1"
    api GET "/audit-events?record_hid=$site&limit=1"
    wanted=$(json '[[e["via"], e["action"], [c["field"] for c in e["changes"]]] for e in d["items"]]')
    cli_run "$work/cli.move" sites move "$site" 'Americas > East'
    api GET "/sites/$site"
    expect "S27 the move is one change of the site, made through the command line; moved back, by its HID, the site is where the examples have it" \
        "$wanted $code $(json_field path)" '[["cli", "update", ["region_hid"]]] 0 Americas > East > Site-1'
    cli_run "$work/cli.move" sites move 'Americas > East > Site-9' 'Americas > Central'
    expect "pkg a site that there is not exits with 4, and nothing is moved" "$code" 4

    api GET /reports/management
    wanted=$(json 'd')
    cli_run "$work/cli-management.json" report management --format json
    cp "$work/cli-management.json" "$work/body"
    expect "pkg hirdir report management with no --by, as json, is what GET /reports/management gives, which is by site" \
        "$code $(json_field by) $(json 'd')" "0 site $wanted"
    cli_run "$work/cli.management" report management
    expect "pkg and on a terminal it is a table with a line for the one site that has items, by its path, one for the items that are nowhere, and one for all" \
        "$code $(head -n 1 "$work/cli.management" | xargs) $(grep -c '^Americas > Central > Site-2 ' "$work/cli.management") $(grep -c '^(none) ' "$work/cli.management") $(grep -c '^(all) ' "$work/cli.management")" \
        "0 SITE ITEMS COMPONENT_COUNT EST_VALUE ANNUAL_SUPPORT_COST 1 1 1"

    # The operators: the labels of the examples, one handed over and left open again,
    # one of the test's own released, and the summary with the operators of each row.
    cli_run "$work/cli.operators" operators list
    expect "pkg hirdir operators list is a table of the six labels of the examples, each with the person behind it, and says which is open" \
        "$code $(head -n 1 "$work/cli.operators" | xargs) | $(tail -n +2 "$work/cli.operators" | awk '{print $2 ":" $(NF - 1)}' | xargs)" \
        "0 HID LABEL DESCRIPTION CONTACT IS_OPEN RECORD_STATUS | DW:false LM:false OP6:true PR:false RA:false TL:false"
    cli_run "$work/cli-operators.csv" operators list --format csv
    api POST /exports '{"entity": "operators", "format": "csv"}'
    expect "pkg and as csv it is the file that POST /exports gives for operators" \
        "$code $(sha256sum <"$work/cli-operators.csv")" "0 $(sha256sum <"$work/body")"
    cli_run "$work/cli.assign" operators assign OP6 facilities@example.net
    api GET '/operators?filter=label:eq:OP6'
    wanted="$code $(json '[[o["contact"]["name"], o["is_open"]] for o in d["items"]]')"
    api GET '/items?filter=hostname:eq:site1-sw-floor-01&include_archived=true'
    wanted="$wanted $(json '[[i["effective"]["operator_hid"]["contact"], i["effective"]["operator_hid"]["is_open"], i["row_version"]] for i in d["items"]]')"
    cli_run "$work/cli.assign" operators assign OP6 --open
    api GET '/operators?filter=label:eq:OP6'
    expect "pkg hirdir operators assign puts a person behind the open label, by an email address, and what the label is on shows that person with nothing written to it; with --open the label is left open again, as the examples have it" \
        "$wanted $code $(json '[[o["contact"], o["is_open"]] for o in d["items"]]')" \
        '0 [["Facilities Help Desk", false]] [["Facilities Help Desk", false, 1]] 0 [[null, true]]'
    api POST /operators '{"label": "CLI1"}'
    made=$(json_field hid)
    cli_run "$work/cli.release" operators release CLI1
    api GET "/operators/$made"
    wanted="$code $(json_field record_status)"
    cli_run "$work/cli.release" operators release NO-SUCH-LABEL
    expect "pkg hirdir operators release retires a label, which then stands for nothing; a label that there is not exits with 4" \
        "$wanted $code" "0 retired 4"
    api GET '/reports/summary?by=site&operators=true'
    wanted=$(json 'd')
    cli_run "$work/cli-summary.json" report summary --by site --operators --format json
    cp "$work/cli-summary.json" "$work/body"
    expect "pkg hirdir report summary --by site --operators, as json, is what GET /reports/summary gives with operators=true: each site with the operators in force among its items" \
        "$code $(json 'd')" "0 $wanted"
    cli_run "$work/cli.summary" report summary --by site --operators
    expect "pkg and on a terminal the table has a column of them at its end, each label with the support weight it carries, the most first" \
        "$code $(head -n 1 "$work/cli.summary" | awk '{print $NF}') $(grep -c '^Americas > Central > Site-2 .* TL [0-9.]*, PR ' "$work/cli.summary")" \
        "0 OPERATORS 1"
}

# What 0.6.0 added to the command line, on the examples: the six lists, a contract
# shown with what it has from its agreement, items put under a contract, a contract
# rolled into an agreement and taken out again, a contract renewed, a purchase request
# shown and a delivery received on one of its lines, the portfolio of a vendor, and
# the coverage, end-of-life, replacements and capacity reports. client_commands runs
# this, while the examples are loaded. What a report says of the examples moves with
# the calendar, so each is held against what the API answers at the same moment, and
# examples_cover() has held that against the files.
client_cover() {
    local code=0 wanted made name contract phones received said early late

    made=""
    for name in agreements:agreements contracts:contracts purchases:purchase_requests systems:external_systems registrations:registrations capacity:capacity_lines; do
        cli_run "$work/cli-list.csv" "${name%:*}" list --format csv
        api POST /exports "{\"entity\": \"${name#*:}\", \"format\": \"csv\"}"
        [ "$code $(sha256sum <"$work/cli-list.csv")" = "0 $(sha256sum <"$work/body")" ] || made="$made${name%:*} "
    done
    expect "pkg hirdir agreements list, contracts list, purchases list, systems list, registrations list and capacity list, each as csv, write the very file that POST /exports gives for the agreements, the contracts, the purchase requests, the external systems, the registrations and the capacity lines" \
        "$made" ""
    cli_run "$work/cli.table" contracts list --filter 'agreement.name:eq:Cisco Enterprise Agreement' --sort number
    expect "pkg hirdir contracts list --filter is a table of the two contracts that the examples group into the Cisco agreement, each with the period it has from it" \
        "$code $(head -n 1 "$work/cli.table" | xargs) | $(tail -n +2 "$work/cli.table" | awk '{print $2 ":" $(NF - 4) ":" $(NF - 3)}' | xargs)" \
        "0 HID NUMBER VENDOR AGREEMENT STARTS_ON ENDS_ON STATUS COVERED_ITEMS RECORD_STATUS | CON-2025-0001:2025-01-01:2027-12-31 CON-2025-0002:2025-01-01:2027-12-31"
    cli_run "$work/cli-registrations.csv" registrations list --filter 'system.name:eq:NetWatch' --columns system,item,group,status --format csv
    expect "pkg hirdir registrations list --filter --columns, as csv, has the three registrations of the examples with the monitoring system, of a router, of the core stack, and the one that was removed" \
        "$code $(table '[head, sorted([r["item"], r["group"], r["status"]] for r in rows)]' "$work/cli-registrations.csv")" \
        '0 [["hid", "system", "item", "group", "status"], [["", "site2-sw-core", "registered"], ["AT-000133", "", "removed"], ["AT-000141", "", "registered"]]]'

    # A contract, with what it has from its agreement.
    api GET '/contracts?filter=number:eq:CON-2025-0001'
    wanted=$(json '[d["items"][0]["covered_items"], d["items"][0]["items_in_scope"]]')
    cli_run "$work/cli.contract" contracts show CON-2025-0001
    expect "pkg hirdir contracts show takes a contract by its number and prints it: what it has from its agreement is marked so, and what is its own is not; then the items it covers today and those in scope, as the API counts them, and a line for each item it has covered, the one whose cover was ended among them" \
        "$code | $(sed -n 's/^agreement: *//p' "$work/cli.contract") | $(sed -n 's/^ends_on: *//p' "$work/cli.contract") | $(sed -n 's/^support_level: *//p' "$work/cli.contract") | $(sed -n 's/^purchase_reference: *//p' "$work/cli.contract") | [$(sed -n 's/^items covered: *//p' "$work/cli.contract"), $(sed -n 's/^items in scope: *//p' "$work/cli.contract")] | $(grep -c ' C9300-48P ' "$work/cli.contract") $(grep -c -E '^site2-sw-floor-03 .* 2026-06-30 +no$' "$work/cli.contract")" \
        "0 | Cisco Enterprise Agreement | 2027-12-31 (agreement) | 24x7, four-hour response (agreement) | RITM0009121 | $wanted | 6 1"

    # Items are put under the contract that stands by itself: a preview, then --apply.
    contract=$(hid_of contracts 'number:eq:CON-2026-0107')
    phones=$(table 'sum(r["pid"] == "CP-8851-K9" for r in rows)' examples/items.csv)
    cli_run "$work/cli.out" contracts cover CON-2026-0107 --filter 'catalog.pid:eq:CP-8851-K9'
    made="$code $(matches "^$phones items would be covered by CON-2026-0107, 2026-09-01 to 2027-08-31\$" "$work/cli.out") $(matches 'nothing was changed' "$work/cli.err")"
    api GET "/contracts/$contract/coverage?limit=1"
    made="$made $(json_field total)"
    cli_run "$work/cli.out" contracts cover CON-2026-0107 --filter 'catalog.pid:eq:CP-8851-K9' --apply
    made="$made | $code $(matches "^$phones items are covered by CON-2026-0107" "$work/cli.out")"
    api GET "/contracts/$contract/coverage?limit=1"
    made="$made $(json_field total)"
    cli_run "$work/cli.out" contracts cover CON-2026-0107 --filter 'catalog.pid:eq:CP-8851-K9' --apply
    api GET "/contracts/$contract/coverage?limit=1"
    expect "pkg hirdir contracts cover --filter says how many items it would put under the contract, the $phones telephones of the examples, and changes nothing until --apply is given; with --apply they are covered for the contract's own period; a second time it exits with 5, because the contract covers them already, and nothing is added" \
        "$made | $code $(json_field total)" \
        "0 1 1 2 | 0 1 $((2 + phones)) | 5 $((2 + phones))"

    # It is rolled into the agreement, and taken out again: one change each.
    cli_run "$work/cli.out" contracts set CON-2026-0107 agreement='Cisco Enterprise Agreement'
    api GET "/contracts/$contract"
    made="$code $(matches '^CON-2026-0107 in Cisco Enterprise Agreement: ' "$work/cli.out") $(json '[d["agreement"]["name"], d["effective"]["account_manager"]["source"], d["effective"]["ends_on"]["value"], d["effective"]["ends_on"]["source"]]')"
    api GET "/audit-events?record_hid=$contract&limit=1"
    made="$made $(json '[[e["via"], e["action"], [c["field"] for c in e["changes"]]] for e in d["items"]]')"
    cli_run "$work/cli.out" contracts set CON-2026-0107 agreement=
    api GET "/contracts/$contract"
    expect "pkg hirdir contracts set NUMBER agreement=NAME rolls the contract that stands by itself into the Cisco agreement: it has whom to ask from the agreement, and keeps its own period, which overrides the agreement's; that is one change of the contract, made through the command line; agreement= takes it out again" \
        "$made | $code $(json '[d["agreement"], d["effective"]["account_manager"]["source"]]')" \
        '0 1 ["Cisco Enterprise Agreement", "agreement", "2027-08-31", "own"] [["cli", "update", ["agreement_hid"]]] | 0 [null, "none"]'

    # It is renewed, in one place.
    api GET '/items?filter=asset_tag:eq:AT-000107'
    wanted=$(json 'd["items"][0]["row_version"]')
    cli_run "$work/cli.out" contracts renew CON-2026-0107 --number CON-2027-0107 --from 2026-09-01 --to 2028-08-31 --purchase-reference RITM0019999 --annual-cost 2600.00
    made="$code $(matches "^CON-2026-0107 is now CON-2027-0107, 2026-09-01 to 2028-08-31; $((2 + phones)) items follow\$" "$work/cli.out")"
    api GET "/contracts/$contract/terms"
    made="$made $(json '[[t["number"], t["ends_on"], t["purchase_reference"], t["annual_cost"]] for t in d]')"
    api GET '/items?filter=asset_tag:eq:AT-000107'
    expect "pkg hirdir contracts renew gives the contract a new number, a new period, a new purchase reference and a new cost in one change, and says how many items follow: the spare under it shows the new number and the new last day, at the row_version it had ($wanted), and the term before is kept" \
        "$made $(json '[[[c["contract"]["number"] for c in i["coverage"]], i["covered_until"], i["row_version"]] for i in d["items"]]')" \
        "0 1 [[\"CON-2026-0107\", \"2027-08-31\", \"RITM0012345\", \"2400.00\"]] [[[\"CON-2027-0107\"], \"2028-08-31\", $wanted]]"
    cli_run "$work/cli.contract" contracts show CON-2027-0107
    made="$code | $(sed -n 's/^purchase_reference: *//p' "$work/cli.contract") | $(sed -n 's/^annual_cost: *//p' "$work/cli.contract") | $(sed -n 's/^earlier term: *//p' "$work/cli.contract")"
    cli_run /dev/null contracts renew CON-2027-0107
    made="$made | $code"
    cli_run /dev/null contracts show CON-2026-0107
    made="$made $code"
    # The day of the application, which is the day the contract left the agreement and
    # was renewed.
    api GET '/reports/coverage?limit=1'
    expect "pkg hirdir contracts show finds it by its new number, with the earlier term beneath what it says now: the part of its history that began when it left the agreement today, which the renewal ended on its first day, and is listed as of that day, while the parts that a join and a leave ended on the day they began are not (D-181); a renewal that gives neither a number nor a period exits with 4, and so does a number that no contract has any more" \
        "$made" \
        "0 | RITM0019999 | 2600.00 | CON-2026-0107, 2026-09-01 to 2027-08-31, RITM0012345; $(json_field as_of) to $(json_field as_of), began by left, by itself | 4 4"

    # A renewal that is entered before the term ends is the next term (D-150).
    early=$(day_from_today 700)
    late=$(day_from_today 1000)
    cli_run "$work/cli.out" contracts renew CON-2027-0107 --number CON-2029-0107 --from "$early" --to "$late"
    made="$code $(matches "^CON-2027-0107 renews as CON-2029-0107 on $early, to $late; until then it runs on as it is" "$work/cli.out")"
    api GET "/contracts/$contract"
    made="$made $(json '[d["number"], d["ends_on"], d["next_term"]["number"], d["next_term"]["starts_on"], d["next_term"]["ends_on"]]')"
    api GET '/items?filter=asset_tag:eq:AT-000107'
    made="$made $(json '[[[c["contract"]["number"] for c in i["coverage"]], i["covered_until"], i["row_version"]] for i in d["items"]]')"
    cli_run "$work/cli.contract" contracts show CON-2027-0107
    made="$made | $code $(sed -n 's/^next term: *//p' "$work/cli.contract")"
    cli_run "$work/cli.out" contracts renew CON-2027-0107 --withdraw
    made="$made | $code $(matches '^CON-2027-0107: the term that was to begin is withdrawn$' "$work/cli.out")"
    api GET "/contracts/$contract"
    expect "pkg hirdir contracts renew with a period that begins after today keeps the renewal as the next term and says so: the contract has the number and the period it had, the spare under it is covered to the last day of the next term at the row_version it had ($wanted), and hirdir contracts show prints the term to come; --withdraw takes it back" \
        "$made $(json '[d["number"], d["next_term"]]')" \
        "0 1 [\"CON-2027-0107\", \"2028-08-31\", \"CON-2029-0107\", \"$early\", \"$late\"] [[[\"CON-2027-0107\"], \"$late\", $wanted]] | 0 CON-2029-0107, $early to $late | 0 1 [\"CON-2027-0107\", null]"
    cli_run "$work/cli.out" agreements renew 'Juniper Enterprise Agreement' --from "$early" --to "$late"
    made="$code $(matches "^Juniper Enterprise Agreement renews on $early, to $late; until then it runs on as it is" "$work/cli.out")"
    api GET '/agreements?filter=name:eq:Juniper%20Enterprise%20Agreement'
    made="$made $(json '[[a["ends_on"], a["next_term"]["starts_on"], a["next_term"]["ends_on"]] for a in d["items"]]')"
    cli_run "$work/cli.table" agreements list --sort name
    made="$made | $code $(head -n 1 "$work/cli.table" | xargs) $(awk '$2 == "Juniper" {print $(NF - 1)}' "$work/cli.table")"
    cli_run "$work/cli.out" agreements renew 'Juniper Enterprise Agreement' --withdraw
    api GET '/agreements?filter=name:eq:Juniper%20Enterprise%20Agreement'
    expect "pkg hirdir agreements renew does the same for an agreement, by its name: the Juniper agreement of the examples keeps its period and has a next term, which hirdir agreements list shows the first day of; --withdraw takes it back" \
        "$made | $code $(json '[a["next_term"] for a in d["items"]]')" \
        "0 1 [[\"2026-12-31\", \"$early\", \"$late\"]] | 0 HID NAME NUMBER VENDOR STARTS_ON ENDS_ON STATUS NEXT_STARTS_ON RECORD_STATUS $early | 0 [null]"

    # A purchase request, and a delivery on one of its lines.
    received=$(table 'sum(r["purchase_line"].startswith("RITM0012345/") for r in rows)' examples/items.csv)
    cli_run "$work/cli.purchase" purchases show RITM0012345
    expect "S32 hirdir purchases show takes a request by its reference and prints it with its three lines and what is still to come: all eight of the two lines that are tracked but the $received that arrived; the second line has its part number, and the tape of the third is not tracked and waits for nothing" \
        "$code $(sed -n 's/^still to come: *//p' "$work/cli.purchase") | $(printed_columns "$work/cli.purchase" line pid part_number quantity received pending | grep '^RITM0012345/' | xargs)" \
        "0 $((8 - received)) of 8 | RITM0012345/1:C9300-48P::4:$received:$((4 - received)) RITM0012345/2:PWR-C1-715WAC-P:PWR-C1-715WAC-P=:4:0:4 RITM0012345/3:(not tracked):HLT-100:20:0:0"
    cli_run "$work/cli.out" purchases receive RITM0012345/2 --serial PKG0000R001 --serial PKG0000R002 --location 'Americas > Central > Site-2 > Store Room' --on 2026-11-02
    made="$code $(matches '^2 items received on RITM0012345/2; 2 of 4 are still to come$' "$work/cli.out")"
    api GET '/items?filter=serial_number:glob:PKG0000R00*&sort=serial_number'
    made="$made $(json '[[i["serial_number"], i["catalog"]["pid"], i["lifecycle_state"], i["purchase_line"]["name"], i["location"]["name"], i["delivered_on"]] for i in d["items"]]')"
    cli_run /dev/null purchases receive RITM0012345/2 --serial PKG0000R003 --serial PKG0000R004 --serial PKG0000R005
    made="$made | $code"
    cli_run /dev/null purchases receive RITM0099999/1 --serial PKG0000R009
    made="$made $code"
    api GET '/items?filter=serial_number:glob:PKG0000R00*&limit=1'
    expect "S32 hirdir purchases receive takes a line as REFERENCE/NUMBER and a serial number for each item that arrived, with where and when: two power supplies of the line's model are made, Delivered, in the store room, on that day, each naming the line; three more, where two are still to come, exit with 4 and make nothing, and so does a line that there is not" \
        "$made $(json_field total)" \
        '0 1 [["PKG0000R001", "PWR-C1-715WAC-P", "Delivered", "RITM0012345/2", "Store Room", "2026-11-02"], ["PKG0000R002", "PWR-C1-715WAC-P", "Delivered", "RITM0012345/2", "Store Room", "2026-11-02"]] | 4 4 2'
    cli_run "$work/cli.out" purchases receive RITM0012345/2 --count 2
    made="$code $(matches '^2 items received on RITM0012345/2; 0 of 4 are still to come$' "$work/cli.out")"
    authorized GET "$prefix/api/v1/items" --get --data-urlencode 'filter=name:glob:RITM0012345/2-*' --data-urlencode 'sort=name'
    made="$made $(json '[[i["name"], i["serial_number"], i["lifecycle_state"], i["purchase_line"]["name"]] for i in d["items"]]')"
    api GET '/purchase-requests?filter=reference:eq:RITM0012345'
    expect "S32 hirdir purchases receive --count takes the rest of the line as a count: two items are made that are named for the line and their place on it, with no serial number yet; the request, whose other line has not all arrived, keeps its status" \
        "$made $(json '[[r["status"], r["pending_quantity"]] for r in d["items"]]')" \
        "0 1 [[\"RITM0012345/2-003\", null, \"Delivered\", \"RITM0012345/2\"], [\"RITM0012345/2-004\", null, \"Delivered\", \"RITM0012345/2\"]] [[\"ordered\", $((4 - received))]]"

    # The portfolio of a vendor.
    api GET "/vendors/$(hid_of vendors 'name:eq:Cisco')/portfolio"
    wanted=$(json '"{} | {} | {} of {} | {} {}".format(d["totals"]["items"], d["totals"]["annual_support_cost"], d["totals"]["covered"], d["totals"]["covered"] + d["totals"]["uncovered"], len(d["contracts"]), len(d["models"]))')
    received=$(json 'd["totals"]["items"]')
    cli_run "$work/cli.portfolio" vendors portfolio Cisco
    expect "S31 hirdir vendors portfolio prints for Cisco what GET /vendors/{hid}/portfolio answers: its items, their cost and how many of the major ones are covered, its agreement and a line for each of its contracts, a row for each of the four kinds and one for each model" \
        "$code $(sed -n 's/^items: *//p' "$work/cli.portfolio") | $(sed -n 's/^annual_support_cost: *//p' "$work/cli.portfolio") | $(sed -n 's/^covered: *//p' "$work/cli.portfolio") | $(grep -c '^contract: ' "$work/cli.portfolio") $(sed -n '/^PID /,$p' "$work/cli.portfolio" | tail -n +2 | grep -c .) | $(grep -c '^agreement: *Cisco Enterprise Agreement, 2025-01-01 to 2027-12-31, 2 contracts$' "$work/cli.portfolio") $(grep -c -E '^(hardware|virtual_machine|software|service) ' "$work/cli.portfolio")" \
        "0 $wanted | 1 4"
    cli_run "$work/cli-portfolio.csv" vendors portfolio Cisco --format csv
    made="$code $(table '[len(rows), [k in head for k in ("covered", "covered_until", "contracts")], [[r["covered"], r["covered_until"], r["contracts"]] for r in rows if r["asset_tag"] == "AT-000107"]]' "$work/cli-portfolio.csv")"
    cli_run /dev/null vendors portfolio Cisco --format json --output /tmp/cli-portfolio.json
    expect "S31 and as csv it writes the items of the vendor, one row each ($received), with whether each is covered, until when and by which contracts: the spare under the contract that was renewed has its new number; with --format json and --output it writes them to a file, as the envelope of an import" \
        "$made | $code $(inside bash -c 'grep -c "\"schema\": \"hirdir/1\", \"entity\": \"items\"" /tmp/cli-portfolio.json' 2>&1)" \
        "0 [$received, [true, true, true], [[\"true\", \"2028-08-31\", \"CON-2027-0107\"]]] | 0 1"

    # The reports of 0.6.0.
    api GET /reports/coverage
    wanted=$(json 'd["totals"]')
    said="$(json '" ".join(str(d["totals"][k]) for k in ("in_service", "covered", "uncovered", "out_of_service", "expiring", "overlapping", "renewal_pending"))') $(json 'd["lapsed_contracts"]["count"]')"
    received=$(json 'd["totals"]["uncovered"]')
    cli_run "$work/cli-coverage.json" report coverage --format json
    cp "$work/cli-coverage.json" "$work/body"
    made="$code $(json 'd["totals"]')"
    cli_run "$work/cli.coverage" report coverage
    expect "pkg hirdir report coverage, as json, counts what GET /reports/coverage counts, and on a terminal prints the day it is of, the seven counts, in service, covered, uncovered, out of service, expiring, overlapping and renewal pending, and how many contracts have lapsed" \
        "$made | $code $(grep -c '^as of: *20[0-9-]*$' "$work/cli.coverage") $(for name in in_service covered uncovered out_of_service expiring overlapping renewal_pending 'lapsed contracts'; do sed -n "s/^$name: *\\([0-9]*\\).*/\\1/p" "$work/cli.coverage"; done | xargs)" \
        "0 $wanted | 0 1 $said"
    cli_run "$work/cli.coverage" report coverage --section uncovered
    made="$code $(head -n 1 "$work/cli.coverage" | xargs) $(($(matches . "$work/cli.coverage") - 1))"
    cli_run "$work/cli.coverage" report coverage --section overlapping
    made="$made | $code $(($(matches . "$work/cli.coverage") - 1))"
    cli_run "$work/cli.coverage" report coverage --section renewal_pending
    made="$made $code $(($(matches . "$work/cli.coverage") - 1))"
    api GET /reports/coverage
    wanted=$(json '"{} 0 {}".format(d["totals"]["overlapping"], d["totals"]["renewal_pending"])')
    cli_run /dev/null report coverage --section nothing-of-the-kind
    expect "pkg hirdir report coverage --section uncovered is a table of the items in service that no contract covers, one line for each of the $received; --section overlapping and --section renewal_pending are tables of as many items as the report counts under each; a section that there is not exits with 4" \
        "$made $code" "0 NAME PID SERIAL_NUMBER LIFECYCLE_STATE SITE COVERED_UNTIL $received | 0 $wanted 4"
    api GET '/reports/end-of-life?date=end_of_sale&section=past&limit=1000'
    wanted=$(json 'd["dates"]')
    received=$(json 'd["total"]')
    cli_run "$work/cli-eol.json" report end-of-life --format json
    cp "$work/cli-eol.json" "$work/body"
    made="$code $(json '[d["date"], d["dates"]]')"
    cli_run "$work/cli.eol" report end-of-life
    made="$made | $code $(head -n 1 "$work/cli.eol" | xargs) $(matches '^(end_of_sale|end_of_sw_support|end_of_hw_support|ldos) ' "$work/cli.eol") $(matches '^FISCAL_YEAR ' "$work/cli.eol")"
    cli_run "$work/cli-eol.csv" report end-of-life --date end_of_sale --section past --format csv
    expect "pkg hirdir report end-of-life, as json, is of the LDoS date and counts for each of the four dates what GET /reports/end-of-life counts; on a terminal it is a table of the four dates and one of the fiscal years; with --date end_of_sale --section past, as csv, it lists the $received items of the examples whose model is no longer sold, each with that date" \
        "$made | $code $(table '[head, len(rows), all(r["end_of_sale"] for r in rows)]' "$work/cli-eol.csv")" \
        "0 [\"ldos\", $wanted] | 0 DATE PAST PAST_COMPONENTS APPROACHING APPROACHING_COMPONENTS 4 1 | 0 [[\"name\", \"pid\", \"serial_number\", \"lifecycle_state\", \"site\", \"end_of_sale\"], $received, true]"
    cli_run "$work/cli.replacements" report replacements
    made="$code $(matches '^2026-06-30 +site2-sw-floor-03 +site2-sw-access-07 +Refresh +CHG0031877$' "$work/cli.replacements") $(matches '^[0-9]+ replacements?: (.*, )?Refresh 1(,|$)' "$work/cli.replacements")"
    cli_run "$work/cli-replacements.csv" report replacements --filter 'reason:eq:refresh' --format csv
    expect "pkg hirdir report replacements lists the one replacement of the examples, the switch that left and the one that took its place, with the count of each reason beneath, one of them a refresh; with --filter, as csv, it is that row" \
        "$made | $code $(table '[head, [r["reference"] for r in rows]]' "$work/cli-replacements.csv")" \
        '0 1 1 | 0 [["replaced_on", "old_item", "new_item", "reason", "reference"], ["CHG0031877"]]'
    api GET /reports/capacity
    wanted=$(json 'd')
    said=$(json '" ".join(d[v][k] for k in ("supply", "balance") for v in ("active", "with_drafts"))')
    received=$(json 'len(d["active"]["by_category"])')
    cli_run "$work/cli-capacity.json" report capacity --format json
    cp "$work/cli-capacity.json" "$work/body"
    made="$code $(json 'd')"
    cli_run "$work/cli.capacity" report capacity
    expect "S39 hirdir report capacity, as json, is what GET /reports/capacity answers; on a terminal it is a table of the measures, without the drafts and with them, the supply and the balance of the examples among them, and a line for the supply of each of the $received categories that supply" \
        "$made | $code $(head -n 1 "$work/cli.capacity" | xargs) | $(awk '$1 == "supply" || $1 == "balance" {print $2, $3}' "$work/cli.capacity" | xargs) | $(grep -c '^supply: ' "$work/cli.capacity")" \
        "0 $wanted | 0 MEASURE ACTIVE WITH_DRAFTS | $said | $received"
}

# ---- operators, deliveries to the street address, planned locations, and what a group gives ----

# hid_of LIST FILTER: the HID of the one record of a list that a filter finds, a draft
# or a retired one too.
hid_of() {
    authorized GET "$prefix/api/v1/$1" --get --data-urlencode "filter=$2" \
        --data-urlencode 'include_drafts=true' --data-urlencode 'include_archived=true'
    json 'd["items"][0]["hid"]'
}

# What the items of a view have as their operator in force, by serial number: the
# label, where it came from, the person behind it, and whether it is open.
operators_of() {
    authorized GET "$prefix/api/v1/items" --get --data-urlencode "filter=$1" --data-urlencode 'sort=serial_number'
    json '[[i["serial_number"][-4:]] + [i["effective"]["operator_hid"][k] for k in ("label", "source", "contact", "is_open")] for i in d["items"]]'
}

# What the items of a view have as their location and their planned location, by serial
# number: the last name of each path, where it came from, and the item's own HIDs.
whereabouts() {
    authorized GET "$prefix/api/v1/items" --get --data-urlencode "filter=$1" --data-urlencode 'sort=serial_number'
    json '[[i["serial_number"][-4:]] + [x for k in ("location_hid", "planned_location_hid") for x in ((i["effective"][k]["label"] or "").rsplit(" > ", 1)[-1], i["effective"][k]["source"], i[k] is not None)] for i in d["items"]]'
}

# What the final decisions of 0.5.0 added, made through nginx under the prefix, each in
# small: an operator is a label with a person behind it, on an item, a group and a
# place (D-122, D-124, D-128); a site or a location says with one flag that deliveries
# go to its street address (D-115); an item and a group have a planned location, and
# are moved in when the place is made active (D-125, D-127); and a member with nothing
# of its own has the location, the plan and the operator of its group (D-129). files()
# runs this after geography(), in the places that made, while the examples are loaded:
# everything here has a name of its own, and what is counted is asked for with a filter
# that finds these items alone. What is made here stays, for hirdir admin reset to
# clear.
operators_and_plans() {
    section "operators, deliveries to the street address, planned locations and what a group gives its members, through nginx under $prefix/"
    local view='serial_number:glob:PKG0000N*'
    local here='Package Test Land > East > Package Test Site > Building 9 > Room 902'
    local land east site room switch_model supply_model pat lee made number entity rows
    local first second third switches=() stack depot yard bay new hall plan events request before

    east=$(hid_of regions 'name:eq:East parent.name:eq:Package Test Land')
    site=$(hid_of sites 'name:eq:Package Test Site')
    room=$(location_at "$here")
    pat=$(hid_of contacts 'name:eq:Pat Whitfield')
    lee=$(hid_of contacts 'name:eq:Lee Raman')
    switch_model=$(hid_of catalog-entries 'pid:eq:PT-48P')
    supply_model=$(hid_of catalog-entries 'pid:eq:PT-PWR-715')

    # An operator is a label, with a person behind it or nobody.
    api POST /operators "{\"label\": \"PT1\", \"description\": \"Package test, the first\", \"colour\": \"#1f6feb\", \"contact_hid\": \"$pat\"}"
    made="$status $(json '[d["label"], d["contact"]["name"], d["is_open"]]')"
    first=$(json_field hid)
    api POST /operators "{\"label\": \"PT2\", \"contact_hid\": \"$lee\"}"
    made="$made $status"
    second=$(json_field hid)
    api POST /operators '{"label": "PT3"}'
    made="$made $status $(json_field is_open)"
    third=$(json_field hid)
    api POST /operators '{"label": "pt1"}'
    expect "pkg POST $prefix/api/v1/operators makes three labels, two with a person behind them and one with nobody, which is open; a second label that differs only in its capitals is refused" \
        "$made $status $(json 'd["errors"][0]["field"]')" \
        '201 ["PT1", "Pat Whitfield", false] 201 201 true 409 label'

    # Five switches and a power supply. The first has an operator of its own, and the
    # power supply in it has that. The second and the third are a stack, which has an
    # operator and is in a room, and they have neither of their own. The fourth is in
    # that room and in no group, and the site it is in has an operator. The fifth is
    # nowhere and nobody's.
    made=""
    for number in "1:\"operator_hid\": \"$first\"" '2:"hostname": "pkgtest-ops-02"' '3:"hostname": "pkgtest-ops-03"' "4:\"location_hid\": \"$room\"" '5:"hostname": "pkgtest-ops-05"'; do
        api POST /items "{\"catalog_entry_hid\": \"$switch_model\", \"serial_number\": \"PKG0000N00${number%%:*}\", \"lifecycle_state\": \"Prod\", ${number#*:}}"
        made="$made$status "
        switches+=("$(json_field hid)")
    done
    api POST /items "{\"catalog_entry_hid\": \"$supply_model\", \"serial_number\": \"PKG0000N0P1\", \"parent_item_hid\": \"${switches[0]}\", \"position\": \"PS-A\"}"
    made="$made$status"
    api POST /device-groups "{\"type\": \"stack\", \"name\": \"pkgtest-ops\", \"operator_hid\": \"$second\", \"location_hid\": \"$room\", \"members\": [{\"item_hid\": \"${switches[1]}\", \"role\": \"master\", \"position\": 1}, {\"item_hid\": \"${switches[2]}\", \"role\": \"member\", \"position\": 2}]}"
    made="$made $status $(json '[d["operator"]["label"], d["location"]["name"]]')"
    stack=$(json_field hid)
    api GET "/sites/$site"
    api PATCH "/sites/$site" "{\"row_version\": $(json_field row_version), \"operator_hid\": \"$third\"}"
    expect "pkg five switches and a power supply are made, two of the switches as a stack that is given an operator and a room, and the site is given the label that is open" \
        "$made $status $(json 'd["operator"]["label"]')" '201 201 201 201 201 201 201 ["PT2", "Room 902"] 200 PT3'
    expect "pkg the operator in force is the item's own; for a minor item, that of the item it is in; for a member of a group, the group's; for an item in no group, that of the place it is at, here its site, which is open; and nobody for the item that is nowhere" \
        "$(operators_of "$view")" \
        '[["N001", "PT1", "own", "Pat Whitfield", false], ["N002", "PT2", "device_group", "Lee Raman", false], ["N003", "PT2", "device_group", "Lee Raman", false], ["N004", "PT3", "site", null, true], ["N005", null, "none", null, false], ["N0P1", "PT1", "parent_item", "Pat Whitfield", false]]'
    expect "pkg and the two switches of the stack are where the stack is, having no location of their own, and say that they have it from the group; the fourth has its own" \
        "$(whereabouts "$view" | python3 -c 'import json, sys; print(json.dumps([row[:4] for row in json.load(sys.stdin)]))')" \
        '[["N001", "", "none", false], ["N002", "Room 902", "device_group", false], ["N003", "Room 902", "device_group", false], ["N004", "Room 902", "own", true], ["N005", "", "none", false], ["N0P1", "", "none", false]]'
    made=""
    for number in 'effective.operator_hid:empty:true' 'operator.is_open:eq:true' "location:within:$here"; do
        authorized GET "$prefix/api/v1/items" --get --data-urlencode "filter=$view $number" --data-urlencode 'sort=serial_number'
        made="$made$status $(json '[i["serial_number"][-4:] for i in d["items"]]') "
    done
    expect "pkg the item list finds what nobody is assigned to, what is under a label with nobody behind it, and, within the room, the members of the stack with the switch that is there itself" \
        "$made" '200 ["N005"] 200 ["N004"] 200 ["N002", "N003", "N004"] '
    authorized GET "$prefix/api/v1/reports/summary" --get --data-urlencode "filter=$view" --data-urlencode 'by=operator'
    made="$status $(json 'sorted([r["label"] or "", r["items"], r["component_count"]] for r in d["rows"])')"
    authorized GET "$prefix/api/v1/reports/summary" --get --data-urlencode "filter=$view" --data-urlencode 'by=site' --data-urlencode 'operators=true'
    expect "pkg GET $prefix/api/v1/reports/summary by operator has a row for each label and one for what nobody is assigned to; by site with operators=true, each row names the operators in force among its items, with the items of each, nobody last" \
        "$made | $status $(json 'sorted([(r["label"] or "").rsplit(" > ", 1)[-1], [[o["label"], o["items"]] for o in r["operators"]]] for r in d["rows"])')" \
        '200 [["", 1, 1], ["PT1", 2, 1], ["PT2", 2, 2], ["PT3", 1, 1]] | 200 [["", [["PT1", 2], [null, 1]]], ["Package Test Site", [["PT2", 2], ["PT3", 1]]]]'

    # The person behind a label is changed in one place, and nothing else is written.
    authorized GET "$prefix/api/v1/items" --get --data-urlencode "filter=$view" --data-urlencode 'sort=serial_number'
    before=$(json '[[i["row_version"], i["updated_at"]] for i in d["items"]]')
    api PATCH "/operators/$first" "{\"row_version\": 1, \"contact_hid\": \"$lee\"}"
    made=$status
    api PATCH "/operators/$second" '{"row_version": 1, "contact_hid": null}'
    made="$made $status $(json_field is_open)"
    expect "pkg the first label is handed to another person and the second is left open: what each is on follows at once" \
        "$made $(operators_of "$view")" \
        '200 200 true [["N001", "PT1", "own", "Lee Raman", false], ["N002", "PT2", "device_group", null, true], ["N003", "PT2", "device_group", null, true], ["N004", "PT3", "site", null, true], ["N005", null, "none", null, false], ["N0P1", "PT1", "parent_item", "Lee Raman", false]]'
    expect "pkg and none of the items was written to: each is at the row_version it had, changed when it was" \
        "$(json '[[i["row_version"], i["updated_at"]] for i in d["items"]]')" "$before"
    # A label that is released stands for nothing: the next level up, or nobody.
    api POST "/operators/$second/retire" '{"row_version": 2}'
    made="$status $(json_field record_status)"
    expect "pkg the second label is released: the members of the stack have the operator of the next level up, which is that of the site their stack is at" \
        "$made $(operators_of "serial_number:in:PKG0000N002,PKG0000N003")" \
        '200 retired [["N002", "PT3", "site", null, true], ["N003", "PT3", "site", null, true]]'
    api POST "/operators/$third/retire" '{"row_version": 1}'
    authorized GET "$prefix/api/v1/items" --get --data-urlencode "filter=$view effective.operator_hid:empty:true" --data-urlencode 'sort=serial_number'
    expect "pkg and with the label of the site released too, nobody is assigned to them or to the fourth switch, and the item list says so" \
        "$status $(json '[i["serial_number"][-4:] for i in d["items"]]')" '200 ["N002", "N003", "N004", "N005"]'

    # Deliveries go to the street address: one flag, and nothing is typed twice.
    api POST /sites "{\"name\": \"Package Test Depot\", \"region_hid\": \"$east\", \"address1\": \"7 Sample Yard\", \"city\": \"Riverton\", \"state\": \"NY\", \"postal_code\": \"00000\", \"country\": \"US\", \"ship_same_as_address\": true}"
    made="$status $(json '[d["ship_same_as_address"], d["ship_address1"]]')"
    depot=$(json_field hid)
    api POST /locations "{\"name\": \"Bay 1\", \"site_hid\": \"$depot\", \"kind\": \"warehouse\"}"
    bay=$(json_field hid)
    api GET "/locations/$bay/effective"
    expect "pkg a site with a street address says that deliveries go there: nothing is stored as its shipping address, and a location in it has the street address of the site as its shipping address, whole, and is told that this is the street address" \
        "$made $status $(json '[d["ship_address"]["source"], d["ship_address"]["same_as_address"], d["ship_address"]["value"]]')" \
        '201 [true, null] 200 ["site", true, {"address1": "7 Sample Yard", "address2": null, "city": "Riverton", "country": "US", "postal_code": "00000", "state": "NY"}]'
    api POST /sites "{\"name\": \"Package Test Yard\", \"region_hid\": \"$east\", \"address1\": \"8 Sample Yard\", \"city\": \"Riverton\"}"
    made=$status
    yard=$(json_field hid)
    api GET "/sites/$yard/effective"
    made="$made $(json '[d["ship_address"]["source"], d["ship_address"]["value"]]')"
    api GET "/sites/$depot"
    api PATCH "/sites/$depot" "{\"row_version\": $(json_field row_version), \"ship_address1\": \"9 Other Road\"}"
    made="$made $status"
    api POST /sites "{\"name\": \"Package Test Plot\", \"region_hid\": \"$east\", \"ship_same_as_address\": true}"
    expect "pkg a site that has a street address and does not say so has no shipping address: a street address is never taken for one; the flag and a shipping address of the site's own are not both taken, and the flag needs a street address" \
        "$made $status" '201 ["none", null] 422 422'
    api GET "/regions/$east"
    api PATCH "/regions/$east" "{\"row_version\": $(json_field row_version), \"ship_address1\": \"5 Depot Road\", \"ship_city\": \"Riverton\"}"
    made=$status
    api GET "/sites/$yard/effective"
    made="$made $(json '[d["ship_address"]["source"], d["ship_address"]["value"]["address1"]]')"
    api GET "/sites/$depot/effective"
    expect "pkg the region is given a shipping address: the site that said nothing has it, from the region, and the site whose deliveries go to its street address keeps that, and says that it overrides the region's" \
        "$made $status $(json '[d["ship_address"]["source"], d["ship_address"]["value"]["address1"], d["ship_address"]["overrides_path"]]')" \
        '200 ["region", "5 Depot Road"] 200 ["own", "7 Sample Yard", "Package Test Land > East"]'

    # A new site is planned: a draft, with a room, and what is meant for it.
    api POST /sites "{\"name\": \"Package Test New Site\", \"region_hid\": \"$east\", \"record_status\": \"draft\"}"
    made=$status
    new=$(json_field hid)
    api POST /locations "{\"name\": \"Hall\", \"site_hid\": \"$new\", \"kind\": \"room\"}"
    made="$made $status"
    hall=$(json_field hid)
    api POST /device-groups "{\"type\": \"custom\", \"name\": \"pkgtest-plan\", \"members\": [{\"item_hid\": \"${switches[0]}\"}, {\"item_hid\": \"${switches[3]}\"}]}"
    made="$made $status"
    plan=$(json_field hid)
    api PATCH "/items/${switches[4]}" "{\"row_version\": 1, \"planned_location_hid\": \"$room\"}"
    made="$made $status $(json '[e["field"] for e in d["errors"]]')"
    api PATCH "/items/${switches[4]}" "{\"row_version\": 1, \"planned_location_hid\": \"$hall\"}"
    made="$made $status $(json '[d["location_hid"], d["planned_location"]["name"]]')"
    api PATCH "/device-groups/$plan" "{\"row_version\": 1, \"planned_location_hid\": \"$hall\"}"
    expect "pkg a site is made as a draft, with a room in it, and a group of the first switch, which is nowhere, and the fourth, which is in a room of its own; the fifth switch is not planned for a room that is in use, and is planned for the room of the draft site, and so is the group" \
        "$made $status $(json '[d["location_hid"], d["planned_location"]["name"]]')" \
        '201 201 201 422 ["planned_location_hid"] 200 [null, "Hall"] 200 [null, "Hall"]'
    expect "pkg nothing has moved: each is where it was, and the members of the group and the power supply in one of them are planned for where their group is planned for, the fifth switch by a plan of its own" \
        "$(whereabouts "$view")" \
        '[["N001", "", "none", false, "Hall", "device_group", false], ["N002", "Room 902", "device_group", false, "", "none", false], ["N003", "Room 902", "device_group", false, "", "none", false], ["N004", "Room 902", "own", true, "Hall", "device_group", false], ["N005", "", "none", false, "Hall", "own", true], ["N0P1", "", "none", false, "Hall", "device_group", false]]'
    authorized GET "$prefix/api/v1/geography/tree" --get --data-urlencode "filter=$view" --data-urlencode 'include_drafts=true' --data-urlencode "root=$new"
    made="$status $(json '[[r["name"], r["record_status"], r["items"], r["planned"], r["planned_groups"]] + [[c["name"], c["planned"], c["planned_groups"]] for c in r["children"]] for r in d["roots"]]')"
    api POST "/locations/$hall/retire" '{"row_version": 1}'
    made="$made $status"
    authorized GET "$prefix/api/v1/locations" --get --data-urlencode "filter=location:within:$hall in_use:eq:false" --data-urlencode 'include_drafts=true'
    expect "pkg the tree, asked for with the drafts, shows the draft site with nothing in it, four items and one group planned for it, in its room; the room is not retired while something is planned for it, and the list of locations finds it among those that are not in use" \
        "$made $status $(json '[l["name"] for l in d["items"]]')" '200 [["Package Test New Site", "draft", 0, 4, 1, ["Hall", 4, 1]]] 409 200 ["Hall"]'

    # The site is made active, and what is planned for it is moved in by that change.
    api GET '/audit-events?limit=1'
    events=$(json_field total)
    api PATCH "/sites/$new" '{"row_version": 1, "record_status": "active"}'
    expect "pkg PATCH $prefix/api/v1/sites/{hid} makes the site active" "$status $(json_field record_status)" "200 active"
    expect "pkg and what was planned for its room is there: the fifth switch and the group, each with its plan cleared; the first switch and its power supply, which are where their group is; and the fourth switch, which gave up the location of its own to go with its group" \
        "$(whereabouts "$view")" \
        '[["N001", "Hall", "device_group", false, "", "none", false], ["N002", "Room 902", "device_group", false, "", "none", false], ["N003", "Room 902", "device_group", false, "", "none", false], ["N004", "Hall", "device_group", false, "", "none", false], ["N005", "Hall", "own", true, "", "none", false], ["N0P1", "Hall", "device_group", false, "", "none", false]]'
    api GET "/device-groups/$plan"
    made=$(json '[d["location"]["name"], d["planned_location_hid"], d["row_version"]]')
    api GET '/audit-events?limit=20'
    request=$(json '[e["request_id"] for e in d["items"] if e["record_hid"] == "'"$new"'"][0]')
    expect "pkg each record that changed has an audit entry of its own, all under the request that made the site active and no other entry with them: the site, the group, the switch that had the plan, and the switch that gave up its own location" \
        "$made $(($(json_field total) - events)) $(json 'sorted([e["record_type"], e["action"], sorted(c["field"] for c in e["changes"])] for e in d["items"] if e["request_id"] == "'"$request"'")')" \
        '["Hall", null, 3] 4 [["device_group", "update", ["location_hid", "planned_location_hid"]], ["item", "update", ["location_hid"]], ["item", "update", ["location_hid", "planned_location_hid"]], ["site", "update", ["record_status"]]]'
    api GET "/items/${switches[4]}/history?limit=1"
    made=$(json '[[e["action"], sorted(c["field"] for c in e["changes"])] for e in d["items"]]')
    authorized GET "$prefix/api/v1/geography/tree" --get --data-urlencode "filter=$view" --data-urlencode "root=$new"
    expect "pkg the move is in the history of the switch, and the tree, with no drafts asked for, has the site with the four items in its room and nothing planned" \
        "$made $status $(json '[[r["name"], r["items"], r["planned"], r["planned_groups"]] + [[c["name"], c["items"]] for c in r["children"]] for r in d["roots"]]')" \
        '[["update", ["location_hid", "planned_location_hid"]]] 200 [["Package Test New Site", 4, 0, 0, ["Hall", 4]]]'
    authorized GET "$prefix/api/v1/locations" --get --data-urlencode "filter=location:within:$hall in_use:eq:true"
    expect "pkg and the list of locations finds the room among those that are in use now, with the one item that is put there itself" \
        "$status $(json '[[l["name"], l["items"]] for l in d["items"]]')" '200 [["Hall", 1]]'

    # A member with no owner of its own has the owner of its group (D-130), and where
    # that owner is outside the team it is marked as an exception.
    made=$(hid_of owners 'label:eq:Package Test Facilities')
    api PATCH "/device-groups/$plan" "{\"row_version\": 3, \"owner_hid\": \"$made\"}"
    made=$status
    authorized GET "$prefix/api/v1/items" --get --data-urlencode "filter=$view owner_hid:empty:true effective.owner_hid:empty:false" --data-urlencode 'sort=serial_number'
    expect "pkg the group is given an owner, one outside the team: its two members and the power supply in one of them, which have no owner of their own, have that owner from the group and are marked as exceptions, with nothing written to them, and filter=owner_hid:empty:true effective.owner_hid:empty:false lists them" \
        "$made $status $(json '[[i["serial_number"][-4:], i["effective"]["owner_hid"]["label"], i["effective"]["owner_hid"]["source"], i["owner_exception"], i["row_version"]] for i in d["items"]]')" \
        '200 200 [["N001", "Package Test Facilities", "device_group", true, 1], ["N004", "Package Test Facilities", "device_group", true, 2], ["N0P1", "Package Test Facilities", "device_group", true, 1]]'

    # What was made here, and the examples' with it, exported and imported back.
    for entity in operators sites locations device_groups; do
        api POST /exports "{\"entity\": \"$entity\", \"format\": \"csv\", \"own_values\": true, \"include_archived\": true, \"include_drafts\": true}"
        cp "$work/body" "$work/back-$entity.csv"
        rows=$(table 'len(rows)' "$work/back-$entity.csv")
        send "/imports/preview?entity=$entity&file_name=$entity.csv" "$work/back-$entity.csv"
        made="$status $(job_counts)"
        api POST /exports "{\"entity\": \"$entity\", \"format\": \"json\", \"own_values\": true, \"include_archived\": true, \"include_drafts\": true}"
        cp "$work/body" "$work/back-$entity.json"
        send "/imports/preview?file_name=$entity.json" "$work/back-$entity.json" application/json
        expect "pkg an export of every record of $entity ($rows rows), with the operators, the flag for deliveries and what was planned and moved, is imported back as it is, as CSV and as JSON: every row finds its record by HID, unchanged" \
            "$made $status $(job_counts)" \
            "201 [\"previewed\", $rows, 0, 0, $rows, 0] 201 [\"previewed\", $rows, 0, 0, $rows, 0]"
    done
    api POST /exports '{"entity": "items", "format": "csv", "own_values": true, "filter": "serial_number:glob:PKG0000N*", "sort": ["depth", "serial_number"]}'
    cp "$work/body" "$work/back-operated.csv"
    send "/imports/preview?entity=items&file_name=operated.csv" "$work/back-operated.csv"
    expect "pkg and an export of these items with their own values holds only what each has itself: the operator of the first and the location of the fifth, and nothing that comes from a group; it is imported back unchanged" \
        "$(table '[[r["serial_number"][-4:], r["operator"], r["location"].rsplit(" > ", 1)[-1], r["planned_location"]] for r in rows]' "$work/back-operated.csv") $status $(job_counts)" \
        '[["N001", "PT1", "", ""], ["N002", "", "", ""], ["N003", "", "", ""], ["N004", "", "", ""], ["N005", "", "Hall", ""], ["N0P1", "", "", ""]] 201 ["previewed", 6, 0, 0, 6, 0]'
}

# ---- contracts and coverage, purchases, external systems, capacity lines -----------------------

# How many agreements, contracts, coverages, purchase requests, purchase lines,
# external systems, registrations and capacity lines there are, the drafts and the
# retired among them, on one line.
records_of() {
    local name counted=""
    for name in agreements contracts contract-coverage purchase-requests purchase-lines external-systems registrations capacity-lines; do
        api GET "/$name?include_drafts=true&include_archived=true&limit=1"
        counted="$counted$(json_field total) "
    done
    echo "${counted% }"
}

# examples_service DAY WITHIN: what the coverage report must count of the examples on
# a day, worked out from the files, by the rules of D-140 to D-142, D-149 and D-150:
# the major items that are in Assigned, Test, Prod or Down, how many of them a
# contract covers on that day and how many none does, the items out of service that a
# contract still counts, the items in service whose cover runs out within so many
# days, the items that more than one contract covers, and the items under a contract
# whose renewal is pending, and the items in service that no contract covers and that
# are not to be renewed (D-182), which are left off what is not covered and what runs
# out soon.
#
# A contract covers on a day within its period when its status is active, and from
# the first day of its period on when its status is renewal_pending. Its period is
# its agreement's where it has none of its own, and the next term's from the day that
# starts. A coverage has the period of its contract where it has none of its own. An
# item is out of service and still counted when it is covered, or when its coverage
# was ended because it left service and the term of its contract still runs. The
# dates of the examples are fixed, so the answer moves with the calendar.
examples_service() {
    python3 -c '
import csv, json, sys
from datetime import date, timedelta

def rows(name):
    with open(f"examples/{name}.csv", encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))

def day_of(text):
    return date.fromisoformat(text) if text else None

day, within = date.fromisoformat(sys.argv[1]), timedelta(days=int(sys.argv[2]))
agreements = {r["name"]: r for r in rows("agreements")}
contracts = {(r["vendor"], r["number"]): r for r in rows("contracts")}
models = {(r["vendor"], r["pid"]): r for r in rows("catalog-entries")}
items = rows("items")
known = {r[key]: r for r in items for key in ("asset_tag", "serial_number", "hostname", "name") if r[key]}

def state(r):
    while not r["lifecycle_state"] and r["parent"]:
        r = known[r["parent"]]
    return r["lifecycle_state"]

def flagged(r):
    """Whether the item is not to be renewed: by its own flag, or by that of its model."""
    own = r.get("do_not_renew", "")
    return (own or models.get((r["vendor"], r["pid"]), {}).get("do_not_renew", "")) == "true"

def term(record):
    """The first and the last day in force on the day, and the last day that is known."""
    start, end = day_of(record.get("starts_on", "")), day_of(record.get("ends_on", ""))
    ahead, last = day_of(record.get("next_starts_on", "")), day_of(record.get("next_ends_on", ""))
    if ahead and ahead <= day:
        return ahead, last, last
    return start, end, last if ahead else end

def period(contract):
    own, above = term(contract), term(agreements.get(contract["agreement"], {}))
    return [mine if text else theirs for mine, theirs, text in zip(
        own, above, (contract["starts_on"], contract["ends_on"], contract["ends_on"]))]

cover = {}
for r in rows("contract-coverage"):
    contract = contracts[r["vendor"], r["contract"]]
    if contract["record_status"] != "active" or contract["status"] not in ("active", "renewal_pending"):
        continue
    start, end, last = period(contract)
    pending = contract["status"] == "renewal_pending"
    cover.setdefault(id(known[r["item"]]), []).append({
        "contract": (r["vendor"], r["contract"]),
        "start": day_of(r["starts_on"]) or start,
        # A renewal that is pending covers past the last day of the period.
        "end": day_of(r["ends_on"]) or (None if pending else end),
        "last": day_of(r["ends_on"]) or last,
        "runs": (not start or start <= day) and (pending or not end or day <= end),
        "left": r.get("left_service", "") == "true",
        "pending": pending,
        "active": contract["status"] == "active",
    })

def covering(r):
    return [c for c in cover.get(id(r), [])
            if (not c["start"] or c["start"] <= day) and (not c["end"] or day <= c["end"])]

def until(r):
    ends = [c["last"] for c in cover.get(id(r), []) if c["active"]]
    return None if not ends or None in ends else max(ends)

view = [r for r in items if r["record_status"] == "active" and state(r) != "Archived"]
service = [r for r in view if not r["parent"] and state(r) in ("Assigned", "Test", "Prod", "Down")]
gone = [r for r in items if r["record_status"] == "retired" or state(r) in ("Pending-Removal", "Released", "Archived")]
print(json.dumps({
    "covered": sum(bool(covering(r)) for r in service),
    "expiring": sum(1 for r in service if covering(r) and until(r) and until(r) <= day + within and not flagged(r)),
    "in_service": len(service),
    "not_renewed": sum(not covering(r) and flagged(r) for r in service),
    "out_of_service": sum(1 for r in gone if covering(r) or any(c["left"] and c["runs"] for c in cover.get(id(r), []))),
    "overlapping": sum(len({c["contract"] for c in covering(r)}) > 1 for r in view),
    "renewal_pending": sum(any(c["pending"] for c in covering(r)) for r in view),
    "uncovered": sum(not covering(r) and not flagged(r) for r in service),
}, sort_keys=True))' "$1" "$2"
}

# examples_end_of_life DAY WITHIN: what the end-of-life report must count of the
# examples on a day, worked out from the files: for each of the four dates, the items
# of the default view whose date in force, their own or their model's, is before the
# day, and those whose date is from the day to so many days ahead.
examples_end_of_life() {
    python3 -c '
import csv, json, sys
from datetime import date, timedelta

def rows(name):
    with open(f"examples/{name}.csv", encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))

day = date.fromisoformat(sys.argv[1])
ahead = day + timedelta(days=int(sys.argv[2]))
models = {(r["vendor"], r["pid"]): r for r in rows("catalog-entries")}
items = rows("items")
known = {r[key]: r for r in items for key in ("asset_tag", "serial_number", "hostname", "name") if r[key]}

def state(r):
    while not r["lifecycle_state"] and r["parent"]:
        r = known[r["parent"]]
    return r["lifecycle_state"]

view = [r for r in items if r["record_status"] == "active" and state(r) != "Archived"]
counted = {}
for name in ("end_of_sale", "end_of_sw_support", "end_of_hw_support", "ldos"):
    dates = [r[name] or models.get((r["vendor"], r["pid"]), {}).get(name, "") for r in view]
    dates = [date.fromisoformat(d) for d in dates if d]
    counted[name] = {"approaching": sum(day <= d <= ahead for d in dates), "past": sum(d < day for d in dates)}
print(json.dumps(counted, sort_keys=True))' "$1" "$2"
}

# examples_cover BEFORE: what the examples show of 0.6.0, looked for while they are
# loaded: support agreements with the contracts grouped into them and a contract that
# stands by itself, what the contracts cover on the day of the test, a spare that
# arrived on a purchase line and took the place of a switch, a stack that is
# registered where its switches are not, the capacity lines of the worked example
# against the support weight of the examples, and the portfolio of a vendor. BEFORE is
# what records_of said before the files were loaded: after an upgrade, what the
# upgrade pass made of these is there, retired or ended.
examples_cover() {
    local name made wanted="" day cisco received

    for name in agreements contracts contract-coverage purchase-requests purchase-lines external-systems registrations capacity-lines; do
        wanted="$wanted$(table 'len(rows)' "examples/$name.csv") "
    done
    expect "S12 the agreements, the contracts, their coverage, the purchase requests, their lines, the external systems, the registrations and the capacity lines of the examples are there, the draft line among them: each list holds what its file holds (${wanted% }), beside what there was ($1)" \
        "$(records_of)" \
        "$(python3 -c 'import sys; print(*(int(a) + int(b) for a, b in zip(sys.argv[1].split(), sys.argv[2].split())))' "$1" "$wanted")"

    # D-139: a contract in an agreement has from it what it does not say itself.
    authorized GET "$prefix/api/v1/contracts" --get --data-urlencode 'filter=agreement.name:eq:Cisco Enterprise Agreement' --data-urlencode 'sort=number'
    expect "pkg the two contracts that the examples group into the Cisco agreement have no period of their own and have the agreement's; the first has its support level too, and the second overrides it with its own" \
        "$status $(json '[[c["number"], c["starts_on"], c["ends_on"]] + [c["effective"][k][x] for k in ("starts_on", "ends_on", "support_level") for x in ("value", "source")] for c in d["items"]]')" \
        '200 [["CON-2025-0001", null, null, "2025-01-01", "agreement", "2027-12-31", "agreement", "24x7, four-hour response", "agreement"], ["CON-2025-0002", null, null, "2025-01-01", "agreement", "2027-12-31", "agreement", "8x5, next business day", "own"]]'
    api GET '/contracts?filter=number:eq:CON-2026-0107'
    made=$(json '[[c["agreement"], c["starts_on"], c["effective"]["ends_on"]["source"], c["effective"]["reseller_hid"]["label"], c["effective"]["account_manager"]["source"]] for c in d["items"]]')
    api GET '/agreements?sort=name'
    expect "pkg the contract for the switches bought lately stands by itself: it is in no agreement, has a period and a reseller of its own, and nobody to ask; each agreement counts the contracts that are grouped into it" \
        "$made $status $(json '[[a["name"], a["vendor"]["name"], a["contracts"]] for a in d["items"]]')" \
        '[[null, "2026-09-01", "own", "Example Reseller", "none"]] 200 [["Cisco Enterprise Agreement", "Cisco", 2], ["Juniper Enterprise Agreement", "Juniper", 1]]'

    # What is covered on the day of the test. The dates of the examples are fixed, so
    # what is looked for is worked out from the files for the day the report is of.
    api GET /reports/coverage
    day=$(json_field as_of)
    expect "S29 GET $prefix/api/v1/reports/coverage counts of the examples, on $day, what their files give for that day: the major items in Assigned, Test, Prod or Down, those of them that a contract covers and those that none does, what is out of service and still counted by a contract, what runs out within 90 days, what more than one contract covers, and what is under a contract whose renewal is pending" \
        "$status $(json 'd["totals"]')" "200 $(examples_service "$day" 90)"
    api GET '/reports/coverage?section=uncovered&limit=1000'
    made="$status $(json '[d["section"], d["total"] == d["sections"]["uncovered"]["count"] == d["totals"]["uncovered"] == len(d["items"]), sorted({(i["is_major"], i["covered"], i["effective"]["lifecycle_state"]["value"] in d["service_states"]) for i in d["items"]})]')"
    wanted=$(json 'sorted(i["hid"] for i in d["items"])')
    api POST /items/query "$(json '{"filter": d["sections"]["uncovered"]["filter"], "include_archived": d["sections"]["uncovered"]["include_archived"], "limit": 1000}')"
    expect "S30 asked for the section of what is in service with no cover, the report holds a page of those items, each a major item in service that is not covered, as many as it counts; the filter that the section gives lists the very same items on POST $prefix/api/v1/items/query" \
        "$made $status $([ "$(json 'sorted(i["hid"] for i in d["items"])')" = "$wanted" ] && echo the same items)" \
        '200 ["uncovered", true, [[true, false, true]]] 200 the same items'
    api GET /reports/end-of-life
    expect "S30 GET $prefix/api/v1/reports/end-of-life counts for each of the four dates the items of the examples whose date in force, their own or their model's, is past on $day, and those whose date is within two years of it, as examples/items.csv and examples/catalog-entries.csv give them" \
        "$status $(json '[d["date"], d["within_days"]]') $(json '{k: {s: v[s]["items"] for s in ("approaching", "past")} for k, v in d["dates"].items()}')" \
        "200 [\"ldos\", 730] $(examples_end_of_life "$day" 730)"

    # A spare that arrived on a purchase line, was put under the contract that stands
    # by itself, and took the place of a switch.
    api GET '/items?filter=asset_tag:in:AT-000107,AT-000133&sort=asset_tag&include_archived=true'
    expect "pkg a spare of the examples arrived on a purchase line, took the place of a switch of the floor stack, and is under the contract that stands by itself; the switch that left is not covered, its cover having been ended by a person on the day it was replaced, and its registration is marked as removed" \
        "$status $(json '[[i["asset_tag"], (i["purchase_line"] or {}).get("name"), (i["replaces"] or {}).get("serial_number"), (i["replaced_by"] or {}).get("serial_number"), [[c["contract"]["number"], c["ends_on"], c["left_service"]] for c in i["coverage"]], [[x["system"]["name"], x["status"]] for x in i["registrations"]]] for i in d["items"]]') $(json '[[i["covered"], i["contract_count"]] for i in d["items"]][1:]')" \
        '200 [["AT-000107", "RITM0012345/1", "JAE0000X003", null, [["CON-2026-0107", "2027-08-31", false]], []], ["AT-000133", null, null, "FCW0000X007", [["CON-2025-0001", "2026-06-30", false]], [["NetWatch", "removed"]]]] [[false, 0]]'
    received=$(table 'sum(r["purchase_line"] == "RITM0012345/1" for r in rows)' examples/items.csv)
    api GET '/purchase-lines?filter=request.reference:eq:RITM0012345&sort=line'
    expect "S32 the first line of a purchase request of the examples is for four switches: the $received that examples/items.csv says arrived on it are received and the rest are still to come, and nothing has arrived on its second line, which has its part number as procurement gave it; the third, of tape, has no model, is not tracked and waits for nothing (D-186)" \
        "$status $(json '[[l["name"], (l["catalog"] or {}).get("pid"), l["part_number"], l["tracked"], l["quantity"], l["received_quantity"], l["pending_quantity"], l["destination_site"]["path"]] for l in d["items"]]')" \
        "200 [[\"RITM0012345/1\", \"C9300-48P\", null, true, 4, $received, $((4 - received)), \"Americas > Central > Site-3\"], [\"RITM0012345/2\", \"PWR-C1-715WAC-P\", \"PWR-C1-715WAC-P=\", true, 4, 0, 4, \"Americas > Central > Site-3\"], [\"RITM0012345/3\", null, \"HLT-100\", false, 20, 0, 0, \"Americas > Central > Site-3\"]]"
    api GET '/reports/replacements?filter=reference:eq:CHG0031877'
    expect "pkg GET $prefix/api/v1/reports/replacements lists the one replacement of the examples, with the switch that left, the one that took its place, the reason and the day, and counts it under its reason" \
        "$status $(json '[[r["old_item"]["serial_number"], r["new_item"]["serial_number"], r["reason"], r["replaced_on"]] for r in d["items"]]') $(json '[[r["reason"], r["count"]] for r in d["by_reason"]]')" \
        '200 [["JAE0000X003", "FCW0000X007", "refresh", "2026-06-30"]] [["refresh", 1]]'

    # S33 on the examples: the core stack is registered, and its switches are not.
    authorized GET "$prefix/api/v1/device-groups" --get --data-urlencode 'filter=registration.system:eq:NetWatch'
    made="$status $(json '[[g["name"], sorted([x["system"]["name"], x["external_id"]] for x in g["registrations"])] for g in d["items"]]')"
    authorized GET "$prefix/api/v1/items" --get --data-urlencode 'filter=registration.system:eq:NetWatch' --data-urlencode 'include_archived=true' --data-urlencode 'sort=hostname'
    expect "S33 the core stack of the examples is registered with the monitoring system and with the SDN controller, and is the one device group that filter=registration.system:eq:NetWatch finds; among the items the filter finds what that system knows: the router that is registered itself, and the two switches of the stack, which have no registration of their own and say what their stack is registered with, and not the switch whose registration was removed" \
        "$made $status $(json '[[i["hostname"], len(i["registrations"]), sorted(x["system"]["name"] for x in i["group_registrations"])] for i in d["items"]]')" \
        '200 [["site2-sw-core", [["Fabric Director", "site2-sw-core"], ["NetWatch", "node-1001"]]]] 200 [["site2-rtr-wan-01", 2, []], ["site2-sw-core-01", 0, ["Fabric Director", "NetWatch"]], ["site2-sw-core-02", 0, ["Fabric Director", "NetWatch"]]]'

    # The capacity lines of the examples are those of the worked example, and the
    # examples weigh 32 where the worked example has 2,400: the supply is the same,
    # and the demand of the infrastructure is 32 / 300.
    api GET /reports/capacity
    expect "S39 GET $prefix/api/v1/reports/capacity of the examples: a support weight of 32 at 300 to the resource unit is a demand of 0.11, with 2 of other work 2.11; the supply is the 9 of the worked example by category, the balance 6.89 and the coverage 427.22%, two thirds of the supply the team's own; with the draft line the supply is 10 and the balance 7.89" \
        "$status $(json '[d["weight_per_resource_unit"]] + [d["active"][k] for k in ("support_weight", "infrastructure_demand", "other_demand", "demand", "supply", "balance", "coverage_pct", "own_units", "outside_units", "own_share_pct")] + [{c["category"]: c["units"] for c in d["active"]["by_category"] if c["lines"]}] + [d["with_drafts"][k] for k in ("supply", "balance")]')" \
        '200 ["300", "32", "0.11", "2", "2.11", "9", "6.89", "427.22", "6", "3", "66.67", {"professional_services": "1", "smart_hands": "0.5", "staff": "6", "tools": "1.5"}, "10", "7.89"]'

    # S31 on the examples: everything from one vendor in one place.
    cisco=$(hid_of vendors 'name:eq:Cisco')
    api GET "/vendors/$cisco/portfolio"
    made="$status $(json '[[k["kind"], k["items"] > 0] for k in d["kinds"]]') $(json '[a["name"] for a in d["agreements"]]') $(json 'sorted(c["number"] for c in d["contracts"])')"
    wanted=$(json 'd["totals"]["items"]')
    api POST /items/query "{\"filter\": $(json 'd["filter"]'), \"limit\": 1}"
    expect "S31 GET $prefix/api/v1/vendors/{hid}/portfolio for Cisco has a row for each of the four kinds, of which the examples have hardware alone, the agreement with Cisco and the three Cisco contracts; the filter it gives lists on the item list as many items as its totals count ($wanted)" \
        "$made $status $(json_field total)" \
        "200 [[\"hardware\", true], [\"virtual_machine\", false], [\"software\", false], [\"service\", false]] [\"Cisco Enterprise Agreement\"] [\"CON-2025-0001\", \"CON-2025-0002\", \"CON-2026-0107\"] 200 $wanted"
    made=$(hid_of vendors 'name:eq:Example Reseller')
    api GET "/vendors/$made/portfolio"
    expect "pkg the portfolio of the reseller of the examples, which makes nothing, lists the contracts that were bought through it, by the reseller in force: the one that names it, and the two that have it from the Cisco agreement; and the capacity line that names it" \
        "$status $(json '[d["totals"]["items"], sorted(c["number"] for c in d["contracts"]), [l["name"] for l in d["capacity_lines"]]]')" \
        '200 [0, ["CON-2025-0001", "CON-2025-0002", "CON-2026-0107"], ["Escalation partner"]]'

    # P-104: by contract, an item is in the row of each contract that covers it today.
    api GET '/contracts?limit=1000'
    wanted=$(json 'sorted(c["number"] + " (" + c["vendor"]["name"] + ")" for c in d["items"] if c["covered_items"])')
    api GET '/reports/management?by=contract'
    expect "pkg GET $prefix/api/v1/reports/management?by=contract has a row for each contract of the examples that covers something on $day, labelled with its number and its vendor, and one row of what no contract covers" \
        "$status $(json 'sorted(r["label"] for r in d["rows"] if r["key"])') $(json 'sum(r["key"] is None for r in d["rows"])')" \
        "200 $wanted 1"
}

# counted_in FILTER SITE DRAFTS: what every count says of the items of a view, with
# the drafts when DRAFTS is true: how many the item list holds, whether the list of
# sites has the site of that name, the components, the managed nodes and the support
# weight of the summary, the cost and the value of the management report, the items
# of the tree of places, and the items in service of the coverage report.
counted_in() {
    local counted
    authorized GET "$prefix/api/v1/items" --get --data-urlencode "filter=$1" --data-urlencode "include_drafts=$3" --data-urlencode 'limit=1'
    counted=$(json_field total)
    authorized GET "$prefix/api/v1/sites" --get --data-urlencode "filter=name:eq:$2" --data-urlencode "include_drafts=$3"
    counted="$counted $(json_field total)"
    authorized GET "$prefix/api/v1/reports/summary" --get --data-urlencode "filter=$1" --data-urlencode "include_drafts=$3"
    counted="$counted $(json '[d["totals"]["component_count"], d["totals"]["managed_node_count"], d["totals"]["support_weight"]]')"
    authorized GET "$prefix/api/v1/reports/management" --get --data-urlencode "filter=$1" --data-urlencode "include_drafts=$3"
    counted="$counted $(json '[d["totals"]["annual_support_cost"], d["totals"]["est_value"]]')"
    authorized GET "$prefix/api/v1/geography/tree" --get --data-urlencode "filter=$1" --data-urlencode "include_drafts=$3"
    counted="$counted $(json 'd["totals"]["items"]')"
    authorized GET "$prefix/api/v1/reports/coverage" --get --data-urlencode "filter=$1" --data-urlencode "include_drafts=$3"
    echo "$counted $(json 'd["totals"]["in_service"]')"
}

# The support weight that the capacity report counts, without the drafts and with
# them, on one line.
weighed() {
    api GET /reports/capacity
    json 'd["active"]["support_weight"] + " " + d["with_drafts"]["support_weight"]'
}

# gained BEFORE: by how much the two support weights that weighed prints have risen
# since it printed BEFORE.
gained() {
    python3 -c 'import sys
from decimal import Decimal
print(*(format((Decimal(now) - Decimal(was)).normalize(), "f") for was, now in zip(sys.argv[1].split(), sys.argv[2].split())))' "$1" "$(weighed)"
}

# The records that 0.6.0 added, made through nginx under the prefix: scenarios S29 to
# S35 of docs/build-plan.md, each in small. files() runs this while the examples are
# loaded, so everything here has a name of its own, and what is counted is asked for
# with a filter that finds these items alone. Every name is invented. What is made
# here stays, for hirdir admin reset to clear with the examples. S39 and S40, the
# capacity balance, are in capacity_balance(): the report is of the whole
# installation, so they are worked where the inventory holds nothing else.
cover_and_purchases() {
    section "contracts and coverage, purchases, external systems and registrations, drafts and archived items, through nginx under $prefix/"
    local view='serial_number:glob:PKG0000V*'
    local vendor maker switch old made wanted number name hid row_version last_year next_year ldos
    local east="" west="" land="" first second bare ending contract request line stack watch fabric
    local site suite kept gone before entity rows received own_token
    local other mistake early late alone registration agreement routes

    last_year=$(day_from_today -200)
    next_year=$(day_from_today 400)
    ldos="$(($(date +%Y) + 1))-06-30"
    api POST /vendors '{"name": "Package Test Supply"}'
    made=$status
    vendor=$(json_field hid)
    api POST /catalog-entries "{\"vendor_hid\": \"$vendor\", \"pid\": \"PC-48P\", \"est_value\": \"18000.00\", \"support_weight\": \"1.0\", \"annual_support_cost\": \"1200.00\"}"
    made="$made $status"
    switch=$(json_field hid)
    api POST /catalog-entries "{\"vendor_hid\": \"$vendor\", \"pid\": \"PC-24S\", \"ldos\": \"$ldos\"}"
    made="$made $status"
    old=$(json_field hid)

    # S29: one contract covering items in two regions, one of them archived.
    for number in East West; do
        api POST /regions "{\"name\": \"Package Test $number\"}"
        made="$made $status"
        if [ "$number" = East ]; then land=$(json_field hid); fi
        api POST /sites "{\"name\": \"Package Test $number Site\", \"region_hid\": \"$(json_field hid)\"}"
        made="$made $status"
        api POST /locations "{\"name\": \"Room 1\", \"site_hid\": \"$(json_field hid)\", \"kind\": \"room\"}"
        made="$made $status"
        if [ "$number" = East ]; then east=$(json_field hid); else west=$(json_field hid); fi
    done
    api POST /items "{\"catalog_entry_hid\": \"$switch\", \"serial_number\": \"PKG0000V001\", \"lifecycle_state\": \"Prod\", \"location_hid\": \"$east\"}"
    made="$made $status"
    first=$(json_field hid)
    api POST /items "{\"catalog_entry_hid\": \"$switch\", \"serial_number\": \"PKG0000V002\", \"lifecycle_state\": \"Prod\", \"location_hid\": \"$west\"}"
    made="$made $status"
    second=$(json_field hid)
    api POST /contracts "{\"number\": \"PKG-CON-0001\", \"vendor_hid\": \"$vendor\", \"starts_on\": \"$last_year\", \"ends_on\": \"$next_year\"}"
    made="$made $status"
    contract=$(json_field hid)
    api POST "/contracts/$contract/coverage" "{\"items\": [{\"item_hid\": \"$first\"}, {\"item_hid\": \"$second\"}]}"
    made="$made $status $(json 'sorted([c["item"]["serial_number"], c["in_force"]] for c in d)')"
    authorized GET "$prefix/api/v1/reports/coverage" --get --data-urlencode "filter=$view"
    expect "S29 a vendor, a model and a contract of a period that today is in are made, and two switches in Prod, each in a room of a site in a region of its own, are put under the contract by one request: GET $prefix/api/v1/reports/coverage, asked for these items alone, counts both as in service and covered" \
        "$made $status $(json 'd["totals"]')" \
        '201 201 201 201 201 201 201 201 201 201 201 201 201 [["PKG0000V001", true], ["PKG0000V002", true]] 200 {"covered": 2, "expiring": 0, "in_service": 2, "not_renewed": 0, "out_of_service": 0, "overlapping": 0, "renewal_pending": 0, "uncovered": 0}'
    row_version=1
    made=""
    for number in Pending-Removal Released Archived; do
        api POST "/items/$second/transition" "{\"to\": \"$number\", \"row_version\": $row_version}"
        made="$made$status "
        row_version=$(json_field row_version)
    done
    authorized GET "$prefix/api/v1/reports/coverage" --get --data-urlencode "filter=$view" --data-urlencode 'section=out_of_service'
    made="$made$status $(json '[d["totals"]["in_service"], d["totals"]["out_of_service"], [[i["serial_number"], i["effective"]["lifecycle_state"]["value"], [[c["contract"]["number"], c["ends_on"] == d["as_of"], c["left_service"]] for c in i["coverage"]]] for i in d["items"]]]')"
    api POST /items/query "$(json '{"filter": {"and": [d["sections"]["out_of_service"]["filter"], {"field": "serial_number", "op": "glob", "value": "PKG0000V*"}]}, "include_archived": d["sections"]["out_of_service"]["include_archived"]}')"
    expect "S29 the second is moved to Archived in three moves: its coverage ended on that day, and says that the item left service; the report counts one item in service and lists the other as out of service under a contract that still runs; the filter of that section lists the same item on the item list" \
        "$made $status $(json '[i["serial_number"] for i in d["items"]]')" \
        '200 200 200 200 [1, 1, [["PKG0000V002", "Archived", [["PKG-CON-0001", true, true]]]]] 200 ["PKG0000V002"]'
    api GET "/contracts/$contract/coverage"
    made="$status $(json '[d["total"], sorted([c["item"]["serial_number"], c["left_service"], c["ends_on"] is None] for c in d["items"])]')"
    api GET "/items/$first"
    made="$made $(json '[d["covered"], d["contract_count"]]')"
    api GET "/contracts/$contract"
    expect "S29 the contract still runs and still covers the switch that is in service; its coverage of the other is on record, ended: GET $prefix/api/v1/contracts/{hid}/coverage has both, the contract has two items in scope, and counts one as covered, as every count leaves out an archived item" \
        "$made $status $(json '[d["covers_today"], d["items_in_scope"], d["covered_items"], d["lapsed"]]')" \
        '200 [2, [["PKG0000V001", false, true], ["PKG0000V002", true, false]]] [true, 1] 200 [true, 2, 1, false]'

    # S30: an item in Prod with no coverage, and one whose model's LDoS is next year.    # S30: an item in Prod with no coverage, and one whose model's LDoS is next year.
    api POST /items "{\"catalog_entry_hid\": \"$switch\", \"serial_number\": \"PKG0000V003\", \"lifecycle_state\": \"Prod\"}"
    made=$status
    bare=$(json_field hid)
    api POST /items "{\"catalog_entry_hid\": \"$old\", \"serial_number\": \"PKG0000V004\", \"lifecycle_state\": \"Prod\"}"
    made="$made $status"
    ending=$(json_field hid)
    api POST /contracts "{\"number\": \"PKG-CON-0002\", \"vendor_hid\": \"$vendor\", \"starts_on\": \"$last_year\", \"ends_on\": \"$next_year\"}"
    made="$made $status"
    other=$(json_field hid)
    api POST "/contracts/$other/coverage" "{\"items\": [{\"item_hid\": \"$ending\"}]}"
    made="$made $status"
    # A coverage that was a mistake is removed outright: the first switch was never
    # meant to be under the second contract.
    api POST "/contracts/$other/coverage" "{\"items\": [{\"item_hid\": \"$bare\"}]}"
    mistake=$(json 'd[0]["hid"]')
    api DELETE "/contracts/$other/coverage/$mistake"
    made="$made $status"
    api GET "/audit-events?record_hid=$mistake&limit=1"
    made="$made $(json '[[e["record_type"], e["action"]] for e in d["items"]]')"
    authorized GET "$prefix/api/v1/reports/coverage" --get --data-urlencode "filter=$view" --data-urlencode 'section=uncovered'
    expect "S30 a switch in Prod under no contract, and one of a model whose LDoS is on $ldos, under a second contract; the first is put under that contract by mistake and its coverage is removed outright, with an audit event: the coverage report lists the first, and no other, as in service with no cover" \
        "$made $status $(json '[d["totals"]["in_service"], d["totals"]["uncovered"], [[i["hid"] == "'"$bare"'", i["serial_number"], i["covered"], i["coverage"]] for i in d["items"]]]')" \
        '201 201 201 201 204 [["contract_coverage", "delete"]] 200 [3, 1, [[true, "PKG0000V003", false, []]]]'
    authorized GET "$prefix/api/v1/reports/end-of-life" --get --data-urlencode "filter=$view" --data-urlencode 'section=approaching'
    expect "S30 GET $prefix/api/v1/reports/end-of-life, which is of the LDoS date unless asked otherwise, lists the second as approaching it, with nothing past it, in the fiscal year that the date falls in" \
        "$status $(json '[d["date"], d["dates"]["ldos"]["approaching"], d["dates"]["ldos"]["past"], [[i["serial_number"], i["effective"]["ldos"]["value"], i["effective"]["ldos"]["source"]] for i in d["items"]], [[y["fiscal_year"], y["items"]] for y in d["by_fiscal_year"]]]')" \
        "200 [\"ldos\", {\"component_count\": 1, \"items\": 1}, {\"component_count\": 0, \"items\": 0}, [[\"PKG0000V004\", \"$ldos\", \"catalog\"]], [[${ldos%%-*}, 1]]]"

    # D-150: a renewal that is entered early is the next term, and the present one
    # runs on; a renewal that is late is said to be pending, and the contract covers
    # past its last day; one that says nothing has lapsed.
    early=$(day_from_today 500)
    late=$(day_from_today 800)
    api POST "/contracts/$other/renew" "{\"row_version\": 1, \"number\": \"PKG-CON-9002\", \"starts_on\": \"$early\", \"ends_on\": \"$late\", \"purchase_reference\": \"PKG-REQ-0009\"}"
    made="$status $(json '[d["number"], d["ends_on"], d["next_term"]["number"], d["next_term"]["starts_on"], d["next_term"]["purchase_reference"]]')"
    api GET "/items/$ending"
    made="$made $(json '[[c["contract"]["number"] for c in d["coverage"]], d["covered"], d["covered_until"], d["row_version"]]')"
    api POST "/contracts/$other/renew" '{"row_version": 2, "withdraw": true}'
    made="$made $status $(json '[d["number"], d["next_term"]]')"
    api GET "/items/$ending"
    expect "pkg POST $prefix/api/v1/contracts/{hid}/renew with a period that starts after today keeps the renewal as the next term: the contract has the number and the period it had, the item under it is covered to the last day of the next term, and nothing is written to it; withdrawn, the next term is gone and the item is covered to the last day it was" \
        "$made $(json '[d["covered_until"], d["row_version"]]')" \
        "200 [\"PKG-CON-0002\", \"$next_year\", \"PKG-CON-9002\", \"$early\", \"PKG-REQ-0009\"] [[\"PKG-CON-0002\"], true, \"$late\", 1] 200 [\"PKG-CON-0002\", null] [\"$next_year\", 1]"
    api PATCH "/contracts/$other" "{\"row_version\": 3, \"ends_on\": \"$(day_from_today -30)\", \"status\": \"renewal_pending\"}"
    made="$status $(json '[d["status"], d["covers_today"], d["lapsed"]]')"
    authorized GET "$prefix/api/v1/reports/coverage" --get --data-urlencode "filter=$view" --data-urlencode 'section=renewal_pending'
    made="$made $status $(json '[d["totals"]["uncovered"], d["totals"]["renewal_pending"], [[i["serial_number"], i["covered"], [c["contract"]["status"] for c in i["coverage"]]] for i in d["items"]]]')"
    api PATCH "/contracts/$other" '{"row_version": 4, "status": "active"}'
    made="$made | $status $(json '[d["status"], d["covers_today"], d["lapsed"]]')"
    # The count of lapsed contracts follows the report's filter (D-168): asked for these
    # items alone, it is of the one contract that is in their scope, and its filter names
    # it; the report of everything counts every lapsed contract there is.
    authorized GET "$prefix/api/v1/reports/coverage" --get --data-urlencode "filter=$view"
    made="$made $(json '[d["totals"]["uncovered"], d["totals"]["renewal_pending"], d["lapsed_contracts"]["count"], d["lapsed_contracts"]["filter"] == {"and": [{"field": "hid", "op": "in", "value": ["'"$other"'"]}, {"field": "lapsed", "op": "eq", "value": True}]}]')"
    api GET /reports/coverage
    made="$made $(json '[d["lapsed_contracts"]["count"] >= 1, d["lapsed_contracts"]["filter"]]')"
    api GET '/contracts?filter=lapsed:eq:true&limit=1000'
    made="$made $status $(json 'sum(c["number"] == "PKG-CON-0002" for c in d["items"])')"
    api PATCH "/contracts/$other" "{\"row_version\": 5, \"ends_on\": \"$next_year\"}"
    expect "pkg the period of the contract is ended a month ago and its status said to be renewal_pending: it covers still, and the coverage report lists its item under the renewals that are pending, and not as uncovered; said to be active again, with its period past, it has lapsed and covers nothing, its item is uncovered, and the report asked for these items counts the one lapsed contract in their scope, with a filter that names it, where the report of everything counts every lapsed contract, among which the list of contracts finds it; given its last day back, it has not lapsed" \
        "$made | $status $(json '[d["covers_today"], d["lapsed"]]')" \
        '200 ["renewal_pending", true, false] 200 [1, 1, [["PKG0000V004", true, ["renewal_pending"]]]] | 200 ["active", false, true] [2, 0, 1, true] [true, {"field": "lapsed", "op": "eq", "value": true}] 200 1 | 200 [true, false]'

    # S31: a vendor with switches, a virtual machine template, a software application
    # and a service.
    api POST /vendors '{"name": "Package Test Portfolio"}'
    made=$status
    maker=$(json_field hid)
    number=10
    for name in PF-48P:hardware:1.0:1200.00:2 PF-VM:virtual_machine:0.5:300.00:1 PF-NCM:software:2.0:9000.00:1 PF-SVC:service:0.25:20000.00:1; do
        IFS=: read -r hid kept gone before rows <<<"$name"
        api POST /catalog-entries "{\"vendor_hid\": \"$maker\", \"pid\": \"$hid\", \"kind\": \"$kept\", \"support_weight\": \"$gone\", \"annual_support_cost\": \"$before\"}"
        made="$made $status"
        hid=$(json_field hid)
        for _ in $(seq "$rows"); do
            number=$((number + 1))
            api POST /items "{\"catalog_entry_hid\": \"$hid\", \"serial_number\": \"PKG0000V0$number\", \"lifecycle_state\": \"Prod\"}"
            made="$made $status"
        done
    done
    api GET "/vendors/$maker/portfolio"
    expect "S31 a second vendor is given two switches, a virtual machine, a software application and a service, each of a model with a support weight and an annual support cost: GET $prefix/api/v1/vendors/{hid}/portfolio lists the four kinds, each with its items, its cost and its weight, the totals of all five, and the four models" \
        "$made $status $(json '[[k["kind"], k["items"], k["annual_support_cost"], k["support_weight"]] for k in d["kinds"]]') $(json '[d["totals"][k] for k in ("items", "annual_support_cost", "support_weight")]') $(json '[m["pid"] for m in d["models"]]')" \
        '201 201 201 201 201 201 201 201 201 201 200 [["hardware", 2, "2400.00", "2"], ["virtual_machine", 1, "300.00", "0.5"], ["software", 1, "9000.00", "2"], ["service", 1, "20000.00", "0.25"]] [5, "31700.00", "4.75"] ["PF-48P", "PF-NCM", "PF-SVC", "PF-VM"]'
    api POST /exports "{\"entity\": \"items\", \"format\": \"csv\", \"filter\": $(json 'd["filter"]'), \"columns\": [\"pid\", \"kind\", \"serial_number\", \"annual_support_cost\", \"covered\"]}"
    expect "S31 and the filter that the portfolio gives exports its items: POST $prefix/api/v1/exports with it writes the five, each with its kind, its cost and whether it is covered" \
        "$status $(table '[head, sorted(r["kind"] for r in rows), sorted({r["covered"] for r in rows})]')" \
        '200 [["hid", "pid", "kind", "serial_number", "annual_support_cost", "covered"], ["hardware", "hardware", "service", "software", "virtual_machine"], ["false"]]'

    # S32: a purchase request with a line of ten switches, of which six arrive.
    api POST /purchase-requests '{"reference": "PKG-REQ-0001"}'
    made=$status
    request=$(json_field hid)
    api POST "/purchase-requests/$request/lines" "{\"catalog_entry_hid\": \"$switch\", \"quantity\": 10}"
    made="$made $status $(json '[d["name"], d["received_quantity"], d["pending_quantity"]]')"
    line=$(json_field hid)
    row_version=$(json_field row_version)
    authorized GET "$prefix/api/v1/reports/summary" --get --data-urlencode "filter=purchase_line_hid:eq:$line"
    expect "S32 POST $prefix/api/v1/purchase-requests and POST .../{hid}/lines make a request with a line of ten switches: a line is not inventory, and nothing of it is an item or a component" \
        "$made $status $(json '[d["totals"]["items"], d["totals"]["component_count"]]')" \
        '201 201 ["PKG-REQ-0001/1", 0, 10] 200 [0, 0]'
    api POST "/purchase-lines/$line/receive" "{\"row_version\": $row_version, \"items\": [$(printf '{"serial_number": "PKG0000V02%s"}, ' 1 2 3 4 5 | sed 's/, $//'), {\"serial_number\": \"PKG0000V026\"}]}"
    made="$status $(json '[d["received_quantity"], d["pending_quantity"], len(d["items"])]')"
    row_version=$(json_field row_version)
    received=$(header x-request-id)
    authorized GET "$prefix/api/v1/items" --get --data-urlencode "filter=purchase_line_hid:eq:$line" --data-urlencode 'sort=serial_number'
    made="$made $status $(json '[d["total"], sorted({(i["lifecycle_state"], i["purchase_line"]["name"], i["catalog"]["pid"]) for i in d["items"]}), [i["serial_number"][-3:] for i in d["items"]]]')"
    authorized GET "$prefix/api/v1/reports/summary" --get --data-urlencode "filter=purchase_line_hid:eq:$line"
    made="$made $(json 'd["totals"]["component_count"]')"
    api GET '/purchase-lines?filter=pending_quantity:gt:0&limit=1000'
    expect "S32 POST $prefix/api/v1/purchase-lines/{hid}/receive with six serial numbers creates six items of the line's model in Delivered, each naming the line, which the item list finds by it; none is a component yet, and GET /purchase-lines?filter=pending_quantity:gt:0 has the line with four still to come" \
        "$made $status $(json '[[l["name"], l["pending_quantity"]] for l in d["items"] if l["hid"] == "'"$line"'"]')" \
        '201 [6, 4, 6] 200 [6, [["Delivered", "PKG-REQ-0001/1", "PC-48P"]], ["021", "022", "023", "024", "025", "026"]] 0 200 [["PKG-REQ-0001/1", 4]]'
    api POST "/purchase-lines/$line/receive" "{\"row_version\": $row_version, \"items\": [$(printf '{"serial_number": "PKG0000V06%s"}, ' 1 2 3 4 | sed 's/, $//'), {\"serial_number\": \"PKG0000V065\"}]}"
    made=$status
    authorized GET "$prefix/api/v1/items" --get --data-urlencode "filter=purchase_line_hid:eq:$line" --data-urlencode 'limit=1'
    expect "S32 five more, where four are still to come, are refused, and none of them is created" \
        "$made $status $(json_field total)" "422 200 6"
    api GET '/audit-events?limit=50'
    expect "pkg the receipt is audited: under its one request the audit trail has the receipt of the line and the creation of each of the six items, and nothing else" \
        "$status $(json 'sorted([e["record_type"], e["action"]] for e in d["items"] if e["request_id"] == "'"$received"'")')" \
        '200 [["item", "create"], ["item", "create"], ["item", "create"], ["item", "create"], ["item", "create"], ["item", "create"], ["purchase_line", "receive"]]'

    api GET "/purchase-lines/$line"
    api POST "/purchase-lines/$line/receive" "{\"row_version\": $(json_field row_version), \"quantity\": 4}"
    made="$status $(json '[d["received_quantity"], d["pending_quantity"], [i["name"] for i in d["items"]]]')"
    received=$(header x-request-id)
    api GET "/purchase-requests/$request"
    made="$made $(json_field status)"
    api GET '/audit-events?limit=50'
    expect "S32 the other four arrive with nothing to know them by yet, and are received as a count: each is an item named for its line and its place on it, and the request, all of it arrived, says received by itself, by the same request, with an audit event of its own" \
        "$made $(json 'sorted([e["record_type"], e["action"]] for e in d["items"] if e["request_id"] == "'"$received"'")')" \
        '201 [10, 0, ["PKG-REQ-0001/1-007", "PKG-REQ-0001/1-008", "PKG-REQ-0001/1-009", "PKG-REQ-0001/1-010"]] received [["item", "create"], ["item", "create"], ["item", "create"], ["item", "create"], ["purchase_line", "receive"], ["purchase_request", "update"]]'

    # S33: a stack registered with a monitoring system and an SDN controller.
    made=""
    wanted=""
    for number in 1 2 3 4; do
        api POST /items "{\"catalog_entry_hid\": \"$switch\", \"serial_number\": \"PKG0000V03$number\"}"
        made="$made$status "
        wanted="$wanted${wanted:+, }{\"item_hid\": \"$(json_field hid)\", \"role\": \"$([ "$number" = 1 ] && echo master || echo member)\", \"position\": $number}"
    done
    api POST /device-groups "{\"type\": \"stack\", \"name\": \"pkgtest-registered\", \"members\": [$wanted]}"
    made="$made$status"
    stack=$(json_field hid)
    api POST /external-systems '{"name": "Package Test Watch", "kind": "monitoring"}'
    made="$made $status"
    watch=$(json_field hid)
    api POST /external-systems '{"name": "Package Test Fabric", "kind": "sdn_controller"}'
    made="$made $status"
    fabric=$(json_field hid)
    api POST /registrations "{\"system_hid\": \"$watch\", \"group_hid\": \"$stack\", \"external_id\": \"node-4411\"}"
    made="$made $status $(json '[d["status"], d["group"]["name"]]')"
    api POST /registrations "{\"system_hid\": \"$fabric\", \"group_hid\": \"$stack\", \"external_id\": \"pkgtest-registered\"}"
    made="$made $status"
    api POST /registrations "{\"system_hid\": \"$watch\", \"group_hid\": \"$stack\", \"external_id\": \"node-4412\"}"
    made="$made $status"
    api GET "/device-groups/$stack"
    made="$made | $(json 'sorted([x["system"]["name"], x["external_id"]] for x in d["registrations"])')"
    authorized GET "$prefix/api/v1/items" --get --data-urlencode 'filter=serial_number:glob:PKG0000V03*'
    expect "S33 four switches are made a stack, and the stack is registered with a monitoring system and with an SDN controller, and not a second time with the first: both registrations are on the stack, and none is among the registrations of any of its four switches, each of which says in group_registrations what its stack is registered with" \
        "$made $(json '[d["total"], sorted({(len(i["registrations"]), tuple(sorted(x["system"]["name"] + " knows " + x["group"]["name"] for x in i["group_registrations"]))) for i in d["items"]})]')" \
        '201 201 201 201 201 201 201 201 ["registered", "pkgtest-registered"] 201 409 | [["Package Test Fabric", "pkgtest-registered"], ["Package Test Watch", "node-4411"]] [4, [[0, ["Package Test Fabric knows pkgtest-registered", "Package Test Watch knows pkgtest-registered"]]]]'
    api POST /items "{\"catalog_entry_hid\": \"$switch\", \"serial_number\": \"PKG0000V039\"}"
    alone=$(json_field hid)
    authorized GET "$prefix/api/v1/device-groups" --get --data-urlencode 'filter=registration.system:eq:Package Test Watch'
    made="$status $(json '[g["name"] for g in d["items"]]')"
    authorized GET "$prefix/api/v1/items" --get --data-urlencode 'filter=registration.system:eq:Package Test Watch' --data-urlencode 'sort=serial_number'
    made="$made $status $(json '[i["serial_number"][-3:] for i in d["items"]]')"
    authorized GET "$prefix/api/v1/items" --get --data-urlencode 'filter=registration.system:ne:Package Test Watch serial_number:glob:PKG0000V03*'
    expect "S33 filter=registration.system:eq: finds the stack among the device groups, and among the items what that system knows, which is each of the four switches through their stack; a fifth switch, in no stack, is the one that registration.system:ne: finds, which the system does not know" \
        "$made $status $(json '[i["serial_number"] for i in d["items"]]')" \
        '200 ["pkgtest-registered"] 200 ["031", "032", "033", "034"] 200 ["PKG0000V039"]'
    # A registration that was a mistake is removed outright.
    api POST /registrations "{\"system_hid\": \"$fabric\", \"item_hid\": \"$alone\"}"
    made=$status
    registration=$(json_field hid)
    api DELETE "/registrations/$registration"
    made="$made $status"
    api GET "/audit-events?record_hid=$registration&limit=1"
    made="$made $(json '[[e["record_type"], e["action"]] for e in d["items"]]')"
    api GET "/items/$alone"
    expect "pkg the fifth switch is registered with the SDN controller by mistake, and DELETE $prefix/api/v1/registrations/{hid} removes the registration outright, with an audit event: the switch is registered nowhere" \
        "$made $status $(json 'd["registrations"]')" \
        '201 204 [["registration", "delete"]] 200 []'

    # S34: a draft site with draft items is left out of every count until made active.    # S34: a draft site with draft items is left out of every count until made active.
    view='serial_number:glob:PKG0000V04*'
    before=$(weighed)
    api POST /sites "{\"name\": \"Package Test Draft Site\", \"region_hid\": \"$land\", \"record_status\": \"draft\"}"
    made=$status
    site=$(json_field hid)
    api POST /locations "{\"name\": \"Suite 300\", \"site_hid\": \"$site\", \"kind\": \"room\", \"record_status\": \"draft\"}"
    made="$made $status"
    suite=$(json_field hid)
    for number in 1 2 3; do
        api POST /items "{\"catalog_entry_hid\": \"$switch\", \"serial_number\": \"PKG0000V04$number\", \"lifecycle_state\": \"Prod\", \"location_hid\": \"$suite\", \"record_status\": \"draft\"}"
        made="$made $status"
    done
    expect "S34 a site that is a draft, a room in it and three switches there, all drafts though in Prod: the item list, the list of sites, the summary, the management report, the tree of places and the coverage report, asked for these items, count none of it" \
        "$made | $(counted_in "$view" 'Package Test Draft Site' false)" \
        '201 201 201 201 201 | 0 0 [0, 0, "0"] ["0.00", "0.00"] 0 0'
    expect "S34 asked for with the drafts, they count the three, their site, their support weight and their cost; the capacity report, which is of everything, has the support weight it had without the drafts, and three more with them" \
        "$(counted_in "$view" 'Package Test Draft Site' true) | $(gained "$before")" \
        '3 1 [3, 3, "3"] ["3600.00", "54000.00"] 3 3 | 0 3'
    made=$(said_of "$site" sites '"record_status": "active"')
    made="$made $(said_of "$suite" locations '"record_status": "active"')"
    api GET "/items?filter=$view&include_drafts=true"
    for hid in $(json '" ".join(i["hid"] + ":" + str(i["row_version"]) for i in d["items"])'); do
        api PATCH "/items/${hid%:*}" "{\"row_version\": ${hid#*:}, \"record_status\": \"active\"}"
        made="$made $status"
    done
    expect "S34 the site, the room and then the three items are made active: every count has them with nothing more asked, and the capacity report has their support weight as demand" \
        "$made | $(counted_in "$view" 'Package Test Draft Site' false) | $(gained "$before")" \
        '200 200 200 200 200 | 3 1 [3, 3, "3"] ["3600.00", "54000.00"] 3 3 | 3 3'

    # S35: an archived item is hidden by default, shown when asked for, still reached
    # by its HID, and keeps its history.
    view='serial_number:glob:PKG0000V05*'
    api POST /items "{\"catalog_entry_hid\": \"$switch\", \"serial_number\": \"PKG0000V051\", \"lifecycle_state\": \"Prod\"}"
    kept=$(json_field hid)
    api POST /items "{\"catalog_entry_hid\": \"$switch\", \"serial_number\": \"PKG0000V052\", \"lifecycle_state\": \"Prod\"}"
    gone=$(json_field hid)
    row_version=1
    for number in Pending-Removal Released Archived; do
        api POST "/items/$gone/transition" "{\"to\": \"$number\", \"row_version\": $row_version}"
        row_version=$(json_field row_version)
    done
    authorized GET "$prefix/api/v1/items" --get --data-urlencode "filter=$view"
    made="$status $(json '[i["hid"] == "'"$kept"'" for i in d["items"]]')"
    authorized GET "$prefix/api/v1/reports/summary" --get --data-urlencode "filter=$view"
    made="$made $(json 'd["totals"]["items"]')"
    authorized GET "$prefix/api/v1/items" --get --data-urlencode "filter=$view" --data-urlencode 'include_archived=true' --data-urlencode 'sort=serial_number'
    expect "S35 of two switches in Prod one is moved to Archived: the item list and the summary have the other alone, and with include_archived=true the list has both, the archived one told apart by its state" \
        "$made $status $(json '[[i["serial_number"], i["lifecycle_state"], i["record_status"]] for i in d["items"]]')" \
        '200 [true] 1 200 [["PKG0000V051", "Prod", "active"], ["PKG0000V052", "Archived", "active"]]'
    api GET "/items/$gone"
    made="$status $(json '[d["lifecycle_state"], d["record_status"]]')"
    api GET "/items/$gone/history?sort=at"
    expect "S35 the archived item is still reached by its HID, and its history is whole: its creation and each of the three moves, in order, each with who made it" \
        "$made $status $(json '[[e["action"] for e in d["items"]], [[c["old"], c["new"]] for e in d["items"] if e["action"] == "transition" for c in e["changes"] if c["field"] == "lifecycle_state"], sorted({e["actor_name"] for e in d["items"]})]')" \
        "200 [\"Archived\", \"active\"] 200 [[\"create\", \"transition\", \"transition\", \"transition\"], [[\"Prod\", \"Pending-Removal\"], [\"Pending-Removal\", \"Released\"], [\"Released\", \"Archived\"]], [\"$admin\"]]"

    # Every write of 0.6.0 is role-checked on the server: a service account that holds
    # View-only reads the lists and the reports, and is refused each of the writes. What
    # it sends with them is no more than a row_version: the role is asked for first.
    api POST /users '{"username": "pkgtest-reader", "is_service_account": true, "role": "viewer"}'
    made=$status
    api POST "/users/$(json 'd["user"]["hid"]')/service-tokens" '{"name": "package test"}'
    made="$made $status"
    routes=$(json_field secret)
    # What the writes are tried on: a coverage and a registration made above, and an
    # agreement of the examples.
    api GET "/contracts/$contract/coverage?limit=1"
    mistake=$(json 'd["items"][0]["hid"]')
    api GET "/device-groups/$stack"
    registration=$(json 'd["registrations"][0]["hid"]')
    agreement=$(hid_of agreements 'name:eq:Cisco Enterprise Agreement')
    own_token=$token
    token=$routes
    wanted=""
    for name in agreements contracts "contracts/$contract/terms" "contracts/$contract/coverage" contract-coverage purchase-requests purchase-lines external-systems registrations capacity-lines reports/coverage reports/end-of-life reports/replacements reports/capacity "vendors/$vendor/portfolio"; do
        api GET "/$name"
        made="$made $status"
        wanted="$wanted 200"
    done
    made="$made |"
    routes=0
    for name in "POST /agreements" "PATCH /agreements/$agreement" "POST /agreements/$agreement/renew" "POST /agreements/$agreement/retire" \
        "POST /contracts" "PATCH /contracts/$contract" "POST /contracts/$contract/renew" "POST /contracts/$contract/retire" \
        "POST /contracts/$contract/coverage" "PATCH /contracts/$contract/coverage/$mistake" "DELETE /contracts/$contract/coverage/$mistake" \
        "POST /purchase-requests" "PATCH /purchase-requests/$request" "POST /purchase-requests/$request/lines" \
        "PATCH /purchase-lines/$line" "POST /purchase-lines/$line/receive" \
        "POST /external-systems" "PATCH /external-systems/$watch" "POST /external-systems/$watch/retire" \
        "POST /registrations" "PATCH /registrations/$registration" "DELETE /registrations/$registration" \
        "POST /capacity-lines"; do
        api "${name% *}" "${name#* }" '{"row_version": 1}'
        made="$made $status"
        wanted="$wanted 403"
        routes=$((routes + 1))
    done
    token=$own_token
    api GET "/contracts/$contract/coverage?limit=1"
    made="$made | $(json 'd["items"][0]["hid"] == "'"$mistake"'"')"
    api GET "/device-groups/$stack"
    made="$made $(json 'sum(x["hid"] == "'"$registration"'" for x in d["registrations"])')"
    api GET "/contracts/$contract"
    expect "pkg a service account that holds View-only reads the agreements, the contracts, a contract's terms and coverage, the purchase requests and lines, the external systems, the registrations, the capacity lines, the four reports and the portfolio of a vendor, and is refused every write of them, $routes routes: to make, change, renew, retire, cover, end or remove a coverage, receive, register and remove a registration; the coverage and the registration it tried to remove are there, and the contract is as it was" \
        "$made $status $(json '[d["number"], d["record_status"], d["row_version"]]')" \
        "201 201${wanted/ 403/ | 403} | true 1 200 [\"PKG-CON-0001\", \"active\", 1]"

    # Every record of the new kinds, the examples' and these, exported and imported
    # back, what is retired with them: so that the coverage of a retired contract is
    # among it in every pass, a third contract is made, covers the switch that had no
    # cover, and is retired.
    api POST /contracts "{\"number\": \"PKG-CON-0003\", \"vendor_hid\": \"$vendor\", \"starts_on\": \"$last_year\", \"ends_on\": \"$next_year\"}"
    made=$status
    other=$(json_field hid)
    api POST "/contracts/$other/coverage" "{\"items\": [{\"item_hid\": \"$bare\"}]}"
    made="$made $status"
    api POST "/contracts/$other/retire" '{"row_version": 1}'
    made="$made $status $(json_field record_status)"
    api GET "/items/$bare"
    expect "pkg a third contract is made, covers the switch that had no cover, and is retired: a retired contract covers nothing, and its coverage is on record" \
        "$made $(json '[d["covered"], [[c["contract"]["number"], c["contract"]["record_status"], c["in_force"]] for c in d["coverage"]]]')" \
        '201 201 200 retired [false, [["PKG-CON-0003", "retired", false]]]'
    for entity in agreements contracts contract_coverage purchase_requests purchase_lines external_systems registrations capacity_lines item_replacements; do
        api POST /exports "{\"entity\": \"$entity\", \"format\": \"csv\", \"own_values\": true, \"include_archived\": true, \"include_drafts\": true}"
        cp "$work/body" "$work/back-$entity.csv"
        rows=$(table 'len(rows)' "$work/back-$entity.csv")
        send "/imports/preview?entity=$entity&file_name=$entity.csv" "$work/back-$entity.csv"
        made="$status $(job_counts)"
        api POST /exports "{\"entity\": \"$entity\", \"format\": \"json\", \"own_values\": true, \"include_archived\": true, \"include_drafts\": true}"
        cp "$work/body" "$work/back-$entity.json"
        send "/imports/preview?file_name=$entity.json" "$work/back-$entity.json" application/json
        expect "pkg an export of every record of $entity ($rows rows), the retired and what is under a retired contract among them, is imported back as it is, as CSV and as JSON: every row finds its record, unchanged" \
            "$made $status $(job_counts)" \
            "201 [\"previewed\", $rows, 0, 0, $rows, 0] 201 [\"previewed\", $rows, 0, 0, $rows, 0]"
    done
    api POST /exports '{"entity": "items", "format": "csv", "own_values": true, "filter": "serial_number:glob:PKG0000V02*", "sort": ["serial_number"]}'
    cp "$work/body" "$work/back-arrived.csv"
    send "/imports/preview?entity=items&file_name=arrived.csv" "$work/back-arrived.csv"
    expect "pkg and an export of the six items that arrived, with their own values, names in purchase_line the line each arrived on; it is imported back unchanged" \
        "$(table '["purchase_line" in head, sorted({r["purchase_line"] for r in rows})]' "$work/back-arrived.csv") $status $(job_counts)" \
        '[true, ["PKG-REQ-0001/1"]] 201 ["previewed", 6, 0, 0, 6, 0]'
}

# multiplied_and_seen: two records of 0.7.0 that the examples do not hold, made beside
# them for hirdir admin reset to clear with them: a line that multiplies the network
# engineers of the examples (D-188), which is a target of a capacity line, and the
# renewal alert as this Admin has seen it (D-179).
multiplied_and_seen() {
    local engineers before made
    api GET '/capacity-lines?limit=1000'
    engineers=$(json '[l["hid"] for l in d["items"] if l["name"] == "Network engineer"][0]')
    api GET /reports/capacity
    before=$(json 'd["active"]["supply"]')
    api POST /capacity-lines "{\"side\": \"supply\", \"category\": \"tools\", \"name\": \"Package Test Automation\", \"effect\": \"multiply\", \"factor\": \"1.5\", \"applies_to\": [\"$engineers\"]}"
    made=$status
    api GET /reports/capacity
    expect "pkg a line that multiplies the three network engineers of the examples by one and a half, for every position, counts 1.5 units more under tools, and the capacity report names it with the line it works on" \
        "$made $status $(python3 -c 'import sys; from decimal import Decimal; print(Decimal(sys.argv[2]) - Decimal(sys.argv[1]))' "$before" "$(json 'd["active"]["supply"]')") $(json '[[m["name"], m["share"], m["units"], [a["name"] for a in m["applies_to"]]] for m in d["active"]["multiplying_lines"]]')" \
        '201 200 1.5 [["Package Test Automation", "1", "1.5", ["Network engineer"]]]'
    api GET /renewals/alert
    api POST /renewals/alert/seen "{\"version\": \"$(json_field version)\"}"
    made=$status
    api GET /renewals/alert
    expect "pkg the renewal alert, once this Admin has seen it, is not shown to them again" "$made $status $(json_field show)" "200 200 false"
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
    apply_job "/imports/$hid/apply"
    expect "pkg applied, it creates the 3 items" "$status $(job_counts)" '202 ["applied", 3, 3, 0, 0, 0]'
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
    apply_job "/imports/$hid/apply"
    expect "pkg a file with ipv4 and ipv6 columns and what was observed of each: both rows update their items" \
        "$status $(job_counts)" '202 ["applied", 2, 0, 2, 0, 0]'
    authorized GET "$prefix/api/v1/items" --get --data-urlencode 'filter=hostname:glob:pkgtest-first-*' --data-urlencode 'sort=hostname'
    send "/imports/preview?entity=items&file_name=second.csv" "$work/second.csv"
    expect "pkg that file a second time, which states again what was observed and gives no moment, changes nothing: both rows are unchanged" \
        "$status $(job_counts)" '201 ["previewed", 2, 0, 0, 2, 0]'
    authorized GET "$prefix/api/v1/items" --get --data-urlencode 'filter=hostname:glob:pkgtest-first-*' --data-urlencode 'sort=hostname'
    expect "pkg an item has a primary management address of each family now, and what was observed of it, with a health of good" \
        "$status $(json '[[i["hostname"], sorted([a["family"], a["address"], a["is_primary"]] for a in i["addresses"]), i["observed_status"], i["health"]["value"]] for i in d["items"][1:]]')" \
        '200 [["pkgtest-first-02", [[4, "198.51.100.102", true], [6, "2001:db8:0:51::102", true]], "online", "good"], ["pkgtest-first-03", [[4, "198.51.100.103", true], [6, "2001:db8:0:51::103", true]], "present", "good"]]'

    # A file that knows its devices by host name alone, with what another tool says of
    # each, finds the items that have those host names, serial numbers and all.
    printf '%s\n' 'hostname,observed_status' 'pkgtest-stack-01,online' 'pkgtest-stack-04,unreachable' >"$work/seen.csv"
    authorized GET "$prefix/api/v1/items" --get --data-urlencode 'filter=hostname:in:pkgtest-stack-01,pkgtest-stack-04' --data-urlencode 'sort=hostname'
    expect "pkg two switches made above have a host name and a serial number each, and nothing is observed of them" \
        "$status $(json '[[i["hostname"], i["serial_number"], i["observed_status"]] for i in d["items"]]')" \
        '200 [["pkgtest-stack-01", "PKG0000S001", null], ["pkgtest-stack-04", "PKG0000S004", null]]'
    send "/imports/preview?entity=items&file_name=seen.csv" "$work/seen.csv"
    expect "pkg a file of hostname and observed_status finds each by its host name, though it has a serial number that the file does not give: 2 rows to update, none to create" \
        "$status $(job_counts)" '201 ["previewed", 2, 0, 2, 0, 0]'
    hid=$(json 'd["job"]["hid"]')
    apply_job "/imports/$hid/apply"
    expect "pkg applied, it updates the 2" "$status $(job_counts)" '202 ["applied", 2, 0, 2, 0, 0]'
    authorized GET "$prefix/api/v1/items" --get --data-urlencode 'filter=hostname:in:pkgtest-stack-01,pkgtest-stack-04' --data-urlencode 'sort=hostname'
    expect "pkg there is still one item of each host name, the one with the serial number, and it has what was observed and the health that follows: no second item was made" \
        "$status $(json '[[i["hostname"], i["serial_number"], i["observed_status"], i["health"]["value"]] for i in d["items"]]')" \
        '200 [["pkgtest-stack-01", "PKG0000S001", "online", "good"], ["pkgtest-stack-04", "PKG0000S004", "unreachable", "failed"]]'
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
    expect "pkg the migrations loaded the default choices of all eleven lists, contact_role, location_kind, capacity_category, circuit_type, carrier_role and reference_kind among them" \
        "$status $(json '" ".join(sorted({c["list"] for c in d}))')" "200 capacity_category carrier_role catalog_function catalog_type circuit_type contact_role item_condition location_kind reference_kind replacement_reason state_reason"
    expect "pkg the circuit_type list offers at least its seven defaults, and the carrier_role list its four" \
        "$(json '[sorted(set(w.split()) - {c["value"] for c in d if c["list"] == k}) for k, w in (("circuit_type", "internet mpls point_to_point dark_fiber wavelength voice other"), ("carrier_role", "local_exchange cross_connect last_mile other"))]')" \
        '[[], []]'
    expect "pkg the replacement_reason list offers at least its five defaults" \
        "$(json 'sorted({"rma", "refresh", "project", "upgrade", "other"} - {c["value"] for c in d if c["list"] == "replacement_reason"})')" "[]"
    expect "pkg and the item_condition list at least its six, from untested to dead" \
        "$(json 'sorted({"untested", "good", "degraded", "suspect", "failed", "dead"} - {c["value"] for c in d if c["list"] == "item_condition"})')" "[]"
    expect "pkg the contact_role list at least its five, and the location_kind list its six" \
        "$(json 'sorted({"shipping", "technical", "federal", "operational", "escalation"} - {c["value"] for c in d if c["list"] == "contact_role"}) + sorted({"building", "floor", "room", "rack", "warehouse", "other"} - {c["value"] for c in d if c["list"] == "location_kind"})')" "[]"
    expect "pkg and the capacity_category list its six: staff, professional_services, smart_hands, tools, services and other_work" \
        "$(json 'sorted({"staff", "professional_services", "smart_hands", "tools", "services", "other_work"} - {c["value"] for c in d if c["list"] == "capacity_category"})')" "[]"
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

# ---- the capacity balance -------------------------------------------------------------------

# Scenarios S39 and S40 of docs/build-plan.md, through nginx under the prefix. The
# capacity report is of the whole installation, so they are worked here, where the
# inventory holds the four items of inventory() and no capacity line: the examples and
# what was made beside them are gone again. The worked example of docs/data-model.md
# is against a support weight of 2,400: one more item is given the support weight that
# brings the inventory to that. The lines carry the names of the worked example behind
# a word of the test's own, so that nothing else can have taken them. What is made
# here is retired again, and the inventory and the report are left as they were.
capacity_balance() {
    section "the capacity balance through nginx under $prefix/"
    local made wanted item weight side category name quantity units lines=() partner="" hid

    api GET /reports/capacity
    expect "pkg with no capacity line entered, GET $prefix/api/v1/reports/capacity has no supply and no other work: the demand is that of the inventory alone, and the balance is short by it" \
        "$status $(json '[d["active"]["supply"], d["active"]["other_demand"], d["active"]["demand"] == d["active"]["infrastructure_demand"], float(d["active"]["balance"]) == -float(d["active"]["demand"]), sum(c["lines"] for c in d["active"]["by_category"])]')" \
        '200 ["0", "0", true, true, 0]'
    weight=$(json 'format(2400 - __import__("decimal").Decimal(d["active"]["support_weight"]), "f")')
    api POST /items "{\"catalog_entry_hid\": \"$(hid_of catalog-entries 'pid:eq:C9500-24Y4C')\", \"serial_number\": \"PKG0000K001\", \"lifecycle_state\": \"Prod\", \"support_weight\": \"$weight\"}"
    made=$status
    item=$(json_field hid)
    wanted=201
    while IFS='|' read -r side category name quantity units; do
        api POST /capacity-lines "{\"side\": \"$side\", \"category\": \"$category\", \"name\": \"pkgtest $name\", \"quantity\": \"$quantity\", \"units_each\": \"$units\"}"
        made="$made $status"
        wanted="$wanted 201"
        lines+=("$(json_field hid)")
        if [ "$category" = professional_services ]; then partner=$(json_field hid); fi
    done <<'LINES'
demand|other_work|Site consolidation project|1|1.5
demand|other_work|Organization transition|1|0.5
supply|staff|Junior network engineer|2|0.6
supply|staff|Network engineer|3|1.0
supply|staff|Senior network engineer|1|1.8
supply|professional_services|Escalation partner|1|1.0
supply|smart_hands|Colocation smart hands|1|0.5
supply|tools|Automation and tooling|1|1.5
LINES
    api GET /reports/capacity
    expect "S39 an item is given the support weight that brings the inventory to 2,400, $weight, and the eight active lines of the worked example are entered: GET $prefix/api/v1/reports/capacity gives 8 units of infrastructure demand at 300 to the unit and 2 of other work, a demand of 10, a supply of 9 by category, a balance of -1 and a coverage of 90%, two thirds of the supply the team's own six units" \
        "$made $status $(json '[d["weight_per_resource_unit"]] + [d["active"][k] for k in ("support_weight", "infrastructure_demand", "other_demand", "demand", "supply", "balance", "coverage_pct", "own_units", "outside_units", "own_share_pct")] + [{c["category"]: c["units"] for c in d["active"]["by_category"] if c["lines"]}]')" \
        "$wanted 200 [\"300\", \"2400\", \"8\", \"2\", \"10\", \"9\", \"-1\", \"90\", \"6\", \"3\", \"66.67\", {\"professional_services\": \"1\", \"smart_hands\": \"0.5\", \"staff\": \"6\", \"tools\": \"1.5\"}]"

    api POST /capacity-lines '{"side": "supply", "category": "services", "name": "pkgtest AI assistant", "quantity": "1", "units_each": "1.0", "record_status": "draft"}'
    made=$status
    lines+=("$(json_field hid)")
    api GET /reports/capacity
    expect "S40 the services line is added as a draft: without the drafts the supply is 9 and the balance -1 as before, and with them the supply is 10, the balance zero and the coverage 100%, against the same support weight" \
        "$made $status $(json '[d["active"]["supply"], d["active"]["balance"]] + [d["with_drafts"][k] for k in ("support_weight", "supply", "balance", "coverage_pct")]')" \
        '201 200 ["9", "-1", "2400", "10", "0", "100"]'
    api PATCH "/capacity-lines/$partner" "{\"row_version\": 1, \"ends_on\": \"$(day_from_today -30)\"}"
    made="$status $(json_field in_date)"
    api GET /reports/capacity
    expect "S40 the professional services line is given a last day that is past: it drops out of the supply in both views, which is 8 with a balance of -2, and 9 with a balance of -1 with the drafts, and its category supplies nothing in either" \
        "$made $status $(json '[d[v][k] for v in ("active", "with_drafts") for k in ("supply", "balance")] + [c["units"] for v in ("active", "with_drafts") for c in d[v]["by_category"] if c["category"] == "professional_services"]')" \
        '200 false 200 ["8", "-2", "9", "-1", "0", "0"]'

    made=""
    wanted=""
    for hid in "${lines[@]}"; do
        api GET "/capacity-lines/$hid"
        api POST "/capacity-lines/$hid/retire" "{\"row_version\": $(json_field row_version)}"
        made="$made$status "
        wanted="${wanted}200 "
    done
    api POST "/items/$item/retire" '{"row_version": 1}'
    made="$made$status"
    api GET /reports/capacity
    expect "pkg the nine lines and the item are retired again: the capacity report has no supply and no other work, as before" \
        "$made $status $(json '[d["active"]["supply"], d["active"]["other_demand"], d["with_drafts"]["supply"], float(d["active"]["support_weight"]) == 2400 - float("'"$weight"'")]')" \
        "${wanted}200 200 [\"0\", \"0\", \"0\", true]"
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
    # From 0.7.0 one server runs on one state directory, which it holds a lock on (D-185),
    # so that a second could not take for stopped an import that the first is applying.
    if inside test -e /var/lib/hirdir/server.lock; then
        code=0
        inside timeout 30 runuser -u hirdir -- /opt/hirdir/venv/bin/hirdir admin serve >"$work/second.log" 2>&1 || code=$?
        expect "pkg the service holds its lock on the state directory, /var/lib/hirdir/server.lock, which the hirdir user made; a second server started on it is refused, and says so, and the one that runs goes on" \
            "$(inside stat -c '%U %a' /var/lib/hirdir/server.lock 2>&1) $code $(grep -c 'another hirdir server is running on /var/lib/hirdir: stop it first' "$work/second.log") $(inside systemctl is-active hirdir.service 2>&1)" \
            "hirdir 640 1 1 active"
    fi
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
    upgrade) title="upgrade from hirdir $previous_version to $version, with $crossing" ;;
    failed-upgrade)
        title="an upgrade from hirdir $previous_version to $version whose migration fails"
        if ! migrating; then title="an upgrade from hirdir $previous_version to $version and back, with no migration that could fail"; fi
        ;;
    *) title="fresh install of hirdir $version" ;;
esac
printf '\n==== package-test, the %s pass: %s\n' "$mode" "$title"
if [ "$mode" != fresh ]; then load_particulars; fi

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
    if [ "$alone" = 1 ]; then
        skip "pkg everything the fresh pass does, on the upgraded installation: --upgrade-alone asks for the upgrade alone, so this run stops where the upgrade pass goes on to it, and is not the release check"
    else
        installed
        setup
        through_nginx
        files
        reference_files
        inventory
        capacity_balance
        reinstall
        state
        if [ "$e2e" = 1 ]; then browser_scenarios; fi
        another_prefix
        own_site
    fi
    cookies=$(grep -ci '^set-cookie:' "$work/headers.all" || true)
    expect "S02 none of the $responses responses of this pass set a cookie" "$cookies" 0
    if [ "$alone" != 1 ]; then purge; fi
fi

# ---- summary --------------------------------------------------------------------------

section "summary of the $mode pass"
if [ "$mode" != failed-upgrade ] && [ "$alone" != 1 ]; then
    echo "package-test: $(basename "$deb"), web UI in the package: $web_ui"
fi
echo "package-test: $mode: $passes PASS, $failures FAIL, $skips SKIP, in $SECONDS s ($title)"
if [ "$failures" -gt 0 ]; then
    echo "package-test: $failures check(s) FAILED in the $mode pass"
    echo "--- journal of hirdir.service"
    inside journalctl --unit hirdir.service --no-pager --lines 30 2>&1 || true
    echo "--- /var/log/nginx/error.log"
    inside tail -n 20 /var/log/nginx/error.log 2>&1 || true
    exit 1
fi
echo "package-test: all checks of the $mode pass passed"
