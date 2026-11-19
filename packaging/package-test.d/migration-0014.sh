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
# What before_0014 makes: a server, and a model of the kind virtual_machine with a
# machine of it that stands alone and one installed in the server, as 0.9.7 held them.
server_0014=""
vm_alone_0014=""
vm_inside_0014=""

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

# vendor_0014: the HID of the vendor of the first model of the inventory.
vendor_0014() {
    api GET "/catalog-entries/$witness_entry"
    json_field vendor_hid
}

# vms_file_0014 ROW...: a file of items as JSON, each ROW being HID:EXTERNAL_ID.
vms_file_0014() {
    local row records=""
    for row in "$@"; do
        records="$records${records:+, }{\"hid\": \"${row%%:*}\", \"external_id\": \"${row#*:}\"}"
    done
    printf '{"schema": "hirdir/1", "entity": "items", "mode": "upsert", "records": [%s]}' "$records"
}

# What the migration could harm, made with the previous release. What it makes anew, the
# items table, is in the inventory already, with every kind of value that the previous
# release can hold, and so are the rows of other tables that refer to an item, which the
# comparison of the tables reads, and the import jobs, of which migration 0013's file
# makes one where none is made before it. What each table declares beside its columns
# and keys is kept, to be read again after the upgrade. Then what the new version reads
# otherwise: a model of the kind virtual_machine, with a machine of it that stands alone
# and one installed in its server, which is how the previous release could hold one.
# The previous release has no kind container.
before_0014() {
    local made vendor entry
    [ -n "$witness_entry" ] || return 0
    hosted_0014=yes
    declared_0014=$(declared_0014_now)
    if previous_at 0009; then
        expect "pkg $previous_version declares no check on items, and on import_jobs the defaults of the three counts that an apply keeps" \
            "$declared_0014" "import_jobs default applied '0'
import_jobs default rows_done '0'
import_jobs default stale '0'"
    fi

    vendor=$(vendor_0014)
    api POST /catalog-entries "{\"vendor_hid\": \"$vendor\", \"pid\": \"UW-VM-STD\", \"kind\": \"virtual_machine\"}"
    made="$status $(json_field kind)"
    entry=$(json_field hid)
    api POST /catalog-entries "{\"vendor_hid\": \"$vendor\", \"pid\": \"UW-APP\", \"kind\": \"container\"}"
    made="$made $status"
    witness_made UWN0000V001 "$witness_entry" '"name": "upgrade-hv-01", "lifecycle_state": "Prod"'
    server_0014=$made_hid
    made="$made $status"
    witness_made UWN0000V101 "$entry" '"name": "upgrade-vm-01", "lifecycle_state": "Prod"'
    vm_alone_0014=$made_hid
    made="$made $status"
    witness_made UWN0000V102 "$entry" "\"name\": \"upgrade-vm-02\", \"lifecycle_state\": \"Prod\", \"parent_item_hid\": \"$server_0014\""
    vm_inside_0014=$made_hid
    expect "pkg $previous_version takes a model of the kind virtual_machine and refuses one of the kind container; it holds a server, a machine of the model that stands alone, and one installed in the server as a minor item of it" \
        "$made $status $(json "[d['is_major'], d['depth'], d['parent_item_hid'] == '$server_0014']")" \
        "201 virtual_machine 422 201 201 201 [false, 1, true]"
}

# What the migration made, looked at by itself with the new version serving.
changed_0014() {
    local when=$1 database=/var/lib/hirdir/hirdir.db made vms
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

    # What the new version says of what was carried over: no item runs on anything or
    # has anything run on it, and only the two machines are to be looked at, for naming
    # no host, the one installed in its server among them, as docs/install.md says.
    vms="('$vm_alone_0014', '$vm_inside_0014')"
    api GET "$every_item"
    expect "pkg $when every item of $previous_version answers with no host, nothing seen as one, nothing that runs on it and nothing to be looked at, but the two machines, which name no host and are to be looked at for it: no_host" \
        "$status $(json "sorted({json.dumps([i['host_item_hid'], i['host_group_hid'], i['observed_host_hid'], i['hosted_count'], [r['reason'] for r in i['review']]]) for i in d['items'] if i['hid'] not in $vms})") $(json "[[i['name'], [r['reason'] for r in i['review']], i['host']] for i in sorted(d['items'], key=lambda i: i['name'] or '') if i['hid'] in $vms]")" \
        '200 ["[null, null, null, 0, []]"] [["upgrade-vm-01", ["no_host"], null], ["upgrade-vm-02", ["no_host"], null]]'
    api GET /settings
    expect "pkg $when count_kinds, at its default, counts the two new kinds beside hardware and virtual_machine, and no model of $previous_version is of either" \
        "$status $(json '[[sorted(s["value"]), s["is_default"]] for s in d if s["key"] == "count_kinds"]')" \
        '200 [[["container", "hardware", "virtual_context", "virtual_machine"], true]]'
    api GET '/imports?limit=1000'
    expect "pkg $when every import job answers that it was read from no system, is not said to be complete, and marked nothing" \
        "$status $(json 'sorted({json.dumps([j["system_hid"], j["system"], j["complete"], j["not_reported"]]) for j in d["items"]})')" \
        '200 ["[null, null, null, 0]"]'
}

# What is new, tried once each on what was carried over: the machine installed in its
# server put right by one change; a container on an item from before, which has its
# place from it, and one named on a member of the stack from before, which runs on the
# stack and was seen on the member; a virtual context given the server's serial number,
# which runs on it and holds none; the retirement of the server asked with dry_run; and a
# file of items read from an external system, loaded twice, the second time as
# everything that system reports with one item left out, which is marked and nothing
# else.
after_0014() {
    local made vendor entry container staked vdc system job place
    [ -n "$hosted_0014" ] || return 0
    vendor=$(vendor_0014)

    # The machine that the previous release held as installed in its server.
    api GET "/items/$vm_inside_0014"
    api PATCH "/items/$vm_inside_0014" "{\"row_version\": $(json_field row_version), \"host_item_hid\": \"$server_0014\", \"parent_item_hid\": null}"
    expect "pkg with $version the machine that was installed in its server is put right by one change, which takes it out of the server and names the server as its host: it is a major item, runs on the server, and has nothing to be looked at" \
        "$status $(json "[d['parent_item_hid'], d['host_item_hid'] == '$server_0014', d['is_major'], d['review']]")" \
        '200 [null, true, true, []]'

    # A container on the item from before with every value, which is in the room.
    api POST /catalog-entries "{\"vendor_hid\": \"$vendor\", \"pid\": \"UW-APP\", \"kind\": \"container\"}"
    made="$status $(json_field kind)"
    entry=$(json_field hid)
    api GET "/items/$witness_full"
    place=$(json 'd["effective"]["location_hid"]["value"]')
    api POST /items "{\"catalog_entry_hid\": \"$entry\", \"name\": \"upgrade-app-01\", \"lifecycle_state\": \"Prod\", \"host_item_hid\": \"$witness_full\"}"
    made="$made $status"
    container=$(json_field hid)
    if [ "$status" = 201 ]; then witness_items+=("$container"); fi
    api GET "/items/$container"
    expect "pkg a model of the kind container is made, and an item of it on the item from before with every value, which is where that item is, from its host" \
        "$made $([ "$place" != null ] && echo placed) $(json "[d['host_item_hid'] == '$witness_full', d['effective']['location_hid']['value'] == '$place', d['effective']['location_hid']['source'], d['effective']['location_hid']['source_hid'] == '$witness_full']")" \
        '201 container 201 placed [true, true, "host", true]'

    # A container named on the first switch of the stack from before runs on the stack.
    api POST /items "{\"catalog_entry_hid\": \"$entry\", \"name\": \"upgrade-app-02\", \"lifecycle_state\": \"Prod\", \"host_item_hid\": \"$witness_switch\"}"
    made=$status
    staked=$(json_field hid)
    if [ "$status" = 201 ]; then witness_items+=("$staked"); fi
    api GET "/items/$staked"
    made="$made $(json "[d['host_item_hid'], d['host_group_hid'] == '$witness_stack', d['observed_host_hid'] == '$witness_switch', d['host_observed_at'] is not None]")"
    api GET "/device-groups/$witness_stack"
    expect "pkg one named on the first switch of the stack from before runs on the stack, and was seen on that switch, now; the stack says one thing runs on it" \
        "$made $(json_field hosted_count)" '201 [null, true, true, true] 1'

    # A virtual context given the serial number of the server from before, which no other
    # item has.
    api POST /catalog-entries "{\"vendor_hid\": \"$vendor\", \"pid\": \"UW-VDC\", \"kind\": \"virtual_context\"}"
    made=$status
    api POST /items "{\"catalog_entry_hid\": \"$(json_field hid)\", \"name\": \"upgrade-vdc-01\", \"lifecycle_state\": \"Prod\", \"serial_number\": \"UWN0000V001\"}"
    made="$made $status"
    vdc=$(json_field hid)
    if [ "$status" = 201 ]; then witness_items+=("$vdc"); fi
    api GET "/items/$vdc"
    expect "pkg a virtual context given UWN0000V001, the serial number of the server from before, runs on the server, holds no serial number of its own, and shows that one as from its host" \
        "$made $(json "[d['host_item_hid'] == '$server_0014', d['serial_number'], d['effective']['serial_number']['value'], d['effective']['serial_number']['source']]")" \
        '201 201 [true, null, "UWN0000V001", "host"]'

    # Retiring the server, asked with dry_run: what would go with it, and nothing goes.
    api POST /items/retire "{\"hids\": [\"$server_0014\"], \"dry_run\": true}"
    made="$status $(json "[d['dry_run'], [r['hid'] == '$server_0014' for r in d['retired']], sorted(h['hid'] for h in d['hosted']) == sorted(['$vm_inside_0014', '$vdc'])]")"
    for job in "$server_0014" "$vm_inside_0014" "$vdc"; do
        api GET "/items/$job"
        made="$made $(json_field record_status)"
    done
    expect "pkg retiring the server with dry_run says that the machine and the context would go with it, and retires none of the three" \
        "$made" '200 [true, [true], true] active active active'

    # A file of the two machines read from an external system, by their identifiers
    # there, and the same system's report once more, as everything it reports, without
    # the second.
    api POST /external-systems '{"name": "Upgrade Example Hypervisors", "kind": "other"}'
    made=$status
    system=$(json_field hid)
    witness_undo=("external-systems/$system" "${witness_undo[@]}")
    api POST "/imports/preview?file_name=upgrade-vms.json&system=$system" "$(vms_file_0014 "$vm_alone_0014:vm-0101" "$vm_inside_0014:vm-0102")"
    made="$made $status $(json "(lambda j: [j['system_hid'] == '$system', j['complete']])(d.get('job', d))")"
    job=$(json 'd["job"]["hid"]')
    apply_job "/imports/$job/apply"
    made="$made $(job_counts)"
    api GET '/registrations?limit=1000'
    expect "pkg a file of the two machines read from an external system, each by its identifier there, is previewed and applied: each is registered with the system under that identifier" \
        "$made $status $(json "sorted([r['external_id'], r['status']] for r in d['items'] if r['system_hid'] == '$system')")" \
        '201 201 [true, false] ["applied", 2, 0, 2, 0, 0] 200 [["vm-0101", "registered"], ["vm-0102", "registered"]]'

    api POST "/imports/preview?file_name=upgrade-vms-again.json&system=$system&complete=true" "$(vms_file_0014 "$vm_alone_0014:vm-0101")"
    made="$status $(json "(lambda j: [j['complete'], j['not_reported'], [x['hid'] == '$vm_inside_0014' for x in j['not_reported_first']]])(d.get('job', d))")"
    job=$(json 'd["job"]["hid"]')
    apply_job "/imports/$job/apply"
    made="$made $(job_counts) $(json_field not_reported)"
    api GET "/items/$vm_inside_0014"
    made="$made $(json "[d['record_status'], d['lifecycle_state'], [[r['reason'], (r['about'] or {}).get('hid') == '$system'] for r in d['review']], sorted(x['status'] for x in d['registrations'])]")"
    api GET "/items/$vm_alone_0014"
    expect "pkg loaded again as everything that system reports, without the second machine, the file says it would mark that one; once applied the second is not reported, and to be looked at for it, and is neither retired nor moved; the first is confirmed, and is to be looked at for naming no host alone" \
        "$made $(json '[[r["reason"] for r in d["review"]], [x["status"] for x in d["registrations"]]]')" \
        '201 [true, 1, [true]] ["applied", 1, 0, 0, 1, 0] 1 ["active", "Prod", [["not_reported", true]], ["not_reported"]] [["no_host"], ["registered"]]'
}
