# shellcheck shell=bash
# shellcheck disable=SC2034,SC2154  # Read by packaging/package-test.sh, whose names these are.
#
# Migration 0019, which comes with hirdir 0.9.18: the dates of each side of a circuit
# and the network its Z side reaches, the kind of a circuit group, and the lists of
# countries and states that an address takes its country and its state from (P-317 to
# P-321).
#
# packaging/package-test.sh reads this file when the upgrade it tests runs the
# migration, and calls the three functions below: see "what one upgrade alone has"
# there. The previous release is then at revision 0018 or before: a circuit has one set
# of dates, installed_on, activated_on and disconnected_on, which its API, its files and
# its filters name so; a circuit group is of no kind; and the country and the state of an
# address are text as they were typed. P-306: the upgrade to 0.9.18 is tested from
# 0.9.17 alone, so this file talks to that release in its own API, and asks of nothing
# older.
#
# The migration renames the three dates of a circuit a_installed_on, a_activated_on and
# a_disconnected_on, each in its place and holding what it held, and adds after the
# columns of circuits z_installed_on, z_activated_on and z_disconnected_on, blank, and
# z_group_hid, blank, with its foreign key to circuit_groups, its index, and a check that
# a Z side names a location or a network and never both; it adds kind to circuit_groups,
# collection for every group, and carrier_hid, blank, with its foreign key to vendors and
# its index. It creates countries and states and loads them from the data file beside
# it, 0019_iso3166_americas.json, which the package has to carry. Then it turns into its
# code, on every region, site and location, a country written as a listed code or name,
# without regard to case and to the spaces around it, or as USA, U.S., U.S.A. or United
# States of America, and a state written as a code or a name of the country in force, a
# blank country being the United States; anything else is kept as it was typed. Each
# place it changes is at its next row_version, and has an audit event of the migration,
# an update by system with the request ID upgrade-0019 that holds each value before and
# after. Nothing else of a row is changed: no circuit's dates, nor whether it is in
# service, a blank date of the Z side being read as the A side's. Nothing held is tidied
# by the input formats of 0.9.18 either (P-322): a telephone number and an email address
# held from before are as they were written. Going back is by the backup the upgrade
# took. docs/install.md says all of it under "From 0.9.17 to 0.9.18", and what is said
# there is what is looked for here.
upgrade_events=upgrade-0019
# It creates its two tables and then changes the addresses of the places, which hold a
# site's records: a table in the way of states would stop it before them. The trigger
# makes it fail when all of it is done, the dates renamed, the lists loaded and the
# addresses written with their events, and all of that has to be undone.
fail_by=trigger
also renamed_columns circuits 'installed_on a_installed_on
activated_on a_activated_on
disconnected_on a_disconnected_on'
also new_columns circuits 'z_installed_on DATE NULL -
z_activated_on DATE NULL -
z_disconnected_on DATE NULL -
z_group_hid VARCHAR(36) NULL -'
also new_keys circuits 'foreign key z_group_hid to circuit_groups.hid
index ix_circuits_z_group_hid on z_group_hid unique=0 origin=c partial=0'
also new_columns circuit_groups 'kind VARCHAR(20) NOT NULL -
carrier_hid VARCHAR(36) NULL -'
also new_keys circuit_groups 'foreign key carrier_hid to vendors.hid
index ix_circuit_groups_carrier_hid on carrier_hid unique=0 origin=c partial=0'

# Set by before_0019 where the previous release holds what this file makes.
noted_0019=""
# The places that before_0019 makes, each by what its address tests: region, whose
# shipping set is usa and texas; site, whose street address has no country and the state
# tx; room, ` Mexico ` and Coahuila de Zaragoza; and hall, Untied States and Texas, which
# no list holds. Their names are Upgrade Codes and that word.
declare -gA places_0019=()
# The contact from before whose email address has capitals and whose number has no
# pattern, which no format of 0.9.18 is to tidy until a file does.
contact_0019=""

# What the migration could harm, or is meant to change, made with the previous release:
# the places of each kind of address, typed as 0.9.17 takes them, and a contact with an
# email address in capitals and a number of ten digits. The circuits and their group
# from before are those that witness_circuits made, whose dates are kept here.
before_0019() {
    local made wanted name
    previous_at 0018 || return 0
    [ -n "$witness_circuited" ] || return 0
    noted_0019=yes

    api POST /regions '{"name": "Upgrade Codes", "ship_address1": "9 Witness Road", "ship_city": "Riverton", "ship_state": "texas", "ship_country": "usa"}'
    made=$status
    places_0019[region]=$(json_field hid)
    api POST /sites "{\"name\": \"Upgrade Codes Site\", \"region_hid\": \"${places_0019[region]}\", \"address1\": \"9 Witness Square\", \"city\": \"Riverton\", \"state\": \"tx\", \"ship_same_as_address\": true}"
    made="$made $status"
    places_0019[site]=$(json_field hid)
    api POST /locations "{\"name\": \"Upgrade Codes Room\", \"site_hid\": \"${places_0019[site]}\", \"kind\": \"room\", \"address1\": \"1 Witness Street\", \"city\": \"Riverton\", \"state\": \"Coahuila de Zaragoza\", \"country\": \" Mexico \", \"ship_same_as_address\": true}"
    made="$made $status"
    places_0019[room]=$(json_field hid)
    api POST /locations "{\"name\": \"Upgrade Codes Hall\", \"site_hid\": \"${places_0019[site]}\", \"kind\": \"room\", \"address1\": \"2 Witness Street\", \"city\": \"Riverton\", \"state\": \"Texas\", \"country\": \"Untied States\"}"
    made="$made $status"
    places_0019[hall]=$(json_field hid)
    api GET "/regions/${places_0019[region]}"
    made="$made $(json '[d["ship_country"], d["ship_state"]]')"
    for name in site room hall; do
        case $name in site) api GET "/sites/${places_0019[$name]}" ;; *) api GET "/locations/${places_0019[$name]}" ;; esac
        made="$made $(json '[d["country"], d["state"]]')"
    done
    expect "S64 $previous_version holds addresses as they were typed, with no list to choose from: a region whose shipping set is usa and texas, a site with no country and the state tx, a room in Mexico, which $previous_version keeps without the spaces it was sent with, and Coahuila de Zaragoza, and a room in Untied States and Texas" \
        "$made" \
        '201 201 201 201 ["usa", "texas"] [null, "tx"] ["Mexico", "Coahuila de Zaragoza"] ["Untied States", "Texas"]'
    witness_undo+=("locations/${places_0019[hall]}" "locations/${places_0019[room]}" "sites/${places_0019[site]}" "regions/${places_0019[region]}")
    # The three that the migration writes codes into are meant to change, row and record.
    rows_apart[regions]="${rows_apart[regions]:+${rows_apart[regions]},}${places_0019[region]}"
    rows_apart[sites]="${rows_apart[sites]:+${rows_apart[sites]},}${places_0019[site]}"
    rows_apart[locations]="${rows_apart[locations]:+${rows_apart[locations]},}${places_0019[room]}"
    meant[regions]="${meant[regions]:-} ${places_0019[region]}.ship_country ${places_0019[region]}.ship_state ${places_0019[region]}.row_version ${places_0019[region]}.updated_at"
    meant[sites]="${meant[sites]:-} ${places_0019[site]}.state ${places_0019[site]}.row_version ${places_0019[site]}.updated_at"
    meant[locations]="${meant[locations]:-} ${places_0019[room]}.country ${places_0019[room]}.state ${places_0019[room]}.row_version ${places_0019[room]}.updated_at"

    # A contact whose email address and number no format of 0.9.18 may tidy as the
    # upgrade carries them over: an export of the contacts loaded back is the way.
    api POST /contacts '{"name": "Upgrade Formats Person", "email": "Upgrade.Formats@Example.NET", "phone": "5550100123"}'
    made="$status $(json '[d["email"], d["phone"]]')"
    contact_0019=$(json_field hid)
    witness_undo+=("contacts/$contact_0019")
    tidied[contacts]=1
    expect "S65 $previous_version holds a contact with an email address in capitals, Upgrade.Formats@Example.NET, and the number 5550100123, each as it was typed" \
        "$made" '201 ["Upgrade.Formats@Example.NET", "5550100123"]'

    # The circuits from before, each with its dates and what is said of it today. Their
    # dates are named anew, and the comparison passes over the old names.
    api GET '/circuits?include_drafts=true&include_archived=true&limit=1000'
    cp "$work/body" "$work/circuits-0019.json"
    wanted=$(json '"".join(" " + c["hid"] + "." + k for c in d["items"] for k in ("installed_on", "activated_on", "disconnected_on"))')
    meant[circuits]="${meant[circuits]:-}$wanted"
    meant[circuit-link]="${meant[circuit-link]:-}$wanted"
    meant[circuit-internet]="${meant[circuit-internet]:-}$wanted"
    meant[circuit-dark]="${meant[circuit-dark]:-}$wanted"
    made="$(json '[[c["name"], c["installed_on"] is not None, c["activated_on"] is not None, c["disconnected_on"], c["cost_side"], c["in_service"]] for c in sorted(d["items"], key=lambda c: c["name"])]')"
    name=$(json '[c["hid"] for c in d["items"] if c["name"] == "Upgrade Witness Link"][0]')
    cp "$work/circuits-0019.json" "$work/kept-circuits-0019.json"
    # What the previous release does not know: the lists, and the new names of the
    # dates, which it refuses, and nothing changes.
    api GET /countries
    made="$made $status"
    api GET "/circuits/$name"
    api PATCH "/circuits/$name" "{\"row_version\": $(json_field row_version), \"a_installed_on\": \"$(day_from_today -401)\"}"
    made="$made $status"
    api GET '/circuits?include_drafts=true&include_archived=true&limit=1000'
    expect "pkg $previous_version holds three circuits with the dates of its own names: the link installed and activated, the internet circuit activated alone, and the dark fiber with none, which counts at its Z side, each in service; it knows no list of countries, a 404, and refuses a date by the name 0.9.18 gives it, a 422, which changes nothing" \
        "$made $(unchanged circuits-0019)" \
        '[["Upgrade Witness Dark Fiber", false, false, null, "z", true], ["Upgrade Witness Internet", false, true, null, "a", true], ["Upgrade Witness Link", true, true, null, "a", true]] 404 422 same'
}

# backup_0019: the backup that the upgrade took, as its log names it.
backup_0019() { sed -n 's/^hirdir: the database as it was before this upgrade is kept at //p' "$work/apt.log"; }

# What the migration made, and what the new version says of what was carried over,
# looked at by itself with the new version serving. It changes nothing.
changed_0019() {
    local when=$1 backup made name
    [ -n "$noted_0019" ] || return 0
    backup=$(backup_0019)

    # The backup that the upgrade took is the way back.
    expect "pkg $when the backup that the upgrade took holds the circuits with installed_on, activated_on and disconnected_on and no column of the Z side's dates, circuit groups of no kind, no list of countries or states, and the addresses as they were typed, so going back to $previous_version is by that backup (${backup:-no backup})" \
        "$(sqlite_value "${backup:-/nonexistent}" "SELECT count(*) FROM pragma_table_info('circuits') WHERE name IN ('installed_on', 'activated_on', 'disconnected_on')") $(sqlite_value "${backup:-/nonexistent}" "SELECT count(*) FROM pragma_table_info('circuits') WHERE name IN ('a_installed_on', 'a_activated_on', 'a_disconnected_on', 'z_installed_on', 'z_activated_on', 'z_disconnected_on', 'z_group_hid')") $(sqlite_value "${backup:-/nonexistent}" "SELECT count(*) FROM pragma_table_info('circuit_groups') WHERE name = 'kind'") $(sqlite_value "${backup:-/nonexistent}" "SELECT count(*) FROM sqlite_master WHERE name IN ('countries', 'states')") $(sqlite_value "${backup:-/nonexistent}" "SELECT ship_country || '/' || ship_state FROM regions WHERE hid = '${places_0019[region]}'")" \
        "3 0 0 0 usa/texas"

    # The circuits, read from the database beside the backup: each date where it was,
    # under its new name, the Z side's blank, and the check of the Z side in the table.
    made=$(inside runuser -u hirdir -- /opt/hirdir/python/bin/python3 -I -c '
import sqlite3, sys

then = sqlite3.connect(sys.argv[1]).execute("SELECT hid, installed_on, activated_on, disconnected_on FROM circuits ORDER BY hid").fetchall()
now = sqlite3.connect("/var/lib/hirdir/hirdir.db")
dates = now.execute("SELECT hid, a_installed_on, a_activated_on, a_disconnected_on FROM circuits ORDER BY hid").fetchall()
blank = now.execute("SELECT count(*) FROM circuits WHERE z_installed_on IS NOT NULL OR z_activated_on IS NOT NULL OR z_disconnected_on IS NOT NULL OR z_group_hid IS NOT NULL").fetchone()[0]
sql = now.execute("SELECT sql FROM sqlite_master WHERE type = '"'table'"' AND name = '"'circuits'"'").fetchone()[0]
kinds = now.execute("SELECT kind, count(*), count(carrier_hid) FROM circuit_groups GROUP BY kind").fetchall()
default = now.execute("SELECT dflt_value FROM pragma_table_info('"'circuit_groups'"') WHERE name = '"'kind'"'").fetchone()[0]
print("same" if then == dates and then else "differ", len(then), blank, "z_location_hid IS NULL OR z_group_hid IS NULL" in sql, kinds, default)' "${backup:-/nonexistent}" 2>&1)
    expect "pkg $when each circuit holds the dates it held, under the names of the A side, in their places; the Z side's dates and network are blank in every one, and the table checks that a Z side names a location or a network, never both; and every circuit group is a collection with no carrier, the kind a group made without one is given" \
        "$made" "same 3 0 True [('collection', 1, 0)] 'collection'"

    # The lists, from the data file that the package carries beside the migration.
    made=$(inside runuser -u hirdir -- /opt/hirdir/python/bin/python3 -I -c '
import glob, json, sqlite3

(path,) = glob.glob("/opt/hirdir/venv/lib/python3.*/site-packages/hirdir/db/migrations/versions/0019_iso3166_americas.json")
data = json.load(open(path, encoding="utf-8"))
held = sqlite3.connect("/var/lib/hirdir/hirdir.db")
countries = sorted(map(list, held.execute("SELECT code, name FROM countries")))
states = sorted(map(list, held.execute("SELECT country, code, name FROM states")))
kept = held.execute("SELECT count(*) FROM (SELECT row_version, created_by FROM countries UNION ALL SELECT row_version, created_by FROM states) WHERE row_version != 1 OR created_by IS NOT NULL").fetchone()[0]
print(len(countries), len(states), countries == sorted(data["countries"]), states == sorted(data["states"]), kept, data["source"])' 2>&1)
    expect "pkg $when the lists of countries and states hold every country of the Americas, 55, and their 633 states, each as the data file that the package carries beside migration 0019 has it, at its first row_version and made by nobody" \
        "$made" "55 633 True True 0 iso-codes 4.20.1"

    # The places, read from the database beside the backup: the three with a value a
    # list holds have its code and their next row_version, and nothing else changed;
    # the one in Untied States is as it was.
    made=$(inside runuser -u hirdir -- /opt/hirdir/python/bin/python3 -I -c '
import sqlite3, sys

then = sqlite3.connect(sys.argv[1])
now = sqlite3.connect("/var/lib/hirdir/hirdir.db")
said = []
for word in sys.argv[2:]:
    name, table, hid = word.split(":")
    columns = [c[1] for c in now.execute(f"PRAGMA table_info({table})")]
    was = dict(zip(columns, then.execute(f"SELECT * FROM {table} WHERE hid = ?", (hid,)).fetchone()))
    held = dict(zip(columns, now.execute(f"SELECT * FROM {table} WHERE hid = ?", (hid,)).fetchone()))
    changed = sorted(k for k in columns if was[k] != held[k] and k not in ("row_version", "updated_at"))
    address = [held.get(k) for k in ("country", "state", "ship_country", "ship_state") if k in held]
    said.append([name, address, changed, held["row_version"] - was["row_version"], held["updated_at"] != was["updated_at"]])
print(said)' "${backup:-/nonexistent}" "region:regions:${places_0019[region]}" "site:sites:${places_0019[site]}" "room:locations:${places_0019[room]}" "hall:locations:${places_0019[hall]}" 2>&1)
    expect "S64 $when the upgrade wrote the codes of what the lists hold: usa and texas of the region's shipping set as US and TX, tx of the site, whose blank country stays blank, as TX, and Mexico and Coahuila de Zaragoza of the room as MX and COA, each at its next row_version and with nothing else of it changed; Untied States and Texas are kept as they were typed, the room in them at the row_version it had" \
        "$made" \
        "[['region', ['US', 'TX'], ['ship_country', 'ship_state'], 1, True], ['site', [None, 'TX', None, None], ['state'], 1, True], ['room', ['MX', 'COA', None, None], ['country', 'state'], 1, True], ['hall', ['Untied States', 'Texas', None, None], [], 0, False]]"

    # And by the API: each place answers its codes and their names.
    api GET "/regions/${places_0019[region]}"
    made="$status $(json '[d["ship_country"], d["ship_state"], d["ship_country_name"], d["ship_state_name"]]')"
    api GET "/sites/${places_0019[site]}"
    made="$made $status $(json '[d["country"], d["state"], d["country_name"], d["state_name"]]')"
    for name in room hall; do
        api GET "/locations/${places_0019[$name]}"
        made="$made $status $(json '[d["country"], d["state"], d["country_name"], d["state_name"]]')"
    done
    expect "S64 $when each place answers the codes it holds and their names from the lists: the region US and TX, United States and Texas; the site no country and TX, read as the United States and Texas; the room MX and COA, Mexico and Coahuila de Zaragoza; and the room in Untied States what it holds, with no name for either" \
        "$made" \
        '200 ["US", "TX", "United States", "Texas"] 200 [null, "TX", "United States", "Texas"] 200 ["MX", "COA", "Mexico", "Coahuila de Zaragoza"] 200 ["Untied States", "Texas", null, null]'

    # The audit events of the upgrade, by system and nobody, with its request ID: an
    # update of each of the three, with each value before and after.
    api GET "/audit-events?request_id=$upgrade_events&limit=1000"
    made="$status $(python3 -c '
import json, sys
events = json.load(open(sys.argv[1], encoding="utf-8"))["items"]
names = dict(zip(sys.argv[2::2], sys.argv[3::2]))
said = sorted([e["action"], e["record_type"], names.get(e["record_hid"], e["record_hid"]), sorted([c["field"], c["old"], c["new"]] for c in e["changes"])] for e in events)
print(json.dumps([said, sorted({json.dumps([e["via"], e["actor_hid"]]) for e in events})]))' "$work/body" "${places_0019[region]}" region "${places_0019[site]}" site "${places_0019[room]}" room "${places_0019[hall]}" hall 2>&1)"
    expect "S64 $when the audit trail has, by system and nobody, with the request ID $upgrade_events, an update of each of the three places whose address the upgrade wrote, each with its values before and after, and none of the room it kept" \
        "$made" \
        '200 [[["update", "location", "room", [["country", "Mexico", "MX"], ["state", "Coahuila de Zaragoza", "COA"]]], ["update", "region", "region", [["ship_country", "usa", "US"], ["ship_state", "texas", "TX"]]], ["update", "site", "site", [["state", "tx", "TX"]]]], ["[\"system\", null]"]]'

    # What the upgrade kept as it was typed is listed for a person to choose: the
    # country no list holds, and not the state of that country, which is judged once
    # the country is chosen.
    api GET '/places/unlisted-addresses?limit=1000'
    expect "S64 $when GET /places/unlisted-addresses lists what the upgrade kept as it was typed, for a person to choose: the country Untied States of the street address of the room, and nothing else" \
        "$status $(json '[d["total"], [[r["level"], r["hid"] == "'"${places_0019[hall]}"'", r["name"], r["set"], r["field"], r["value"]] for r in d["items"]]]')" \
        '200 [1, [["location", true, "Upgrade Codes Hall", "street", "country", "Untied States"]]]'

    # The circuits by the API: each date under its new name as it was, the Z side's
    # blank and read as the A side's, and in service as it was.
    api GET '/circuits?include_drafts=true&include_archived=true&limit=1000'
    made=$(python3 -c '
import json, sys
then = {c["hid"]: c for c in json.load(open(sys.argv[1], encoding="utf-8"))["items"]}
said = []
for c in sorted(json.load(open(sys.argv[2], encoding="utf-8"))["items"], key=lambda c: c["name"]):
    was = then[c["hid"]]
    a = [c.get("a_" + k) == was[k] for k in ("installed_on", "activated_on", "disconnected_on")]
    z = [c.get("z_" + k) for k in ("installed_on", "activated_on", "disconnected_on")] + [c.get("z_group_hid")]
    effective = [[(c["effective"].get("z_" + k) or {}).get("source"), (c["effective"].get("z_" + k) or {}).get("value") == was[k]] for k in ("installed_on", "activated_on", "disconnected_on")]
    old = sorted(k for k in ("installed_on", "activated_on", "disconnected_on") if k in c)
    said.append([c["name"], a, z, effective, old, c["in_service"] == was["in_service"]])
print(json.dumps(said))' "$work/circuits-0019.json" "$work/body" 2>&1)
    expect "pkg $when each circuit answers the dates it had under the names of the A side, a_installed_on, a_activated_on and a_disconnected_on, and none by the old names; its Z side's dates and network blank, each date in force the A side's, source a_side, where the A side has one and none where it has not; and is in service as it was" \
        "$made" \
        '[["Upgrade Witness Dark Fiber", [true, true, true], [null, null, null, null], [["none", true], ["none", true], ["none", true]], [], true], ["Upgrade Witness Internet", [true, true, true], [null, null, null, null], [["none", true], ["a_side", true], ["none", true]], [], true], ["Upgrade Witness Link", [true, true, true], [null, null, null, null], [["a_side", true], ["a_side", true], ["none", true]], [], true]]'
    api GET '/circuit-groups?include_drafts=true&include_archived=true&limit=1000'
    expect "pkg $when the circuit group from before is a collection, with no carrier" \
        "$status $(json '[[g["name"], g.get("kind"), g.get("carrier_hid")] for g in d["items"]]')" \
        '200 [["Upgrade Witness Links", "collection", null]]'
    # The totals of the cost report name the circuits behind them by a filter of their
    # dates, which is to name them as they are named now.
    api GET '/reports/circuit-costs?by=carrier'
    made="$status $(python3 -c '
import json, sys

def fields(condition):
    if isinstance(condition, dict):
        if "field" in condition:
            yield condition["field"]
        for value in condition.values():
            yield from fields(value)
    elif isinstance(condition, list):
        for value in condition:
            yield from fields(value)

named = set(fields(json.load(open(sys.argv[1], encoding="utf-8"))["totals"]["filter"]))
print(json.dumps([sorted(named & {"installed_on", "activated_on", "disconnected_on"}), bool(named)]))' "$work/body" 2>&1)"
    expect "pkg $when GET /reports/circuit-costs names the circuits behind its totals by the dates as they are named now: no field of its filter is installed_on, activated_on or disconnected_on" \
        "$made" '200 [[], true]'

    # Nothing held is tidied by the formats: the contact from before is as it was typed,
    # and the settings of the formats are at their defaults.
    api GET "/contacts/$contact_0019"
    made="$status $(json '[d["email"], d["phone"], d["row_version"]]')"
    api GET /settings
    expect "S65 $when the contact from before has its email address in capitals and its number as they were typed, at the row_version it had: no format tidies what is held; and the settings of the formats are at their defaults, no pattern of a number, an email address in lower case and Title Case on the web page" \
        "$made $status $(json 'sorted([s["key"], s["value"], s["is_default"]] for s in d if s["key"] in ("phone_formats", "email_lower_case", "title_case_names"))')" \
        '200 ["Upgrade.Formats@Example.NET", "5550100123", 1] 200 [["email_lower_case", true, true], ["phone_formats", [], true], ["title_case_names", true, true]]'
}

# What is asked of what was carried over, last: a date by the name of 0.9.17 is refused
# and found by none, the new names find what the old ones did; the internet circuit from
# before reaches a network of its carrier on its Z side, which lists it there; the room in
# Untied States is changed in other things and keeps it until its country is chosen; and
# the contact from before is tidied by its contacts exported and loaded back, and not by
# a setting that changes. They leave the inventory as a site would have it after them,
# and the network is retired after the circuits.
after_0019() {
    local made rv link internet dark group network telecom code rows
    [ -n "$noted_0019" ] || return 0

    api GET '/circuits?include_drafts=true&include_archived=true&limit=1000'
    link=$(json '[c["hid"] for c in d["items"] if c["name"] == "Upgrade Witness Link"][0]')
    internet=$(json '[c["hid"] for c in d["items"] if c["name"] == "Upgrade Witness Internet"][0]')
    dark=$(json '[c["hid"] for c in d["items"] if c["name"] == "Upgrade Witness Dark Fiber"][0]')

    # No alias of the old names.
    api GET "/circuits/$link"
    rv=$(json_field row_version)
    api PATCH "/circuits/$link" "{\"row_version\": $rv, \"installed_on\": \"$(day_from_today -401)\"}"
    made="$status"
    authorized GET "$prefix/api/v1/circuits" --get --data-urlencode 'filter=installed_on:empty:false'
    made="$made $status"
    authorized GET "$prefix/api/v1/circuits" --get --data-urlencode 'filter=a_installed_on:empty:false'
    made="$made $status $(json '[c["name"] for c in d["items"]]')"
    authorized GET "$prefix/api/v1/circuits" --get --data-urlencode 'filter=a_activated_on:empty:false' --data-urlencode 'sort=a_activated_on'
    made="$made $status $(json '[c["name"] for c in d["items"]]')"
    api GET "/circuits/$link"
    expect "S63 after the upgrade, a date of a circuit from before by its old name is refused, a 422, and so is a filter by it, and the record is unchanged; filtered and sorted by the names of the A side, the circuits from before are found as their dates have it" \
        "$made $(json_field row_version)" \
        "422 422 200 [\"Upgrade Witness Link\"] 200 [\"Upgrade Witness Link\", \"Upgrade Witness Internet\"] $rv"

    # The Z side's own dates on the link, which leave it in service, its cost counting
    # at its A side.
    api PATCH "/circuits/$link" "{\"row_version\": $rv, \"z_installed_on\": \"$(day_from_today -395)\", \"z_activated_on\": \"$(day_from_today -385)\"}"
    made="$status $(json '[[d["effective"]["z_" + k]["source"] for k in ("installed_on", "activated_on", "disconnected_on")], d["in_service"]]')"
    expect "S63 after the upgrade, the Z side of the link from before is given its own installation and activation, later than the A side's: they are its own in force, its disconnection the A side's, none; and it is in service as it was" \
        "$made" '200 [["own", "own", "none"], true]'

    # A network of the carrier from before, reached by the Z side of the internet
    # circuit from before, which ended in its network by a note alone.
    api GET '/vendors?limit=1000'
    telecom=$(json '[v["hid"] for v in d["items"] if v["name"] == "Upgrade Witness Telecom"][0]')
    api POST /circuit-groups "{\"name\": \"Upgrade Witness MPLS\", \"kind\": \"network\", \"carrier_hid\": \"$telecom\"}"
    made="$status $(json '[d.get("kind"), d.get("carrier_hid") == "'"$telecom"'"]')"
    network=$(json_field hid)
    witness_undo+=("circuit-groups/$network")
    api GET "/circuits/$internet"
    api PATCH "/circuits/$internet" "{\"row_version\": $(json_field row_version), \"z_group_hid\": \"$network\"}"
    made="$made $status $(json '[d["z_group_hid"] == "'"$network"'", d["z_note"], d["in_service"]]')"
    api GET "/circuit-groups/$network/members?limit=1000"
    made="$made $status $(json '[[m["circuit"]["name"], m.get("z_side"), m["hid"]] for m in d["items"]]')"
    api GET "/circuit-groups/$network"
    rv=$(json_field row_version)
    api POST "/circuit-groups/$network/retire" "{\"row_version\": $rv}"
    made="$made $status"
    expect "S63 after the upgrade, a circuit group of the kind network is made with the carrier from before; the internet circuit from before names it on its Z side, keeping its note, and is in service as it was; the network lists it, by its Z side, with no membership of its own; and it is not retired while the circuit names it, a 409" \
        "$made" \
        '201 ["network", true] 200 [true, "carrier network", true] 200 [["Upgrade Witness Internet", true, null]] 409'
    api GET '/circuit-groups?include_drafts=true&include_archived=true&limit=1000'
    group=$(json '[g["hid"] for g in d["items"] if g["name"] == "Upgrade Witness Links"][0]')
    api GET "/circuit-groups/$group"
    api PATCH "/circuit-groups/$group" "{\"row_version\": $(json_field row_version), \"carrier_hid\": \"$telecom\"}"
    made="$status $(json '[e["field"] for e in d.get("errors", [])]')"
    api GET "/circuits/$dark"
    api PATCH "/circuits/$dark" "{\"row_version\": $(json_field row_version), \"z_location_hid\": null, \"z_group_hid\": \"$group\"}"
    made="$made $status $(json '[e["field"] for e in d.get("errors", [])]')"
    expect "S63 after the upgrade, the circuit group from before, a collection, takes no carrier, a 422 on carrier_hid, and no Z side names it, a 422 on z_group_hid" \
        "$made" '422 ["carrier_hid"] 422 ["z_group_hid"]'

    # The room in Untied States: what else of it is changed goes through, and its
    # country is kept until it is chosen; then both are checked, and it is listed no
    # more.
    api GET "/locations/${places_0019[hall]}"
    rv=$(json_field row_version)
    api PATCH "/locations/${places_0019[hall]}" "{\"row_version\": $rv, \"notes\": \"Its country to be chosen\"}"
    made="$status $(json '[d["country"], d["state"], d["notes"]]')"
    api PATCH "/locations/${places_0019[hall]}" "{\"row_version\": $((rv + 1)), \"country\": \"US\", \"state\": \"Lone Star\"}"
    made="$made $status $(json '[e["field"] for e in d.get("errors", [])]')"
    api PATCH "/locations/${places_0019[hall]}" "{\"row_version\": $((rv + 1)), \"country\": \"United States\"}"
    made="$made $status $(json '[d["country"], d["state"], d["country_name"], d["state_name"]]')"
    api GET /places/unlisted-addresses
    expect "S64 after the upgrade, the room in Untied States is given notes, which go through with its country kept as it was typed; given the United States with a state no list of it holds, it is refused at state; and given the United States by its name, it holds US, and Texas, which it held, as TX; and no place is listed as holding what no list holds" \
        "$made $status $(json_field total)" \
        '200 ["Untied States", "Texas", "Its country to be chosen"] 422 ["state"] 200 ["US", "TX", "United States", "Texas"] 200 0'

    # The formats, on the contact from before: a setting that changes tidies nothing;
    # the contacts exported and loaded back find it alone to change, its email address in
    # lower case and its number in the pattern, each beside what the file has, and
    # applied, it is so.
    made="$(put_setting phone_formats '["+1 (###) ###-####"]')"
    api GET "/contacts/$contact_0019"
    made="$made $status $(json '[d["email"], d["phone"], d["row_version"]]')"
    api POST /exports "$(whole_body contacts csv)"
    cp "$work/body" "$work/contacts-0019.csv"
    send "/imports/preview?entity=contacts&file_name=contacts.csv" "$work/contacts-0019.csv"
    code=$(json 'd["job"]["hid"]')
    rows=$(json 'd["job"]["row_count"]')
    made="$made $status $(json '(lambda j: [j["updated"], j["created"], j["rejected"]])(d["job"])')"
    api GET "/imports/$code/rows?limit=1000"
    made="$made $(json '[[r["record_hid"] == "'"$contact_0019"'", sorted([c["field"], c["old"], c["new"], c.get("as_in_file")] for c in r["changes"])] for r in d["items"] if r["outcome"] == "update"]')"
    apply_job "/imports/$code/apply"
    made="$made $status $(job_counts)"
    api GET "/contacts/$contact_0019"
    made="$made $(json '[d["email"], d["phone"], d["row_version"]]')"
    expect "S65 after the upgrade, phone_formats is set to +1 (###) ###-####, and the contact from before is as it was: a setting that changes tidies nothing held; its contacts exported and previewed back, it alone is to change, its email address in lower case and its number in the pattern, each beside the value in the file; and applied, it holds them" \
        "$made" \
        "200 [\"+1 (###) ###-####\"] 200 [\"Upgrade.Formats@Example.NET\", \"5550100123\", 1] 201 [1, 0, 0] [[true, [[\"email\", \"Upgrade.Formats@Example.NET\", \"upgrade.formats@example.net\", \"Upgrade.Formats@Example.NET\"], [\"phone\", \"5550100123\", \"+1 (555) 010-0123\", \"5550100123\"]]]] 202 [\"applied\", $rows, 0, 1, $((rows - 1)), 0] [\"upgrade.formats@example.net\", \"+1 (555) 010-0123\", 2]"
    # Tidied, it loads back as nothing to change; and the pattern is taken away again.
    unset 'tidied[contacts]'
    put_setting phone_formats null >/dev/null
}
