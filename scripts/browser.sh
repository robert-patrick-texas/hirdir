#!/bin/bash
# The browser scenarios of web/e2e on this host, in one pass that reports every failure.
#
#   scripts/browser.sh [--built] [--port N] [spec ...]
#   scripts/browser.sh --since <commit> [--built] [--port N]
#   scripts/browser.sh --last-failed [--built]
#
# It makes a fresh scratch inventory in dev-data/browser/ (git-ignored), with the Admin of
# the environment, e2e-admin, and an access code of its own; builds the web UI, unless
# --built says the build is current; serves it with `hirdir admin serve --dev` on a free
# port, never 8715, with `hirdir admin work` beside it on the same inventory, the two
# processes that the package runs (P-267); and stops that server, by its port, and the
# second process with it, when it ends or is interrupted.
# The examples are not loaded: every spec file makes what it needs, as it does on the
# fresh install of the package test.
#
# Then it runs the ordinary project, and after it each project that runs alone, in the
# order of playwright.config.ts, whatever failed before (`--no-deps`), and ends with one
# list of every scenario that failed, by project, file and title, and a non-zero exit if
# anything failed.
#
#   spec ...         only these spec files, as `geography` or `web/e2e/geography.spec.ts`;
#                    a project that runs alone is run only when its file is among them
#   --since <commit> only the spec files that differ from that commit, in the tree as it
#                    is (`git diff --name-only <commit> -- web/e2e`, and new files); a
#                    helper module that differs takes in the files that import it, and
#                    support.ts or playwright.config.ts every file
#   --last-failed    only what failed, or did not run after a failure, in the last run,
#                    on the same inventory and port, each project with Playwright's own
#                    --last-failed; nothing is made afresh
#   --built          the web UI in src/hirdir/static is current: it is not built again
#   --plan           say which projects and spec files would be run, and run nothing
#   --port N         serve on this port, which must be free
#
# How many files run at once is E2E_WORKERS if it is set, or one fewer than what
# scripts/test_load.py says of the host, the server needing a processor too; and a busy
# host is waited for first,
# ten minutes at the most, as `make acceptance` does (HIRDIR_TEST_WAIT=0 does not wait).
# Temporary files go to TMPDIR, by default dev-data/pytmp of this tree.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
web=$root/web
state=$root/dev-data/browser
admin=e2e-admin
self=scripts/browser.sh

usage() {
    echo "usage: $self [--built] [--plan] [--port N] [--since <commit> | --last-failed | spec ...]" >&2
    exit 2
}

die() {
    echo "browser: $*" >&2
    exit 1
}

build=1
only_plan=0
again=0
since=
port=
specs=()
while [ $# -gt 0 ]; do
    case $1 in
        --built) build=0 ;;
        --plan) only_plan=1 ;;
        --last-failed) again=1 ;;
        --since) [ $# -ge 2 ] || usage; since=$2; shift ;;
        --since=*) since=${1#--since=} ;;
        --port) [ $# -ge 2 ] || usage; port=$2; shift ;;
        --port=*) port=${1#--port=} ;;
        -h | --help) sed -n '2,/^set -euo/{/^set -euo/d;s/^# \{0,1\}//;p}' "$0"; exit 0 ;;
        -*) usage ;;
        *) specs+=("$1") ;;
    esac
    shift
done
if [ "$again" = 1 ] && { [ -n "$since" ] || [ ${#specs[@]} -gt 0 ]; }; then
    die "--last-failed reruns the last run as it was: it takes no spec file and no --since"
fi
if [ -n "$since" ] && [ ${#specs[@]} -gt 0 ]; then
    die "--since chooses the spec files itself: name none beside it"
fi
[ -x "$web/node_modules/.bin/playwright" ] || die "run 'npm --prefix web ci' first"

export TMPDIR=${TMPDIR:-$root/dev-data/pytmp}
mkdir -p "$TMPDIR" "$root/dev-data"

# One run at a time in a tree: the next would empty the inventory under this one.
exec 9>"$root/dev-data/browser.lock"
flock -n 9 || die "another run of $self is going on in this tree"

# ---- which spec files ------------------------------------------------------------------

# A spec file named as `geography`, `geography.spec.ts` or `web/e2e/geography.spec.ts`.
spec_name() {
    local name=${1##*/}
    case $name in
        *.spec.ts) ;;
        *.*) die "$1 is not a spec file" ;;
        *) name=$name.spec.ts ;;
    esac
    [ -f "$web/e2e/$name" ] || die "there is no web/e2e/$name"
    printf '%s\n' "$name"
}

# The spec files that differ from a commit, with those that import a helper that differs.
# Prints nothing for every file, and "none" when there is none.
changed_specs() {
    local path name helper file every=0
    local -a found=() helpers=()
    git -C "$root" rev-parse --verify --quiet "$1^{commit}" >/dev/null || die "$1 is not a commit"
    while IFS= read -r path; do
        name=${path##*/}
        case $path in
            web/playwright.config.ts | web/e2e/support.ts) every=1 ;;
            web/e2e/*.spec.ts) [ -f "$root/$path" ] && found+=("$name") ;;
            web/e2e/*.ts) helpers+=("${name%.ts}") ;;
        esac
    done < <({
        git -C "$root" diff --name-only "$1" -- web/e2e web/playwright.config.ts
        git -C "$root" ls-files --others --exclude-standard -- web/e2e
    } | sort -u)
    # A helper is taken in by every file that imports it, and a helper that imports it.
    while [ ${#helpers[@]} -gt 0 ]; do
        helper=${helpers[0]}
        helpers=("${helpers[@]:1}")
        while IFS= read -r file; do
            name=${file##*/}
            case $name in
                *.spec.ts) found+=("$name") ;;
                *) helpers+=("${name%.ts}") ;;
            esac
        done < <(grep -l -F "from \"./$helper\"" "$web"/e2e/*.ts || true)
    done
    if [ "$every" = 1 ]; then return 0; fi
    if [ ${#found[@]} -eq 0 ]; then echo none; return 0; fi
    printf '%s\n' "${found[@]}" | sort -u
}

chosen=()
if [ -n "$since" ]; then
    mapfile -t chosen < <(changed_specs "$since")
    if [ "${chosen[*]}" = none ]; then
        echo "browser: no spec file differs from $since: nothing to run"
        exit 0
    fi
else
    for spec in "${specs[@]}"; do chosen+=("$(spec_name "$spec")"); done
fi

# ---- the inventory and its port --------------------------------------------------------

listening() {
    ss -ltnH "sport = :$1" 2>/dev/null | grep -q .
}

free_port() {
    python3 -c '
import socket
with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    print(probe.getsockname()[1])'
}

if [ "$again" = 1 ]; then
    [ -f "$state/.scratch" ] && [ -f "$state/plan.tsv" ] || die "no earlier run to take up: run $self first"
    port=$(cat "$state/port")
elif [ -z "$port" ]; then
    port=$(free_port)
fi
[[ $port =~ ^[1-9][0-9]*$ ]] || die "--port takes a number"
[ "$port" != 8715 ] || die "port 8715 is the development server's: choose another"
if listening "$port"; then die "something listens on 127.0.0.1:$port already"; fi

hirdir_admin() {
    (cd "$state" && HIRDIR_CONFIG=$state/config.toml uv run --project "$root" hirdir admin "$@")
}

fresh_inventory() {
    if [ -d "$state" ]; then
        [ -f "$state/.scratch" ] || die "$state was not made by $self: move it out of the way"
        rm -rf "$state"
    fi
    mkdir -p "$state/runs" "$state/last"
    touch "$state/.scratch"
    printf '[server]\nlisten = "127.0.0.1:%s"\nstate_dir = "."\n' "$port" >"$state/config.toml"
    echo "$port" >"$state/port"
    (umask 077 && od -An -tx1 -N16 /dev/urandom | tr -d ' \n' >"$state/access-code")
    if ! { hirdir_admin migrate &&
        hirdir_admin create-user "$admin" --role admin --access-code "$(cat "$state/access-code")"; } \
        >"$state/setup.log" 2>&1; then
        tail -n 20 "$state/setup.log" >&2
        die "the inventory was not made: see $state/setup.log"
    fi
}

# ---- the server ------------------------------------------------------------------------

server=
worker=
child=

# The processes that listen on the port and were started in the inventory's folder: the
# server this script started, and nothing of anybody else.
ours_on_port() {
    local pid
    for pid in $(ss -ltnpH "sport = :$port" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u); do
        if [ "$(readlink "/proc/$pid/cwd" 2>/dev/null)" = "$state" ]; then echo "$pid"; fi
    done
}

# The processes of the background work that were started in the inventory's folder: the
# one this script started, and nothing of anybody else.
ours_working() {
    local pid
    for pid in $(pgrep -f 'hirdir admin work' 2>/dev/null); do
        if [ "$(readlink "/proc/$pid/cwd" 2>/dev/null)" = "$state" ]; then echo "$pid"; fi
    done
}

# It stops after the batch it is applying, which it is given a minute for.
stop_worker() {
    local -a pids
    [ -n "$worker" ] || return 0
    mapfile -t pids < <(ours_working)
    if [ ${#pids[@]} -gt 0 ]; then
        kill -TERM "${pids[@]}" 2>/dev/null || true
        for _ in $(seq 1 140); do
            [ -n "$(ours_working)" ] || break
            sleep 0.5
        done
        mapfile -t pids < <(ours_working)
        if [ ${#pids[@]} -gt 0 ]; then kill -KILL "${pids[@]}" 2>/dev/null || true; fi
    fi
    kill -TERM "$worker" 2>/dev/null || true
    wait "$worker" 2>/dev/null || true
    worker=
}

stop_server() {
    local -a pids
    stop_worker
    [ -n "$server" ] || return 0
    mapfile -t pids < <(ours_on_port)
    if [ ${#pids[@]} -gt 0 ]; then
        kill -TERM "${pids[@]}" 2>/dev/null || true
        for _ in $(seq 1 40); do
            listening "$port" || break
            sleep 0.5
        done
        mapfile -t pids < <(ours_on_port)
        if [ ${#pids[@]} -gt 0 ]; then kill -KILL "${pids[@]}" 2>/dev/null || true; fi
    fi
    kill -TERM "$server" 2>/dev/null || true
    wait "$server" 2>/dev/null || true
    server=
    echo "browser: the server on 127.0.0.1:$port and the process of the background work are stopped; the inventory is kept in $state"
}

interrupted() {
    echo "browser: interrupted" >&2
    if [ -n "$child" ]; then
        kill -TERM "$child" 2>/dev/null || true
        wait "$child" 2>/dev/null || true
    fi
    exit 130
}

trap 'stop_server' EXIT
trap 'interrupted' INT TERM

serve() {
    # The server does not hold the lock of the run: fd 9 is closed for it.
    (cd "$state" && HIRDIR_CONFIG=$state/config.toml exec uv run --project "$root" hirdir admin serve --dev) \
        >>"$state/serve.log" 2>&1 9>&- &
    server=$!
    for _ in $(seq 1 120); do
        if curl --silent --fail --output /dev/null "http://127.0.0.1:$port/api/v1/health/ready"; then
            return 0
        fi
        if ! kill -0 "$server" 2>/dev/null; then
            server=
            tail -n 20 "$state/serve.log" >&2
            die "the server stopped as it started: see $state/serve.log"
        fi
        sleep 0.5
    done
    die "the server on 127.0.0.1:$port did not answer in a minute: see $state/serve.log"
}

# The second process of the service, started once the server answers, which has migrated
# the inventory by then. The scenarios begin when it says that it is at work: what it
# does as it starts, the record of a week that has none, is done by then.
work() {
    : >"$state/work.log"
    (cd "$state" && HIRDIR_CONFIG=$state/config.toml exec uv run --project "$root" hirdir admin work) \
        >>"$state/work.log" 2>&1 9>&- &
    worker=$!
    for _ in $(seq 1 120); do
        if grep -q 'is under way' "$state/work.log"; then return 0; fi
        if ! kill -0 "$worker" 2>/dev/null; then
            worker=
            tail -n 20 "$state/work.log" >&2
            die "the process of the background work stopped as it started: see $state/work.log"
        fi
        sleep 0.5
    done
    die "the process of the background work was not under way in a minute: see $state/work.log"
}

# ---- the runs --------------------------------------------------------------------------

codes=()

# run SLUG PROJECTS FILES [--last-failed]: one run of Playwright, with its own report,
# its own output folder and its own record of what failed.
run() {
    local name=$1 names=$2 files=$3 status=0
    local -a args=(test --no-deps "--reporter=list,json" "--output=test-results/$name"
        "--last-failed-file=$state/last/$name.json")
    local -a projects given
    IFS='|' read -ra projects <<<"$names"
    for project in "${projects[@]}"; do args+=("--project=$project"); done
    if [ "${4:-}" = --last-failed ]; then args+=(--last-failed); fi
    read -ra given <<<"$files"
    args+=("${given[@]}")
    rm -f "$state/runs/$name.json"
    printf '\n==== browser: %s%s\n' "${names//|/, }" "${4:+, what failed last time}${files:+: $files}"
    (cd "$web" && exec env E2E_BASE_URL="http://127.0.0.1:$port/" E2E_USERNAME="$admin" \
        E2E_ACCESS_CODE="$(cat "$state/access-code")" E2E_WORKERS="$workers" \
        PLAYWRIGHT_JSON_OUTPUT_FILE="$state/runs/$name.json" \
        node_modules/.bin/playwright "${args[@]}") 9>&- &
    child=$!
    wait "$child" || status=$?
    child=
    codes+=("$name=$status")
}

started=$(date +%s)
if [ "$again" = 1 ]; then
    plan=
    while IFS=$'\t' read -r name names _; do
        left=$(cd "$web" && node scripts/e2e-plan.mjs left "$state/last/$name.json")
        if [ "$left" != 0 ]; then plan+="$name"$'\t'"$names"$'\t'$'\n'; fi
    done <"$state/plan.tsv"
    [ -n "$plan" ] || { echo "browser: nothing failed in the last run: nothing to run again"; exit 0; }
else
    plan=$(cd "$web" && node scripts/e2e-plan.mjs plan "${chosen[@]}") || die "the runs could not be planned"
fi
if [ "$only_plan" = 1 ]; then
    echo "browser: the runs, in order (slug, projects, spec files; none is every file of the project):"
    printf '%s\n' "$plan"
    exit 0
fi

# One fewer at once than the host has free: the server that the browsers drive is one
# process, and needs a processor of its own (docs/architecture.md, "How long the tests
# take").
workers=$(cd "$root" && uv run python scripts/test_load.py --wait)
if [ "$workers" -gt 1 ]; then workers=$((workers - 1)); fi
if [[ ${E2E_WORKERS:-} =~ ^[1-9][0-9]*$ ]]; then workers=$E2E_WORKERS; fi

if [ "$build" = 1 ]; then
    echo "browser: building the web UI"
    npm --prefix "$web" run build >"$root/dev-data/browser-build.log" 2>&1 ||
        { tail -n 30 "$root/dev-data/browser-build.log" >&2; die "the web UI did not build"; }
fi
if [ "$again" = 0 ]; then
    fresh_inventory
    printf '%s\n' "$plan" >"$state/plan.tsv"
fi
serve
work
echo "browser: inventory $state, served on http://127.0.0.1:$port/ with the background work beside it, $workers at once"

while IFS=$'\t' read -r name names files; do
    [ -n "$name" ] || continue
    if [ "$again" = 1 ]; then run "$name" "$names" "" --last-failed; else run "$name" "$names" "$files"; fi
done <<<"$plan"

stop_server
printf '\n==== browser: every run, in %s min\n' "$(( ($(date +%s) - started + 30) / 60 ))"
status=0
(cd "$web" && node scripts/e2e-plan.mjs summary "$state/runs" "${codes[@]}") | tee "$state/summary.txt" ||
    status=$?
if [ "$status" != 0 ]; then
    echo "a fix is checked with: $self --last-failed --built"
    false
fi
