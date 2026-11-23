# shellcheck shell=bash
# shellcheck disable=SC2034,SC2154  # Read by packaging/package-test.sh, whose names these are.
#
# Migration 0020, which comes with hirdir 0.9.19: how far a preview in the background has
# got (P-325).
#
# packaging/package-test.sh reads this file when the upgrade it tests runs the
# migration, and calls the three functions below: see "what one upgrade alone has"
# there. The previous release is then at revision 0019: it previews every file in its
# request, one of more than a hundred rows on a copy of the database, and answers 201
# with the job previewed and its first hundred rows; a job of it says nothing of how far
# a preview has got. P-306: the upgrade to 0.9.19 is tested from 0.9.18 alone, so this
# file talks to that release in its own API, and asks of nothing older.
#
# The migration adds one column to import_jobs after the others, rows_previewed, an
# integer that is never blank and is 0 where it is not given, and sets it to the
# row_count of every job, since every job before it was previewed whole in its request.
# It creates no table, so the pass whose migration fails puts the trigger on
# alembic_version in its way, which refuses this revision once the column is added and
# set, and all of it has to be undone. Nothing else of a job is changed, nor any row of
# one, nor any record, and no audit event is written. Going back is by the backup the
# upgrade took. docs/install.md says all of it under "From 0.9.18 to 0.9.19", and what is
# said there is what is looked for here.
writes_no_event=yes
# The import jobs and their rows are a site's own and no part of the inventory: their two
# tables are kept and compared as the inventory's tables are, every job in the columns
# it had, with the new one after them, and every row of a job as it was, which a table
# made anew could lose. A file of an earlier migration may have named them. The upgrade
# pass previews a file of its own on the new version before it compares them, which is
# a job and rows beside those that were kept.
case " $more_tables " in *" import_jobs "*) ;; *) more_tables="${more_tables:+$more_tables }import_jobs" ;; esac
case " $more_tables " in *" import_rows "*) ;; *) more_tables="${more_tables:+$more_tables }import_rows" ;; esac
may_add[import_jobs]=yes
may_add[import_rows]=yes
also new_columns import_jobs 'rows_previewed INTEGER NOT NULL -'

# Set by before_0020 where the previous release holds what this file makes.
noted_0020=""
# How many rows the files of this file have: many, one more than a preview is worked in
# its request from 0.9.19, and few.
many_0020=$((in_request_rows + 1))
few_0020=2
# The jobs that before_0020 makes, by what each is: many, a file of $many_0020 states
# that the previous release previewed in its request and that waits to be applied; and
# few, a file of $few_0020 states that it previewed and applied.
declare -gA jobs_0020=()

# states_0020 COUNT NAME: write the first COUNT records of the states, as the previous
# release exported them whole, to $work/NAME, as a file of their own.
states_0020() {
    python3 -c '
import json, sys

document = json.load(open(sys.argv[1], encoding="utf-8"))
document["records"] = document["records"][: int(sys.argv[2])]
with open(sys.argv[3], "w", encoding="utf-8") as out:
    json.dump(document, out)' "$work/states-0020.json" "$1" "$work/$2"
}

# backup_0020: the backup that the upgrade took, as its log names it.
backup_0020() { sed -n 's/^hirdir: the database as it was before this upgrade is kept at //p' "$work/apt.log"; }

# What the migration is meant to change, made with the previous release: import jobs to
# be given how far they were previewed, one of more rows than 0.9.19 previews in a
# request, which 0.9.18 previewed in its own and which waits to be applied, and one that
# it applied. Each is a file of the states that every inventory holds, exported by the
# previous release and loaded back, so that no row of either changes a record.
before_0020() {
    local made
    previous_at 0019 || return 0
    noted_0020=yes

    api POST /exports "$(whole_body states json)"
    cp "$work/body" "$work/states-0020.json"
    made="$status $(json 'len(d["records"]) > '"$in_request_rows")"
    states_0020 "$many_0020" states-0020-many.json
    states_0020 "$in_request_rows" states-0020-hundred.json
    states_0020 "$few_0020" states-0020-few.json

    api POST '/imports/preview?file_name=states-0020-many.json' "$(cat "$work/states-0020-many.json")"
    made="$made $status $(job_counts) $(json 'len(d["rows"])') $(json '"rows_previewed" in d["job"]')"
    jobs_0020[many]=$(json 'd["job"]["hid"]')
    api POST '/imports/preview?file_name=states-0020-few.json' "$(cat "$work/states-0020-few.json")"
    made="$made $status $(job_counts)"
    jobs_0020[few]=$(json 'd["job"]["hid"]')
    apply_job "/imports/${jobs_0020[few]}/apply"
    made="$made $status $(job_counts)"
    expect "pkg $previous_version previews a file of $many_0020 of its states, more than a hundred rows, in its request: a 201 with the job previewed, every row unchanged, its first hundred rows in the answer, and nothing said of how far a preview has got; and a file of $few_0020, previewed and applied, every row unchanged" \
        "$made" \
        "200 true 201 [\"previewed\", $many_0020, 0, 0, $many_0020, 0] 100 false 201 [\"previewed\", $few_0020, 0, 0, $few_0020, 0] 202 [\"applied\", $few_0020, 0, 0, $few_0020, 0]"
}

# What the migration made, looked at by itself with the new version serving. It changes
# nothing.
changed_0020() {
    local when=$1 backup made
    [ -n "$noted_0020" ] || return 0
    backup=$(backup_0020)

    # The backup that the upgrade took is the way back.
    expect "pkg $when the backup that the upgrade took holds the import jobs from before, the $many_0020 states and the $few_0020, in a table with no column rows_previewed, so going back to $previous_version is by that backup (${backup:-no backup})" \
        "$(sqlite_value "${backup:-/nonexistent}" "SELECT count(*) FROM pragma_table_info('import_jobs') WHERE name = 'rows_previewed'") $(sqlite_value "${backup:-/nonexistent}" "SELECT group_concat(row_count, ' ') FROM (SELECT row_count FROM import_jobs WHERE hid IN ('${jobs_0020[many]}', '${jobs_0020[few]}') ORDER BY row_count)")" \
        "0 $few_0020 $many_0020"

    # Every job, read from the database beside the backup: what it previewed is all its
    # rows; and the column is declared as the migration declares it. What else a job
    # holds is compared by tables_carried, which reads every column it had.
    made=$(inside runuser -u hirdir -- /opt/hirdir/python/bin/python3 -I -c '
import sqlite3, sys

then = dict(sqlite3.connect(sys.argv[1]).execute("SELECT hid, row_count FROM import_jobs").fetchall())
now = sqlite3.connect("/var/lib/hirdir/hirdir.db")
held = dict(now.execute("SELECT hid, rows_previewed FROM import_jobs").fetchall())
default, not_null = now.execute("SELECT dflt_value, \"notnull\" FROM pragma_table_info(?) WHERE name = ?", ("import_jobs", "rows_previewed")).fetchone()
every = "every" if then and all(held.get(hid) == count for hid, count in then.items()) else "not every"
print(every, sorted(held.get(hid) for hid in sys.argv[2:]), default, not_null)' "${backup:-/nonexistent}" "${jobs_0020[few]}" "${jobs_0020[many]}" 2>&1)
    expect "pkg $when every import job from before has rows_previewed at its row_count, as a preview worked in its request leaves it: $few_0020 and $many_0020; and the column is 0 where it is not given, and never blank" \
        "$made" "every [$few_0020, $many_0020] '0' 1"

    # And by the API: each with the status it had, the one that waits to be applied with
    # its rows listed, as before.
    api GET "/imports/${jobs_0020[many]}"
    made="$status $(json '[d["status"], d["row_count"], d["rows_previewed"], d["rows_done"]]')"
    api GET "/imports/${jobs_0020[few]}"
    made="$made $status $(json '[d["status"], d["row_count"], d["rows_previewed"]]')"
    api GET "/imports/${jobs_0020[many]}/rows?limit=1"
    made="$made $status $(json_field total)"
    expect "pkg $when each import job from before answers rows_previewed, its row_count: the $many_0020 states that $previous_version previewed in its request, previewed still, none of its rows applied, and its rows listed, all $many_0020; and the $few_0020 that it applied, applied" \
        "$made" \
        "200 [\"previewed\", $many_0020, $many_0020, 0] 200 [\"applied\", $few_0020, $few_0020] 200 $many_0020"
}

# What is asked of what was carried over, last: the job that the previous release
# previewed in its request, of more rows than 0.9.19 previews in one, is applied as any
# preview is; and the same file sent again is previewed by the second process, which
# send follows, while a hundred of its rows are previewed in the request still. Neither
# of the two is applied, and no record is changed by any of it.
after_0020() {
    local made
    [ -n "$noted_0020" ] || return 0

    apply_job "/imports/${jobs_0020[many]}/apply"
    expect "pkg after the upgrade, the job of $many_0020 states that $previous_version previewed in its request is applied by $version as any preview is, every row unchanged" \
        "$status $(job_counts)" "202 [\"applied\", $many_0020, 0, 0, $many_0020, 0]"

    # The answer as it came is kept by send where it followed one, and only there.
    rm -f "$work/begun.json"
    send '/imports/preview?file_name=states-0020-many.json' "$work/states-0020-many.json" application/json
    made="$status $(json '[d["job"]["status"], d["job"]["rows_previewed"], len(d["rows"])]') $(job_counts)"
    made="$made $(python3 -c '
import json, sys

try:
    job, rows = (lambda d: (d["job"], d["rows"]))(json.load(open(sys.argv[1], encoding="utf-8")))
    print(json.dumps([job["status"], job["row_count"], job["rows_previewed"] < job["row_count"], rows]))
except (OSError, ValueError, KeyError, TypeError) as error:
    print(f"<{type(error).__name__}: {error}>")' "$work/begun.json")"
    send '/imports/preview?file_name=states-0020-hundred.json' "$work/states-0020-hundred.json" application/json
    made="$made | $status $(json '[d["job"]["status"], d["job"]["rows_previewed"], len(d["rows"])]') $(job_counts)"
    expect "pkg after the upgrade, the same file of $many_0020 states is answered 202, with its job previewing, not every row worked and no rows, and is previewed by the second process: every row unchanged and worked, the first hundred listed; a file of $in_request_rows of them is previewed at once in its request, as before, a 201 with its rows" \
        "$made" \
        "202 [\"previewed\", $many_0020, 100] [\"previewed\", $many_0020, 0, 0, $many_0020, 0] [\"previewing\", $many_0020, true, []] | 201 [\"previewed\", $in_request_rows, $in_request_rows] [\"previewed\", $in_request_rows, 0, 0, $in_request_rows, 0]"
}
