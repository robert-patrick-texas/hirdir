# shellcheck shell=bash
# shellcheck disable=SC2034,SC2154  # Read by packaging/package-test.sh, whose names these are.
#
# Migration 0015, which came with hirdir 0.9.11: the long reports worked out ahead by
# the second process and kept in the database (P-275), and worked out again by day
# once nothing has changed for a while (P-276).
#
# packaging/package-test.sh reads this file when the upgrade it tests runs the
# migration, and calls the three functions below: see "what one upgrade alone has"
# there. The previous release is then at revision 0014 or before: its server works the
# four long reports out when it starts and keeps them in its memory, it has no table
# for them and no setting of when they are worked out again.
#
# The migration creates one table, kept_answers, and nothing else: it alters no table,
# changes no row and writes no audit event. That table is the one that the pass whose
# migration fails puts in its way, there being no other.
#
# The table is empty when the migration is done. It does not stay so: the second
# process fills it as it starts, a row to each of the four reports, before anything is
# asked of the new version, and writes the rows again half a minute after any change.
# So what the migration left cannot be read from the installation that was upgraded,
# and is read here from a copy of the backup that the upgrade took, migrated by the
# new version where no service runs on it; and the rows of the installation itself
# are looked at as what the second process wrote, never as something the upgrade
# changed. kept_answers is named in no list of what is compared, being new, and holds
# no record. The table is not in the backup, and what it held is nothing to keep, so
# going back is by the backup, as after any migration, which the pass whose migration
# fails does. docs/install.md says all of it under "From 0.9.10 to 0.9.11", and what is
# said there is what is looked for here.
writes_no_event=yes

# Set by before_0015 when the previous release holds an inventory, for the other two.
ahead_0015=""
# The four routes of the long reports, each for the view its page opens with, by the
# name its row has.
routes_0015="capacity:/reports/capacity coverage:/reports/coverage renewals:/reports/renewals renewal_alert:/renewals/alert"

# migrated_0015 BACKUP: copy a backup of the database of the previous release to a
# directory that no service runs on, bring the copy to the schema of the new version
# with its hirdir admin migrate, as the hirdir user, and print what the migrations
# left, on one line: the revision; the tables that the copy has and the backup had
# not; how many rows kept_answers holds; and how many of the tables that the backup
# had hold other rows now than they did, the audit trail among them, with their names.
# The copy and its directory are removed again.
migrated_0015() {
    inside runuser -u hirdir -- bash -c '
set -e
scratch=$(mktemp -d)
trap "rm -rf \"$scratch\"" EXIT
cp "$1" "$scratch/hirdir.db"
printf "[server]\nstate_dir = \"%s\"\n" "$scratch" >"$scratch/config.toml"
if ! HIRDIR_CONFIG="$scratch/config.toml" /opt/hirdir/venv/bin/hirdir admin migrate >"$scratch/migrate.log" 2>&1; then
    tail -n 3 "$scratch/migrate.log"
    exit 1
fi
/opt/hirdir/python/bin/python3 -I -c "
import sqlite3, sys

before, after = (sqlite3.connect(path) for path in sys.argv[1:3])
tables = lambda held: sorted(name for (name,) in held.execute(\"SELECT name FROM sqlite_master WHERE type = ?\", (\"table\",)))
rows = lambda held, table: sorted(map(repr, held.execute(f\"SELECT * FROM {table}\")))
had = [table for table in tables(before) if table != \"alembic_version\"]
differing = [table for table in had if rows(before, table) != rows(after, table)]
(revision,) = after.execute(\"SELECT version_num FROM alembic_version\").fetchone()
(kept,) = after.execute(\"SELECT count(*) FROM kept_answers\").fetchone()
new = sorted(set(tables(after)) - set(tables(before)))
print(revision, \"new:\", *new, \"| kept_answers:\", kept, \"rows |\", len(had) - len(differing), \"of\", len(had), \"tables as they were\", *differing)
" "$1" "$scratch/hirdir.db"' migrated_0015 "$1" 2>&1 | tail -n 1
}

# What the previous release has of this, and what the upgrade is to leave as it is. The
# migration alters nothing, so there is nothing to make for it to harm: the inventory
# that every upgrade carries is compared whole. What could differ is what the four
# reports say, which the server of the new version gives from a row that another
# process wrote and that is read back from text: each is kept whole here, as the
# previous release answers it, where the upgrade runs this migration alone and no
# other release in between has changed what a report says.
before_0015() {
    local made
    [ -n "$witness_entry" ] || return 0
    ahead_0015=yes

    api GET /settings
    made="$status $(json '[s["key"] for s in d if s["key"] == "reports_ahead_after_seconds"]')"
    api PUT /settings/reports_ahead_after_seconds '{"row_version": 0, "value": 5}'
    case $status in 404 | 405) made="$made none" ;; *) made="$made $status" ;; esac
    expect "pkg $previous_version has no table kept_answers, and no reports_ahead_after_seconds among its settings, which it does not take" \
        "[$(tables_there kept_answers)] $made" "[] 200 [] none"
    if previous_at 0010; then
        api GET /reports/capacity
        api GET /kept-answers
        expect "pkg what $previous_version keeps of the long reports is in the memory of its server alone: GET /kept-answers lists the capacity balance once somebody has asked for it, and says of nothing that it was worked out ahead" \
            "$status $(json '"capacity" in {e["report"] for e in d}') $(json 'sorted({k for e in d for k in e})')" \
            '200 true ["kept_at", "report", "request", "uses"]'
    fi
    if [ "$crossed" = 0015 ] && [ -n "$witness_renewed" ]; then
        witness_answers+=(
            'capacity-whole|/reports/capacity|d|GET /reports/capacity, the capacity balance for the view its page opens with, answers whole what it answered'
            'coverage-whole|/reports/coverage|d|GET /reports/coverage, the coverage report for the view its page opens with, answers whole what it answered'
            'renewals-whole|/reports/renewals|d|GET /reports/renewals, the renewal worklist for the view its page opens with, answers whole what it answered'
            'alert-whole|/renewals/alert|d|GET /renewals/alert, the renewal alert, answers whole what it answered, to the same person'
        )
    fi
}

# What the migration made, and what the second process has made of it since, looked at
# by itself with the new version serving. Nothing has been changed since the service
# started when this runs: the pass has signed in, previewed and read, which leave what
# is kept good.
changed_0015() {
    local when=$1 backup made entry tables
    [ -n "$ahead_0015" ] || return 0

    # What the migration left, where no second process has been: a copy of the backup
    # of this upgrade, migrated by itself. The log of apt is that of the upgrade still.
    backup=$(sed -n 's/^hirdir: the database as it was before this upgrade is kept at //p' "$work/apt.log")
    expect "pkg $when the backup that the upgrade took has no table kept_answers, so going back to $previous_version is by that backup and loses nothing but what is worked out again (${backup:-no backup})" \
        "$(sqlite_value "${backup:-/nonexistent}" "SELECT count(*) FROM sqlite_master WHERE name = 'kept_answers'")" 0
    made=$(migrated_0015 "${backup:-/nonexistent}" || true)
    if [ "$crossed" = 0015 ]; then
        tables=$(sqlite_value "${backup:-/nonexistent}" "SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name <> 'alembic_version'" || true)
        expect "pkg $when a copy of that backup, migrated by $version where no service runs on it, is at revision $head with one table more, kept_answers, which is empty: the migration puts nothing into it; and every other table holds the rows it held, the audit trail among them, so the migration changes no row and writes no event" \
            "$made" "$head new: kept_answers | kept_answers: 0 rows | $tables of $tables tables as they were"
    else
        expect "pkg $when a copy of that backup, migrated by $version where no service runs on it, is at revision $head, and its kept_answers is empty: the migration puts nothing into it" \
            "$(printf '%s\n' "$made" | sed 's/^\([^ ]*\) new:.*| \(kept_answers: [0-9]* rows\) |.*$/\1 \2/')" \
            "$head kept_answers: 0 rows"
    fi

    # What the second process made of it, with nobody asking: it started with the
    # service, a moment after the upgrade.
    if wait_ahead 90; then
        pass "pkg $when the second process, started by the upgrade, has worked out the four long reports by itself and filled the table: GET /kept-answers lists the capacity balance, the coverage report, the renewal worklist and the summary of the renewal alert, each as worked out ahead"
    else
        fail "pkg $when the second process, started by the upgrade, has worked out the four long reports by itself and filled the table: GET /kept-answers lists the capacity balance, the coverage report, the renewal worklist and the summary of the renewal alert, each as worked out ahead (got $status, and worked out ahead: $(ahead_times))"
    fi
    expect "pkg $when kept_answers holds a row to each of the four and no other, and each names $version as the version that worked it out" \
        "$(sqlite_text 'SELECT report, version FROM kept_answers ORDER BY report' | xargs)" \
        "capacity $version coverage $version renewal_alert $version renewals $version"

    # The server gives each from its row: asked for the view its page opens with, it
    # answers, and what it then lists as given is the row, at the moment the second
    # process worked it out, and nothing that it worked out itself.
    made=""
    for entry in $routes_0015; do
        api GET "${entry#*:}"
        made="$made$status "
    done
    api GET /kept-answers
    expect "pkg $when the server, asked for each of the four for the view its page opens with, gives the row of the second process and works nothing out itself: GET /kept-answers lists the four as given, each as worked out ahead, at the moment its row was worked out" \
        "$made$status $(json 'sorted([e["report"], e["uses"] >= 1] for e in d if e["ahead"])') $(ahead_times)" \
        "200 200 200 200 200 [[\"capacity\", true], [\"coverage\", true], [\"renewal_alert\", true], [\"renewals\", true]] $(ahead_rows)"

    # The setting that came with it is at its default.
    api GET /settings
    expect "pkg $when reports_ahead_after_seconds is at its default, 30, which the upgrade set for nobody" \
        "$status $(json '[[s["value"], s["default"], s["is_default"], s.get("fixed", False)] for s in d if s["key"] == "reports_ahead_after_seconds"]')" \
        '200 [[30, 30, true, false]]'
}

# What is new, tried on what was carried over: worked_ahead of package-test.sh, with the
# reports of the inventory from before, which have contracts, renewals and capacity
# lines in them where the previous release could hold them.
after_0015() {
    [ -n "$ahead_0015" ] || return 0
    worked_ahead
}
