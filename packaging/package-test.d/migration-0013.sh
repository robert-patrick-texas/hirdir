# shellcheck shell=bash
# shellcheck disable=SC2034,SC2154  # Read by packaging/package-test.sh, whose names these are.
#
# Migration 0013, which came with hirdir 0.9.8: an item replaced, and taking another's
# place, more than once (P-241).
#
# packaging/package-test.sh reads this file when the upgrade it tests runs the
# migration, and calls the three functions below: see "what one upgrade alone has"
# there. The previous release is then at revision 0012 or before: an item is replaced
# once and takes the place of one item, and a replacement of an item that was replaced,
# or by an item that took a place, is refused with 409.
#
# The migration makes item_replacements anew: it drops the two uniquenesses, of the item
# that left and of the item that came, and puts an index on each in their place and one
# uniqueness of the two items with the day. It creates no table, so the pass whose
# migration fails puts the trigger on alembic_version in its way, which refuses the
# revision of the new version: by then this migration is done, and whatever comes after
# it, and all of it has to be undone. It changes no row and writes no audit event: every
# replacement that is held was the only one of each of its items. docs/install.md says so
# under "From 0.9.7 to 0.9.8", and what is said there is what is looked for here.
writes_no_event=yes
also gone_keys item_replacements 'index - on new_item_hid unique=1 origin=u partial=0
index - on old_item_hid unique=1 origin=u partial=0'
also new_keys item_replacements 'index - on old_item_hid,new_item_hid,replaced_on unique=1 origin=u partial=0
index ix_item_replacements_new_item_hid on new_item_hid unique=0 origin=c partial=0
index ix_item_replacements_old_item_hid on old_item_hid unique=0 origin=c partial=0'

# Set by before_0013 when the previous release holds an inventory with groups.
replaced_0013=""
# The items that before_0013 makes, by serial number, and the stack and the circuit.
declare -gA kept_0013=()
pool_0013=""
link_0013=""
# The day of the replacements that before_0013 makes, which after_0013 makes its own on.
day_0013=""
# The named constraints of item_replacements, as the previous release has them.
constraints_0013=""

# replacement_constraints: the constraints that the table of replacements names, each as
# "name kind" on a line, in order, from its CREATE statement: the names of its
# uniquenesses are not in what table_read keys prints.
replacement_constraints() {
    inside runuser -u hirdir -- /opt/hirdir/python/bin/python3 -I -c '
import re, sqlite3

(sql,) = sqlite3.connect("/var/lib/hirdir/hirdir.db").execute(
    "SELECT sql FROM sqlite_master WHERE type = '"'"'table'"'"' AND name = '"'"'item_replacements'"'"'"
).fetchone()
print("\n".join(sorted(f"{name} {kind} ({over})" for name, kind, over in re.findall(r"CONSTRAINT (\w+) (UNIQUE|CHECK) \(([^)]*)\)", sql))))' 2>&1
}

# replace_0013 OLD NEW REASON REFERENCE [DAY]: POST /items/OLD/replace with NEW, an item
# that exists, at the row_version that OLD has now.
replace_0013() {
    api GET "/items/$1"
    api POST "/items/$1/replace" "{\"row_version\": $(json_field row_version), \"new_item_hid\": \"$2\", \"reason\": \"$3\", \"reference\": \"$4\"${5:+, \"replaced_on\": \"$5\"}}"
}

# replacement_lists HID...: what each item says of its replacements, by serial number:
# the one it replaces and the one that replaced it, the latest of each, and the list of
# them all, each as its part and the other item, in the order it is given.
replacement_lists() {
    local hid listed=""
    for hid in "$@"; do
        api GET "/items/$hid"
        listed="$listed $status $(json '[(d["replaces"] or {}).get("serial_number"), (d["replaced_by"] or {}).get("serial_number"), [[r["part"], r["item"]["serial_number"]] for r in d.get("replacements", [])]]')"
    done
    printf '%s' "${listed# }"
}

# What the migration could harm, made with the previous release: replacements, one of
# them of a member of a stack that is on a circuit, whose new item takes over its place
# in the stack and its end of the circuit, and one made by a file. Then what the previous
# release refuses, which the new version is to allow: an item that was replaced replaced
# again, a spare that took a place taking another, and the switch that left taking the
# place of the spare that took its own.
before_0013() {
    local made serial row_version job
    [ -n "$witness_entry" ] && [ "${#witness_groups[@]}" -gt 0 ] || return 0
    replaced_0013=yes

    # A stack of two switches, the second of which is at the end of a circuit in the room
    # from before, two spares in the pool, and two switches that stand alone.
    made=""
    for serial in UWN0000K001 UWN0000K002 UWN0000K003 UWN0000K004; do
        witness_made "$serial" "$witness_entry" '"lifecycle_state": "Prod"'
        kept_0013[$serial]=$made_hid
        made="$made$status "
    done
    for serial in UWN0000K008 UWN0000K009; do
        witness_made "$serial" "$witness_entry" '"lifecycle_state": "Assigned", "disposition": "Spare"'
        kept_0013[$serial]=$made_hid
        made="$made$status "
    done
    api POST /device-groups "{\"type\": \"stack\", \"name\": \"upgrade-pool-stack\", \"members\": [{\"item_hid\": \"${kept_0013[UWN0000K001]}\", \"role\": \"master\", \"position\": 1}, {\"item_hid\": \"${kept_0013[UWN0000K002]}\", \"role\": \"member\", \"position\": 2}]}"
    made="$made$status"
    pool_0013=$(json_field hid)
    witness_groups+=("$pool_0013")
    members_made=$((members_made + 2))
    if [ -n "$witness_circuited" ] && [ -n "$witness_room" ]; then
        api POST /circuits "{\"name\": \"Upgrade Pool Link\", \"enterprise_circuit_id\": \"UW-EC-0013\", \"circuit_type\": \"point_to_point\", \"port_mbps\": \"1000\", \"a_location_hid\": \"$witness_room\", \"z_note\": \"hand-off in the hall\"}"
        made="$made $status"
        if [ "$status" = 201 ]; then
            link_0013=$(json_field hid)
            witness_undo=("circuits/$link_0013" "${witness_undo[@]}")
            witness_lists+=("circuit-pool /circuits/$link_0013")
        fi
        api POST "/circuits/$link_0013/devices" "{\"devices\": [{\"item_hid\": \"${kept_0013[UWN0000K002]}\", \"side\": \"a\"}]}"
        made="$made $status"
    fi
    expect "pkg $previous_version holds a stack of two switches$([ -n "$link_0013" ] && echo ', the second at the A end of a circuit'), two spares and two switches that stand alone" \
        "$made" "201 201 201 201 201 201 201$([ -n "$link_0013" ] && echo ' 201 201')"

    # The second switch of the stack fails, and a spare takes its place, in the stack and
    # on the circuit.
    replace_0013 "${kept_0013[UWN0000K002]}" "${kept_0013[UWN0000K009]}" rma RMA-0000-131
    made="$status $(json '[d["old_item"]["serial_number"], d["new_item"]["serial_number"], d["reason"], d["reference"]]')"
    day_0013=$(json_field replaced_on)
    members_made=$((members_made + 1))
    replacements_made=$((replacements_made + 1))
    api GET "/device-groups/$pool_0013/members?include_past=true"
    made="$made $(json 'sorted([m["position"], m["item"]["serial_number"], m["left_on"] is None] for m in d["items"])')"
    if [ -n "$link_0013" ]; then
        api GET "/circuits/$link_0013"
        made="$made $(json '[[x["side"], x["item_hid"]] for x in d["devices"]]')"
    fi
    expect "pkg the second switch is replaced for an RMA by the spare, which takes its position in the stack$([ -n "$link_0013" ] && echo ' and its end of the circuit')" \
        "$made" "201 [\"UWN0000K002\", \"UWN0000K009\", \"rma\", \"RMA-0000-131\"] [[1, \"UWN0000K001\", true], [2, \"UWN0000K002\", false], [2, \"UWN0000K009\", true]]$([ -n "$link_0013" ] && echo " [[\"a\", \"${kept_0013[UWN0000K009]}\"]]")"

    # A switch that stands alone is replaced by the other spare, by a file.
    if previous_at 0008; then
        api POST '/imports/preview?file_name=upgrade-replacements.json' "{\"schema\": \"hirdir/1\", \"entity\": \"item_replacements\", \"mode\": \"upsert\", \"records\": [{\"old_item\": \"${kept_0013[UWN0000K003]}\", \"new_item\": \"${kept_0013[UWN0000K008]}\", \"reason\": \"refresh\", \"reference\": \"CHG-0000-213\"}]}"
        made="$status $(job_counts)"
        job=$(json 'd["job"]["hid"]')
        apply_job "/imports/$job/apply"
        made="$made $(job_counts)"
        replacements_made=$((replacements_made + 1))
        expect "pkg a file of one replacement, of the first switch that stands alone by the other spare, is previewed and applied with $previous_version" \
            "$made" '201 ["previewed", 1, 1, 0, 0, 0] ["applied", 1, 1, 0, 0, 0]'
    fi

    # What the previous release refuses: the switch that was replaced, replaced again; a
    # spare that took a place, taking another; and the switch that left, back from the
    # manufacturer, taking the place of the spare that took its own.
    replace_0013 "${kept_0013[UWN0000K002]}" "${kept_0013[UWN0000K004]}" rma RMA-0000-132
    made="$status $(json 'd["detail"]') $(json '[e["field"] for e in d.get("errors", [])]')"
    replace_0013 "${kept_0013[UWN0000K004]}" "${kept_0013[UWN0000K009]}" refresh CHG-0000-214
    made="$made | $status $(json 'd["detail"]') $(json '[e["field"] for e in d.get("errors", [])]')"
    replace_0013 "${kept_0013[UWN0000K009]}" "${kept_0013[UWN0000K002]}" rma RMA-0000-131
    expect "pkg $previous_version refuses a replacement of the switch that was replaced, with 409; one by the spare that took its place, with 409; and the switch that left taking the place of that spare, with 422" \
        "$made | $status $(json 'd["detail"]') $(json '[e["field"] for e in d.get("errors", [])]')" \
        '409 this item has been replaced already ["new_item_hid"] | 409 this item took the place of another already ["new_item_hid"] | 422 an item does not take the place of one that took its own ["new_item_hid"]'

    # Kept as the previous release gives them, to be compared field by field: every
    # replacement there is, the inventory's own among them, and the named constraints of
    # the table.
    api GET '/reports/replacements?limit=1000'
    keep replacements-0013
    expect "pkg and lists the $replacements_made replacements there are in its report of replacements" \
        "$status $(json_field total)" "200 $replacements_made"
    constraints_0013=$(replacement_constraints)
}

# What the migration made, and what the new version says of what was carried over,
# looked at by itself with the new version serving.
changed_0013() {
    local when=$1 wanted hids
    [ -n "$replaced_0013" ] || return 0

    expect "pkg $when the table of replacements names its uniquenesses as $version has them: item_replacements_old and item_replacements_new are gone, and item_replacements_pair_day is there, of the two items with the day" \
        "$(printf '%s' "$constraints_0013" | cut -d' ' -f1 | xargs) | $(replacement_constraints)" \
        'item_replacements_new item_replacements_old | item_replacements_pair_day UNIQUE (old_item_hid, new_item_hid, replaced_on)'

    api GET '/reports/replacements?limit=1000'
    expect "pkg $when every replacement is as it was, field for field and at the row_version it had: the $replacements_made of the report, the inventory's own among them, and no other" \
        "$status $(json_field total) $(unchanged replacements-0013 fields)" "200 $replacements_made same"

    # Each item of a replacement says what it said of it, and lists it, the one of each.
    read -ra hids <<<"$(json '" ".join(h for r in d["items"] for h in (r["old_item_hid"], r["new_item_hid"]))')"
    wanted=$(python3 -c '
import json, sys

kept = json.load(open(sys.argv[1], encoding="utf-8"))["items"]
said = []
for hid in sys.argv[2:]:
    left = [r for r in kept if r["old_item_hid"] == hid]
    came = [r for r in kept if r["new_item_hid"] == hid]
    serial = lambda r, side: r[side]["serial_number"]
    entries = [["left", serial(r, "new_item")] for r in left] + [["came", serial(r, "old_item")] for r in came]
    said.append("200 " + json.dumps([serial(came[0], "old_item") if came else None, serial(left[0], "new_item") if left else None, entries]))
print(" ".join(said))' "$work/kept-replacements-0013.json" "${hids[@]}")
    expect "pkg $when each item of each replacement says which item it replaces and which replaced it as it did, and lists that one replacement in its replacements, as the item that left or the item that came" \
        "$(replacement_lists "${hids[@]}")" "$wanted"
}

# What is new, tried on what was carried over: the switch that left takes back the place
# of the spare that took its own, and is replaced a second time, by the other spare,
# which took a place by the file and takes another; the stack and the circuit follow.
# The same two items the same way on the same day are refused.
after_0013() {
    local made k001 k002 k008 k009 second
    [ -n "$replaced_0013" ] || return 0
    k001=${kept_0013[UWN0000K001]}
    k002=${kept_0013[UWN0000K002]}
    k008=${kept_0013[UWN0000K008]}
    k009=${kept_0013[UWN0000K009]}

    # The switch that left is back from the manufacturer and takes the place of the
    # spare, which 0.9.7 refused as a loop.
    replace_0013 "$k009" "$k002" rma RMA-0000-133 "$day_0013"
    made="$status $(json '[d["old_item"]["serial_number"], d["new_item"]["serial_number"], d["replaced_on"]]')"
    # Then it is replaced a second time, by the other spare, which took the place of the
    # switch that stands alone by the file and takes a second place.
    replace_0013 "$k002" "$k008" refresh CHG-0000-215 "$day_0013"
    made="$made $status $(json '[d["old_item"]["serial_number"], d["new_item"]["serial_number"], d["replaced_on"]]')"
    second=$(json_field hid)
    expect "pkg with $version the switch that left takes back the place of the spare that took its own, and is then replaced a second time, by the other spare, which takes a second place: 201 each, on the day of the first" \
        "$made" "201 [\"UWN0000K009\", \"UWN0000K002\", \"$day_0013\"] 201 [\"UWN0000K002\", \"UWN0000K008\", \"$day_0013\"]"

    api GET "/device-groups/$pool_0013/members?include_past=true"
    made="$status $(json '[[m["position"], m["item"]["serial_number"], m["left_on"] is None] for m in sorted(d["items"], key=lambda m: (m["position"], m["created_at"]))]')"
    if [ -n "$link_0013" ]; then
        api GET "/circuits/$link_0013"
        made="$made $(json '[[x["side"], x["item_hid"]] for x in d["devices"]]')"
    fi
    expect "pkg position 2 of the stack went from the spare to the switch and from it to the other spare, each membership ended as the next began, and the first switch is where it was$([ -n "$link_0013" ] && echo '; the end of the circuit went with it')" \
        "$made" "200 [[1, \"UWN0000K001\", true], [2, \"UWN0000K002\", false], [2, \"UWN0000K009\", false], [2, \"UWN0000K002\", false], [2, \"UWN0000K008\", true]]$([ -n "$link_0013" ] && echo " [[\"a\", \"$k008\"]]")"

    # Each item says the latest of each, and lists them all, the latest first.
    expect "pkg the switch says it replaces the spare and was replaced by the other spare, the latest of each, and lists its three replacements, the latest first; the spare that came first lists two, the other spare two, and the first switch none" \
        "$(replacement_lists "$k002" "$k009" "$k008" "$k001")" \
        '200 ["UWN0000K009", "UWN0000K008", [["left", "UWN0000K008"], ["came", "UWN0000K009"], ["left", "UWN0000K009"]]] 200 ["UWN0000K002", "UWN0000K002", [["left", "UWN0000K002"], ["came", "UWN0000K002"]]] 200 ["UWN0000K002", null, [["came", "UWN0000K002"], ["came", "UWN0000K003"]]] 200 [null, null, []]'

    # The same two items the same way on the same day: refused, naming the one there is.
    replace_0013 "$k002" "$k008" refresh CHG-0000-216 "$day_0013"
    made="$status $(json '[e["field"] for e in d.get("errors", [])]') $(json '[(d.get("existing") or {}).get(k) for k in ("record_type", "hid")]')"
    api GET '/reports/replacements?limit=1000'
    expect "pkg and the switch replaced by the other spare again on that day is refused with 409, naming the replacement there is, and nothing is recorded: the report lists $((replacements_made + 2)) replacements" \
        "$made $status $(json_field total)" "409 [\"new_item_hid\"] [\"item_replacement\", \"$second\"] 200 $((replacements_made + 2))"
}
