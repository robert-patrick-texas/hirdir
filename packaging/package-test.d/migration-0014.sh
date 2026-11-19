# shellcheck shell=bash
# shellcheck disable=SC2034,SC2154  # Read by packaging/package-test.sh, whose names these are.
#
# Migration 0014, which came with hirdir 0.9.8: what runs on a host (P-226, P-246), and
# what an external system reports (P-248).
#
# packaging/package-test.sh reads this file when the upgrade it tests runs the
# migration, and calls the three functions below: see "what one upgrade alone has"
# there. The previous release is then at revision 0013 or before: an item runs on
# nothing, and an import is read from no system.
#
# The migration makes the items table anew with four columns more: host_item_hid and
# host_group_hid, the host a person names, an item or a device group, with a foreign key
# and an index each, observed_host_hid, the item it was seen to run on, with its own,
# and host_observed_at; and one check, items_one_host, that an item names one host at
# most. Then it makes import_jobs anew with three columns more: system_hid, with a
# foreign key to external_systems, complete, and not_reported, which is 0 where it is not
# given. It creates no table, so the pass whose migration fails puts the trigger on
# alembic_version in its way, which refuses this revision, the last one written: by then
# both tables are made anew, and migration 0013 is done before it. It changes no row and
# writes no audit event: every item has no host, and every import job was read from no
# system. docs/install.md says so under "From 0.9.7 to 0.9.8", and what is said there is
# what is looked for here.
writes_no_event=yes
also new_columns items 'host_item_hid VARCHAR(36) NULL -
host_group_hid VARCHAR(36) NULL -
observed_host_hid VARCHAR(36) NULL -
host_observed_at DATETIME NULL -'
also new_keys items 'foreign key host_group_hid to device_groups.hid
foreign key host_item_hid to items.hid
foreign key observed_host_hid to items.hid
index ix_items_host_group_hid on host_group_hid unique=0 origin=c partial=0
index ix_items_host_item_hid on host_item_hid unique=0 origin=c partial=0
index ix_items_observed_host_hid on observed_host_hid unique=0 origin=c partial=0'
# The import jobs are a site's own and no part of the inventory: their table is kept and
# compared as the inventory's tables are.
case " $more_tables " in *" import_jobs "*) ;; *) more_tables="${more_tables:+$more_tables }import_jobs" ;; esac
# The upgrade pass previews a file of its own on the new version before it compares
# them, which is a job beside those that were kept.
may_add[import_jobs]=yes
also new_columns import_jobs 'system_hid VARCHAR(36) NULL -
complete BOOLEAN NULL -
not_reported INTEGER NOT NULL -'
also new_keys import_jobs 'foreign key system_hid to external_systems.hid'

# Set by before_0014 when the previous release holds an inventory, for the other two.
hosted_0014=""
# What the two tables declare beside their columns and keys, as the previous release
# has them.
declared_0014=""

# declared_0014_now: what items and import_jobs declare in their CREATE statements that
# table_read does not print, a line each: each check, named or not, and each default of a
# column. Making a table anew on SQLite copies what the model of the migration says, so
# a check or a default that the table had and the model did not would be lost without a
# word in what table_read prints.
declared_0014_now() {
    inside runuser -u hirdir -- /opt/hirdir/python/bin/python3 -I -c '
import re, sqlite3

held = sqlite3.connect("/var/lib/hirdir/hirdir.db")
lines = []
for table in ("items", "import_jobs"):
    (sql,) = held.execute("SELECT sql FROM sqlite_master WHERE type = ? AND name = ?", ("table", table)).fetchone()
    for name, check in re.findall(r"(?:CONSTRAINT (\w+) )?CHECK \((.*?)\)(?=,?\s*(?:\n|\)$|CONSTRAINT|PRIMARY|UNIQUE|FOREIGN))", sql):
        lines.append(f"{table} check {name or chr(45)} {check}")
    for column, default in re.findall(r"(\w+) \w+(?:\(\d+\))? DEFAULT (\S+)", sql):
        lines.append(f"{table} default {column} {default}")
print("\n".join(sorted(lines)))' 2>&1
}

# What the migration could harm, made with the previous release. What it makes anew, the
# items table, is in the inventory already, with every kind of value that the previous
# release can hold, and so are the rows of other tables that refer to an item, which the
# comparison of the tables reads, and the import jobs, of which migration 0013's file
# makes one where none is made before it. So nothing more is made: what each table
# declares beside its columns and keys is kept, to be read again after the upgrade.
before_0014() {
    [ -n "$witness_entry" ] || return 0
    hosted_0014=yes
    declared_0014=$(declared_0014_now)
    if previous_at 0009; then
        expect "pkg $previous_version declares no check on items, and on import_jobs the defaults of the three counts that an apply keeps" \
            "$declared_0014" "import_jobs default applied '0'
import_jobs default rows_done '0'
import_jobs default stale '0'"
    fi

    # STAGE TWO: what the previous release refuses or does not know of a host and of a
    # system an import is read from, shown with it here, is written when the code that
    # uses the columns is merged.
}

# What the migration made, looked at by itself with the new version serving.
changed_0014() {
    local when=$1 database=/var/lib/hirdir/hirdir.db made
    [ -n "$hosted_0014" ] || return 0

    expect "pkg $when the four columns of items and the three of import_jobs hold nothing: no item names a host or was seen on one, no import job names a system or says whether it is complete, and each has not_reported 0" \
        "$(sqlite_value "$database" 'SELECT (SELECT count(*) FROM items WHERE host_item_hid IS NOT NULL OR host_group_hid IS NOT NULL OR observed_host_hid IS NOT NULL OR host_observed_at IS NOT NULL) + (SELECT count(*) FROM import_jobs WHERE system_hid IS NOT NULL OR complete IS NOT NULL OR not_reported <> 0)')" 0
    expect "pkg $when and no row refers to a record that is not there" \
        "$(sqlite_text 'PRAGMA foreign_key_check' | wc -l)" 0
    expect "pkg $when items declares the one check that the migration adds, items_one_host, and import_jobs the defaults it had and the one of not_reported" \
        "$(declared_0014_now)" "$(printf '%s\n' "$declared_0014" "import_jobs default not_reported '0'" 'items check items_one_host host_item_hid IS NULL OR host_group_hid IS NULL' | LC_ALL=C sort)"

    # The check is tried as well as read, in a transaction that is undone.
    made=$(inside runuser -u hirdir -- /opt/hirdir/python/bin/python3 -I -c '
import sqlite3, sys

held = sqlite3.connect("/var/lib/hirdir/hirdir.db", timeout=10)
try:
    held.execute("UPDATE items SET host_item_hid = ?, host_group_hid = ? WHERE hid = ?", sys.argv[1:4])
    print("taken")
except sqlite3.IntegrityError as error:
    print(error)
finally:
    held.rollback()' "$witness_full" "${witness_groups[0]:-none}" "$witness_item" 2>&1)
    expect "pkg $when an item that names an item and a group as its host at once is refused by the database" \
        "$made" "CHECK constraint failed: items_one_host"

    # STAGE TWO: what the new version says of a host and of an import read from a
    # system, of the items and the jobs that were carried over, is written when the
    # code that uses the columns is merged.
}

# What is new, tried on what was carried over.
after_0014() {
    [ -n "$hosted_0014" ] || return 0
    # STAGE TWO: a host given to items that were carried over, an item seen on another,
    # and an import read from a system, which is everything it reports, are written
    # when the code that uses the columns is merged.
    return 0
}
