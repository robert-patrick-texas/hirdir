# shellcheck shell=bash
# shellcheck disable=SC2034,SC2154  # Read by packaging/package-test.sh, whose names these are.
#
# Migration 0007, which came with hirdir 0.5.0: contacts, operators, regions, sites,
# locations and the members of owners.
#
# packaging/package-test.sh reads this file when the upgrade it tests runs the
# migration, and calls the three functions below: see "what one upgrade alone has"
# there. The previous release is then at revision 0006 or before: it knows no place,
# no contact and no operator, and an item or a device group of it may be with an owner
# outside the team, which says nothing more of either.
#
# The migration creates contacts, operators, regions, sites, locations and
# contact_assignments, and makes the items and the device_groups tables anew, each with
# three columns: the location it is at, the location that is planned for it, and its
# operator. It loads the contact_role and location_kind lists, and leaves alone what it
# finds in them. Last of all it creates owner_members, which is the table that the pass
# whose migration fails puts in its way: everything else is done by then. It changes no
# record there is and writes no audit event. docs/install.md says so under "From 0.4.2
# to 0.5.0", and what is said there is what is looked for here.
writes_no_event=yes
# It loads the two lists beside the choices that are there.
may_add[choices]=yes
new_columns[items]='location_hid VARCHAR(36) NULL -
planned_location_hid VARCHAR(36) NULL -
operator_hid VARCHAR(36) NULL -'
new_keys[items]='foreign key location_hid to locations.hid
foreign key operator_hid to operators.hid
foreign key planned_location_hid to locations.hid
index ix_items_location_hid on location_hid unique=0 origin=c partial=0
index ix_items_operator_hid on operator_hid unique=0 origin=c partial=0
index ix_items_planned_location_hid on planned_location_hid unique=0 origin=c partial=0'
new_columns[device_groups]=${new_columns[items]}
new_keys[device_groups]=${new_keys[items]//ix_items_/ix_device_groups_}

outside_owner=""
outside_item=""
outside_group=""
money_before=""
owners_before=""
versions_before=""

# What the migration could harm, made with the previous release: an item and a device
# group that are with an owner outside the team already, with a minor item in the item,
# and choices of a site's own in the two lists that the migration loads.
before_0007() {
    local made
    [ -n "$witness_entry" ] || return 0

    api POST /owners '{"label": "Upgrade Witness Facilities", "organization": "Building Services", "is_external": true, "exception_reason": "Looks after the door controllers"}'
    made=$status
    outside_owner=$(json_field hid)
    witness_made UWN0000E001 "$witness_entry" "\"lifecycle_state\": \"Prod\", \"owner_hid\": \"$outside_owner\""
    outside_item=$made_hid
    made="$made $status"
    witness_made UWN0000E002 "$witness_second" "\"parent_item_hid\": \"$outside_item\", \"position\": \"PS-A\""
    made="$made $status"
    witness_made UWN0000E003 "$witness_entry" '"lifecycle_state": "Prod"'
    made="$made $status"
    api POST /device-groups "{\"type\": \"custom\", \"name\": \"upgrade-doors\", \"owner_hid\": \"$outside_owner\", \"members\": [{\"item_hid\": \"$made_hid\"}]}"
    outside_group=$(json_field hid)
    witness_groups+=("$outside_group")
    members_made=$((members_made + 1))
    expect "pkg $previous_version holds an owner outside the team, with the reason that such an owner must have, an item that is with it, a minor item in that item, and a device group that is with it and has a member with no owner of its own: nothing more is said of any of them" \
        "$made $status $not_made" "201 201 201 201 201 0"

    # From this migration's release on, an item with no owner of its own has the owner
    # of its group (D-130). Nothing that is held changes, and what such an item says of
    # its owner in force does: the three switches of the first stack, which has an
    # owner, the two minor items in the first of them that have none of their own, and
    # the member of the group that is with the owner outside the team. That one field
    # of each is left out of the comparison by name and looked at by itself, and so is
    # the count by owner, which the previous release has of them as nobody's.
    api GET '/items?filter=serial_number:in:UWN0000S001,UWN0000S003,UWN0000S009,UWN0000P001,UWN0000M001,UWN0000E003&sort=serial_number&limit=1000'
    versions_before=$(json '[[i["serial_number"], i["row_version"]] for i in d["items"]]')
    expect "pkg with $previous_version those six have no owner, of their own or in force, though the group of each has one" \
        "$status $(json 'sorted({(i["owner_hid"], i["effective"]["owner_hid"]["value"]) for i in d["items"]})') $(json_field total)" \
        "200 [[null, null]] 6"
    for made in $(json '" ".join(i["hid"] for i in d["items"])'); do
        meant[items]+=" $made.effective.owner_hid"
    done
    api GET '/reports/summary?by=owner'
    owners_before=$(json '{(r["label"] or ""): r["items"] for r in d["rows"]}')

    # The previous release uses neither list, and takes a choice in each all the same.
    # One is the site's alone, and one has the value of a default under a label of the
    # site's: the migration is to leave both as they are.
    api POST /choices '{"list": "contact_role", "value": "site-security", "label": "Site security"}'
    made=$status
    api POST /choices '{"list": "contact_role", "value": "shipping", "label": "Goods in"}'
    made="$made $status"
    api POST /choices '{"list": "location_kind", "value": "cage", "label": "Cage"}'
    made="$made $status"
    api POST /choices '{"list": "location_kind", "value": "rack", "label": "Cabinet"}'
    expect "pkg and four choices of a site's own in the contact_role and location_kind lists, which $previous_version does not use: in each, one that is the site's alone, and one with the value of a default under a label of the site's" \
        "$made $status" "201 201 201 201"

    # What answers differently afterwards: the management report with no by.
    api GET /reports/management
    money_before=$(money)
    expect "pkg GET /reports/management of $previous_version, asked with no by, is by nothing and has no row" \
        "$status $(json '[d["by"], d["rows"]]')" "200 [null, []]"
    # A file of items and one of device groups with a location column, which the
    # previous release does not know. They are sent through nginx, which only the
    # upgrade pass installs.
    if [ "$mode" = upgrade ]; then
        printf 'hid,location\n%s,Upgrade Witness Region > Upgrade Witness Site > Upgrade Witness Cage\n' "$witness_item" >"$work/placed.csv"
        send "/imports/preview?entity=items&file_name=placed.csv" "$work/placed.csv"
        made="$status $(json 'd["errors"][0]["field"]')"
        printf 'hid,location\n%s,Upgrade Witness Region > Upgrade Witness Site > Upgrade Witness Cage\n' "$witness_stack" >"$work/placed-groups.csv"
        send "/imports/preview?entity=device_groups&file_name=placed-groups.csv" "$work/placed-groups.csv"
        expect "pkg a file of items with a location column is refused by $previous_version, for its unknown column, and so is one of device groups" \
            "$made $status $(json 'd["errors"][0]["field"]')" "422 column 422 column"
    fi
}

# What the migration made, and what the new version says differently of what was
# carried over, looked at by itself with the new version serving.
changed_0007() {
    local when=$1 database=/var/lib/hirdir/hirdir.db made
    [ -n "$outside_item" ] || return 0

    # What is new is empty until somebody fills it in.
    expect "pkg $when the seven tables that the migration creates are empty: contacts, operators, regions, sites, locations, contact_assignments and owner_members" \
        "$(sqlite_value "$database" 'SELECT (SELECT count(*) FROM contacts) + (SELECT count(*) FROM operators) + (SELECT count(*) FROM regions) + (SELECT count(*) FROM sites) + (SELECT count(*) FROM locations) + (SELECT count(*) FROM contact_assignments) + (SELECT count(*) FROM owner_members)')" 0
    expect "pkg $when the new columns hold nothing: no item and no device group has a location, a planned location or an operator" \
        "$(sqlite_value "$database" 'SELECT (SELECT count(*) FROM items WHERE location_hid IS NOT NULL OR planned_location_hid IS NOT NULL OR operator_hid IS NOT NULL) + (SELECT count(*) FROM device_groups WHERE location_hid IS NOT NULL OR planned_location_hid IS NOT NULL OR operator_hid IS NOT NULL)')" 0
    api GET "$every_group"
    made=$(json 'sorted({json.dumps([g[k] for k in ("location_hid", "location", "planned_location_hid", "planned_location", "operator_hid", "operator")] + [g["effective"][k]["value"] for k in ("location_hid", "planned_location_hid", "operator_hid")]) for g in d["items"]})')
    api GET "$every_item"
    expect "pkg $when no device group and no item is anywhere, is planned for anywhere or has an operator, of its own or in force, by what each says of itself" \
        "$made $(json 'sorted({json.dumps([i[k] for k in ("location_hid", "location", "planned_location_hid", "planned_location", "operator_hid", "operator")] + [i["effective"][k]["value"] for k in ("location_hid", "planned_location_hid", "operator_hid")]) for i in d["items"]})')" \
        '["[null, null, null, null, null, null, null, null, null]"] ["[null, null, null, null, null, null, null, null, null]"]'
    made=$(json_field total)
    api GET '/geography/tree?include_archived=true&include_drafts=true'
    expect "pkg $when the tree of places is empty, and every item there is, $made of them, is counted as nowhere" \
        "$status $(json '[d["roots"], d["hidden"]["items"], d["unplaced"] == d["totals"], d["totals"]["items"]]')" \
        "200 [[], 0, true, $made]"
    api GET '/reports/summary?by=operator'
    expect "pkg $when a report by operator has one row, of what nobody is assigned to, which holds the items of the totals" \
        "$status $(json '[d["by"], [[r["key"], r["items"] == d["totals"]["items"]] for r in d["rows"]]]')" \
        '200 ["operator", [[null, true]]]'

    # An item with no owner of its own has the owner of its group from now on. It is
    # not written to, and it is counted with that owner.
    api GET '/items?filter=owner_hid:empty:true%20effective.owner_hid:empty:false&include_archived=true&include_drafts=true&sort=serial_number&limit=1000'
    expect "pkg $when GET /items?filter=owner_hid:empty:true effective.owner_hid:empty:false lists every item that has its owner from above: the six that have it from their group now, the minor items of a switch among them, and the minor item that had it from the item it is in before" \
        "$status $(json '[[i["serial_number"], i["effective"]["owner_hid"]["label"], i["effective"]["owner_hid"]["source"]] for i in d["items"]]')" \
        '200 [["UWN0000E002", "Upgrade Witness Facilities", "parent_item"], ["UWN0000E003", "Upgrade Witness Facilities", "device_group"], ["UWN0000M001", "Upgrade Witness Team", "device_group"], ["UWN0000P001", "Upgrade Witness Team", "device_group"], ["UWN0000S001", "Upgrade Witness Team", "device_group"], ["UWN0000S003", "Upgrade Witness Team", "device_group"], ["UWN0000S009", "Upgrade Witness Team", "device_group"]]'
    expect "pkg $when and none of the six was written to: each is at the row_version it had ($versions_before)" \
        "$(json '[[i["serial_number"], i["row_version"]] for i in d["items"] if i["effective"]["owner_hid"]["source"] == "device_group"]')" \
        "$versions_before"
    api GET '/reports/summary?by=owner'
    expect "pkg $when the counts by owner have changed, as docs/install.md says they may: the six are counted with the owners of their groups, where $previous_version counted them as nobody's ($owners_before), and nothing else has moved" \
        "$status $(json '{(r["label"] or ""): r["items"] for r in d["rows"]}')" \
        "200 $(python3 -c 'import json, sys
counted = json.loads(sys.argv[1])
for owner, moved in (("", -6), ("Upgrade Witness Team", 5), ("Upgrade Witness Facilities", 1)):
    counted[owner] = counted.get(owner, 0) + moved
print(json.dumps(counted, sort_keys=True))' "$owners_before")"

    # What was with an owner outside the team is marked as an exception, with the
    # reason of that owner, and so is what has that owner from above: the minor item,
    # from the item it is in, and the member of the group that is with that owner.
    api GET '/items?filter=owner_exception:eq:true&include_archived=true&include_drafts=true&sort=serial_number'
    expect "pkg $when GET /items?filter=owner_exception:eq:true lists the item that was with an owner outside the team, the minor item in it, and the member of the group that is with that owner, each marked, with the reason of that owner, and no other" \
        "$status $(json '[[i["serial_number"], i["owner_exception"], i["owner_exception_reason"]] for i in d["items"]]')" \
        '200 [["UWN0000E001", true, "Looks after the door controllers"], ["UWN0000E002", true, "Looks after the door controllers"], ["UWN0000E003", true, "Looks after the door controllers"]]'
    api GET "$every_group"
    expect "pkg $when the device group that was with that owner is marked likewise, and no other group is" \
        "$status $(json '[[g["name"], g["owner_exception"], g["owner_exception_reason"]] for g in d["items"] if g["owner_exception"]]')" \
        '200 [["upgrade-doors", true, "Looks after the door controllers"]]'
    api GET "/owners/$outside_owner"
    expect "pkg $when the record of an owner lists its tags and its members, of which there are none, beside what it held" \
        "$status $(json '[d["label"], d["is_external"], d["exception_reason"], d["tags"], d["members"]]')" \
        '200 ["Upgrade Witness Facilities", true, "Looks after the door controllers", [], []]'

    # The two lists are loaded beside what the site had in them.
    api GET '/choices?list=contact_role'
    expect "pkg $when the contact_role list holds its five defaults and the site's own, with shipping there once, under the label the site gave it" \
        "$status $(json '" ".join(sorted(c["value"] + "=" + c["label"].replace(" ", "_") for c in d))')" \
        "200 escalation=Escalation federal=Federal operational=Operational shipping=Goods_in site-security=Site_security technical=Technical"
    api GET '/choices?list=location_kind'
    expect "pkg $when and the location_kind list its six defaults and the site's own, with rack there once, under the label the site gave it" \
        "$status $(json '" ".join(sorted(c["value"] + "=" + c["label"].replace(" ", "_") for c in d))')" \
        "200 building=Building cage=Cage floor=Floor other=Other rack=Cabinet room=Room warehouse=Warehouse"

    # The management report with no by is by site: one row, of the items that are
    # nowhere, beside totals that are as they were.
    api GET /reports/management
    expect "pkg $when GET /reports/management with no by says that it is by site, and has one row, of the items that are nowhere, which holds what the totals hold; the totals are as $previous_version gave them ($money_before)" \
        "$status $(json '[d["by"], len(d["rows"]), d["rows"][0]["key"], {**d["rows"][0], "key": 0, "label": 0} == {**d["totals"], "key": 0, "label": 0}]') $(money)" \
        "200 [\"site\", 1, null, true] $money_before"
}

# What is new, tried on what was carried over.
after_0007() {
    local made region site cage staging contact operator assignment row_version hid
    [ -n "$outside_item" ] || return 0

    # An export of the item that is with an owner outside the team is imported back:
    # nothing is changed by it, and nothing is asked.
    api POST /exports '{"entity": "items", "format": "csv", "own_values": true, "filter": "serial_number:glob:UWN0000E00*", "sort": ["depth"]}'
    cp "$work/body" "$work/outside.csv"
    send "/imports/preview?entity=items&file_name=outside.csv" "$work/outside.csv"
    expect "pkg an export of the item that was with an owner outside the team, of the minor item in it and of the member of the group, with their own values, is imported back as it is: each row finds its record unchanged, and nothing is asked for" \
        "$status $(job_counts) $(json '[[r["outcome"], [x["field"] for x in r["reasons"]]] for r in d["rows"] if r["outcome"] != "unchanged"]')" \
        '201 ["previewed", 3, 0, 0, 3, 0] []'

    # The reason is the owner's. An item is given such an owner with nothing more
    # said, has no reason of its own to give, and an owner is not made external
    # without one.
    api GET "/items/$outside_item"
    api PATCH "/items/$outside_item" "{\"row_version\": $(json_field row_version), \"comments\": \"Seen after the upgrade\", \"owner_hid\": \"$outside_owner\"}"
    expect "pkg the item that was with an owner outside the team is changed in another field, with its owner said again as it is: it stays marked, with the reason of its owner" \
        "$status $(json '[d["comments"], d["owner_exception"], d["owner_exception_reason"]]')" \
        '200 ["Seen after the upgrade", true, "Looks after the door controllers"]'
    api GET "/items/$witness_item"
    row_version=$(json_field row_version)
    api PATCH "/items/$witness_item" "{\"row_version\": $row_version, \"owner_hid\": \"$outside_owner\", \"owner_exception_reason\": \"A reason of its own\"}"
    made="$status $(json '[e["field"] for e in d["errors"]]')"
    api PATCH "/items/$witness_item" "{\"row_version\": $row_version, \"owner_hid\": \"$outside_owner\"}"
    made="$made $status $(json '[d["owner_exception"], d["owner_exception_reason"]]')"
    api POST /owners '{"label": "Upgrade Witness Landlord", "is_external": true}'
    expect "pkg an item from before is given that owner: a reason of the item's own is not taken, and with nothing more said the item is marked, with the reason of the owner; an owner outside the team with no reason is refused" \
        "$made $status $(json '[e["field"] for e in d["errors"]]')" \
        '422 ["owner_exception_reason"] 200 [true, "Looks after the door controllers"] 422 ["exception_reason"]'

    # A place is made, of the kind that the site had entered before the upgrade, with
    # a contact in the role of the site's own and an operator on the site.
    api POST /regions '{"name": "Upgrade Witness Region"}'
    made=$status
    region=$(json_field hid)
    api POST /sites "{\"name\": \"Upgrade Witness Site\", \"region_hid\": \"$region\"}"
    made="$made $status"
    site=$(json_field hid)
    api POST /locations "{\"name\": \"Upgrade Witness Cage\", \"site_hid\": \"$site\", \"kind\": \"cage\"}"
    made="$made $status $(json_field kind)"
    cage=$(json_field hid)
    api POST /contacts '{"name": "Upgrade Witness Guard", "email": "upgrade.guard@example.net"}'
    made="$made $status"
    contact=$(json_field hid)
    api POST /contact-assignments "{\"contact_hid\": \"$contact\", \"role\": \"site-security\", \"site_hid\": \"$site\"}"
    made="$made $status"
    assignment=$(json_field hid)
    api GET "/locations/$cage/effective"
    expect "pkg a region, a site and a location of the kind the site entered before the upgrade are made, and a contact with the role of the site's own at the site: the location shows that contact, from its site, and has an entry for each of the six roles, shipping under the site's label" \
        "$made $status $(json '[[c["role"], c["source"], [p["name"] for p in c["contacts"]]] for c in d["contacts"] if c["contacts"]]') $(json '[len(d["contacts"]), [c["label"] for c in d["contacts"] if c["role"] == "shipping"]]')" \
        '201 201 201 cage 201 201 200 [["site-security", "site", ["Upgrade Witness Guard"]]] [6, ["Goods in"]]'
    api POST /operators "{\"label\": \"UW1\", \"colour\": \"#1f6feb\", \"contact_hid\": \"$contact\"}"
    made=$status
    operator=$(json_field hid)
    api GET "/sites/$site"
    api PATCH "/sites/$site" "{\"row_version\": $(json_field row_version), \"operator_hid\": \"$operator\"}"
    made="$made $status"

    # An item and a group from before are put there by the two files with a location
    # column that the previous release refused.
    send "/imports/preview?entity=items&file_name=placed.csv" "$work/placed.csv"
    made="$made | $status $(job_counts)"
    api POST "/imports/$(json 'd["job"]["hid"]')/apply"
    made="$made $status $(job_counts)"
    send "/imports/preview?entity=device_groups&file_name=placed-groups.csv" "$work/placed-groups.csv"
    api POST "/imports/$(json 'd["job"]["hid"]')/apply"
    made="$made | $status $(job_counts)"
    api GET "/device-groups/$witness_stack"
    made="$made $(json 'd["location"]["path"]')"
    api GET "/items/$witness_item"
    expect "pkg an operator is made, with that contact behind it, and put on the site; the two files with a location column that $previous_version refused are previewed and applied: the item is at that location, and so is the first stack" \
        "$made | $(json '[d["location"]["path"], d["effective"]["location_hid"]["source"]]')" \
        '201 200 | 201 ["previewed", 1, 0, 1, 0, 0] 200 ["applied", 1, 0, 1, 0, 0] | 200 ["applied", 1, 0, 1, 0, 0] Upgrade Witness Region > Upgrade Witness Site > Upgrade Witness Cage | ["Upgrade Witness Region > Upgrade Witness Site > Upgrade Witness Cage", "own"]'
    expect "pkg and the item, which has no operator of its own and is in no group that has one, has the operator of the site it is at, with the person behind it" \
        "$(json '[d["operator_hid"], d["effective"]["operator_hid"]["label"], d["effective"]["operator_hid"]["source"], d["effective"]["operator_hid"]["contact"], d["effective"]["operator_hid"]["is_open"]]')" \
        '[null, "UW1", "site", "Upgrade Witness Guard", false]'
    api POST /exports '{"entity": "items", "format": "csv", "own_values": true}'
    made=$(table '["location" in head, [r["location"] for r in rows if r["serial_number"] == "UWN0000X001"]]')
    authorized GET "$prefix/api/v1/items" --get --data-urlencode 'filter=location:within:Upgrade Witness Region' --data-urlencode 'sort=serial_number'
    expect "pkg an export of the columns that can be set writes the location, and the item list finds within the region the item and, with it, the three switches of the stack and the three minor items in the first of them: none has a location of its own, and each is where the stack is, and says that it has that from the group" \
        "$made $status $(json '[[i["serial_number"], i["effective"]["location_hid"]["source"]] for i in d["items"]]')" \
        '[true, ["Upgrade Witness Region > Upgrade Witness Site > Upgrade Witness Cage"]] 200 [["UWN0000M001", "device_group"], ["UWN0000P001", "device_group"], ["UWN0000S001", "device_group"], ["UWN0000S003", "device_group"], ["UWN0000S009", "device_group"], ["UWN0000T001", "device_group"], ["UWN0000X001", "own"]]'
    api GET '/geography/tree'
    expect "pkg GET /geography/tree counts the seven at the location, the site and the region, and what is in the tree, what is nowhere and what is hidden add up to the totals" \
        "$status $(json '(lambda walk: [walk(walk, d["roots"][0]), d["roots"][0]["items"] + d["unplaced"]["items"] + d["hidden"]["items"] == d["totals"]["items"]])(lambda walk, n: [n["name"], n["items"]] + [walk(walk, c) for c in n["children"]])')" \
        '200 [["Upgrade Witness Region", 7, ["Upgrade Witness Site", 7, ["Upgrade Witness Cage", 7]]], true]'

    # A second location is a draft, and an item from before is planned for it: made
    # active, the location takes the item in, with an entry in the item's history.
    api POST /locations "{\"name\": \"Upgrade Witness Staging\", \"site_hid\": \"$site\", \"record_status\": \"draft\"}"
    made=$status
    staging=$(json_field hid)
    api GET "/items/$witness_full"
    api PATCH "/items/$witness_full" "{\"row_version\": $(json_field row_version), \"planned_location_hid\": \"$staging\"}"
    made="$made $status $(json '[d["location_hid"], d["planned_location"]["name"]]')"
    api PATCH "/locations/$staging" '{"row_version": 1, "record_status": "active"}'
    made="$made $status"
    api GET "/items/$witness_full"
    made="$made $(json '[d["location"]["name"], d["planned_location_hid"]]')"
    api GET "/items/$witness_full/history?limit=1"
    expect "pkg an item from before is planned for a location that is a draft, and stays where it is; the location is made active, and the item is there, with its plan cleared and an entry of its own in its history" \
        "$made $(json '[[e["action"], sorted(c["field"] for c in e["changes"])] for e in d["items"]]')" \
        '201 200 [null, "Upgrade Witness Staging"] 200 ["Upgrade Witness Staging", null] [["update", ["location_hid", "planned_location_hid"]]]'

    # Taken out again, so that the rest of this pass starts from a tree as empty as a
    # new installation's. A place is retired when nothing is in it.
    made=""
    for hid in "$witness_item" "$witness_full"; do
        api GET "/items/$hid"
        api PATCH "/items/$hid" "{\"row_version\": $(json_field row_version), \"location_hid\": null}"
        made="$made$status "
    done
    api GET "/device-groups/$witness_stack"
    api PATCH "/device-groups/$witness_stack" "{\"row_version\": $(json_field row_version), \"location_hid\": null}"
    made="$made$status"
    api DELETE "/contact-assignments/$assignment"
    made="$made $status"
    api POST "/operators/$operator/retire" '{"row_version": 1}'
    made="$made $status"
    api POST "/contacts/$contact/retire" '{"row_version": 1}'
    made="$made $status"
    for hid in "locations/$cage" "locations/$staging" "sites/$site" "regions/$region"; do
        api GET "/$hid"
        api POST "/$hid/retire" "{\"row_version\": $(json_field row_version)}"
        made="$made $status"
    done
    api GET '/geography/tree'
    expect "pkg the items and the stack are taken out again, the assignment is removed, the operator is released, and the contact, the two locations, the site and the region are retired: the tree is empty once more" \
        "$made $status $(json 'd["roots"]')" "200 200 200 204 200 200 200 200 200 200 200 []"
}
