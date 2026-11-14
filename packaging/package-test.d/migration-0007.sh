# shellcheck shell=bash
# shellcheck disable=SC2034,SC2154  # Read by packaging/package-test.sh, whose names these are.
#
# Migration 0007, which came with hirdir 0.5.0: regions, sites, locations, contacts and
# the members of owners.
#
# packaging/package-test.sh reads this file when the upgrade it tests runs the
# migration, and calls the three functions below: see "what one upgrade alone has"
# there. The previous release is then at revision 0006 or before: it knows no place and
# no contact, and an item of it may be with an owner outside the team with no reason
# given.
#
# The migration creates regions, sites, locations, contacts and contact_assignments,
# makes the items and the device_groups tables anew, each with a column that refers to
# a location, and items with the reason for an owner outside the team. It loads the
# contact_role and location_kind lists, and leaves alone what it finds in them. Last of
# all it creates owner_members, which is the table that the pass whose migration fails
# puts in its way: everything else is done by then. It changes no record there is and
# writes no audit event. docs/install.md says so under "From 0.4.2 to 0.5.0", and what
# is said there is what is looked for here.
writes_no_event=yes
# It loads the two lists beside the choices that are there.
may_add[choices]=yes
new_columns[items]='owner_exception_reason TEXT NULL -
location_hid VARCHAR(36) NULL -'
new_keys[items]='foreign key location_hid to locations.hid
index ix_items_location_hid on location_hid unique=0 origin=c partial=0'
new_columns[device_groups]='location_hid VARCHAR(36) NULL -'
new_keys[device_groups]='foreign key location_hid to locations.hid
index ix_device_groups_location_hid on location_hid unique=0 origin=c partial=0'

outside_owner=""
outside_item=""
money_before=""

# What the migration could harm, made with the previous release: an item that is with an
# owner outside the team already, with a minor item in it, and choices of a site's own
# in the two lists that the migration loads.
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
    expect "pkg $previous_version holds an owner outside the team, an item that is with it and a minor item in that item: it asks for no reason, and has nowhere to keep one" \
        "$made $status $not_made" "201 201 201 0"

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
    expect "pkg $when the five tables of places and contacts and the table of the members of owners are empty" \
        "$(sqlite_value "$database" 'SELECT (SELECT count(*) FROM regions) + (SELECT count(*) FROM sites) + (SELECT count(*) FROM locations) + (SELECT count(*) FROM contacts) + (SELECT count(*) FROM contact_assignments) + (SELECT count(*) FROM owner_members)')" 0
    expect "pkg $when the new columns hold nothing: no item and no device group has a location, and no item a reason for its owner" \
        "$(sqlite_value "$database" 'SELECT (SELECT count(*) FROM items WHERE location_hid IS NOT NULL OR owner_exception_reason IS NOT NULL) + (SELECT count(*) FROM device_groups WHERE location_hid IS NOT NULL)')" 0
    api GET "$every_group"
    made=$(json 'sorted({json.dumps([g["location_hid"], g["location"]]) for g in d["items"]})')
    api GET "$every_item"
    expect "pkg $when no device group and no item is anywhere, by what each says of itself" \
        "$made $(json 'sorted({json.dumps([i["location_hid"], i["location"], i["effective"]["location_hid"]["value"]]) for i in d["items"]})')" \
        '["[null, null]"] ["[null, null, null]"]'
    made=$(json_field total)
    api GET '/geography/tree?include_archived=true&include_drafts=true'
    expect "pkg $when the tree of places is empty, and every item there is, $made of them, is counted as nowhere" \
        "$status $(json '[d["roots"], d["hidden"]["items"], d["unplaced"] == d["totals"], d["totals"]["items"]]')" \
        "200 [[], 0, true, $made]"

    # An item that was with an owner outside the team is marked as an exception, with
    # no reason, and so is the minor item in it, which has its owner from it.
    api GET '/items?filter=owner_exception:eq:true&include_archived=true&include_drafts=true&sort=serial_number'
    expect "pkg $when GET /items?filter=owner_exception:eq:true lists the item that was with an owner outside the team, and the minor item in it, each marked and with no reason, and no other" \
        "$status $(json '[[i["serial_number"], i["owner_exception"], i["owner_exception_reason"]] for i in d["items"]]')" \
        '200 [["UWN0000E001", true, null], ["UWN0000E002", true, null]]'
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
    local made region site cage contact assignment row_version
    [ -n "$outside_item" ] || return 0

    # An export of the item that is with an owner outside the team is imported back:
    # nothing is changed by it, and no item is given an owner, so nothing is asked.
    api POST /exports '{"entity": "items", "format": "csv", "own_values": true, "filter": "serial_number:glob:UWN0000E00*", "sort": ["depth"]}'
    cp "$work/body" "$work/outside.csv"
    send "/imports/preview?entity=items&file_name=outside.csv" "$work/outside.csv"
    expect "pkg an export of the item that was with an owner outside the team, and of the minor item in it, is imported back as it is: each row finds its record unchanged, and no reason is asked for, because no item is given an owner" \
        "$status $(job_counts) $(json '[[r["outcome"], [x["field"] for x in r["reasons"]]] for r in d["rows"] if r["outcome"] != "unchanged"]')" \
        '201 ["previewed", 2, 0, 0, 2, 0] []'

    # The item that is with an owner outside the team is changed in another field, and
    # no reason is asked for. The reason is asked for when an item is given such an owner.
    api GET "/items/$outside_item"
    api PATCH "/items/$outside_item" "{\"row_version\": $(json_field row_version), \"comments\": \"Seen after the upgrade\"}"
    expect "pkg the item that was with an owner outside the team is changed in another field, and no reason is asked for: it stays marked, with none" \
        "$status $(json '[d["comments"], d["owner_exception"], d["owner_exception_reason"]]')" \
        '200 ["Seen after the upgrade", true, null]'
    api GET "/items/$witness_item"
    row_version=$(json_field row_version)
    api PATCH "/items/$witness_item" "{\"row_version\": $row_version, \"owner_hid\": \"$outside_owner\"}"
    made="$status $(json '[e["field"] for e in d["errors"]]')"
    api PATCH "/items/$witness_item" "{\"row_version\": $row_version, \"owner_hid\": \"$outside_owner\", \"owner_exception_reason\": \"Mounted behind their badge readers\"}"
    expect "pkg an item from before is given that owner: refused with no reason, and taken and marked with one" \
        "$made $status $(json '[d["owner_exception"], d["owner_exception_reason"]]')" \
        '422 ["owner_exception_reason"] 200 [true, "Mounted behind their badge readers"]'

    # A place is made, of the kind that the site had entered before the upgrade, and a
    # contact is given the role of the site's own at it.
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

    # An item and a group from before are put there by the two files with a location
    # column that the previous release refused.
    send "/imports/preview?entity=items&file_name=placed.csv" "$work/placed.csv"
    made="$status $(job_counts)"
    api POST "/imports/$(json 'd["job"]["hid"]')/apply"
    made="$made $status $(job_counts)"
    send "/imports/preview?entity=device_groups&file_name=placed-groups.csv" "$work/placed-groups.csv"
    api POST "/imports/$(json 'd["job"]["hid"]')/apply"
    made="$made | $status $(job_counts)"
    api GET "/device-groups/$witness_stack"
    made="$made $(json 'd["location"]["path"]')"
    api GET "/items/$witness_item"
    expect "pkg the two files with a location column that $previous_version refused are previewed and applied: the item is at that location, and so is the first stack" \
        "$made | $(json '[d["location"]["path"], d["effective"]["location_hid"]["source"]]')" \
        '201 ["previewed", 1, 0, 1, 0, 0] 200 ["applied", 1, 0, 1, 0, 0] | 200 ["applied", 1, 0, 1, 0, 0] Upgrade Witness Region > Upgrade Witness Site > Upgrade Witness Cage | ["Upgrade Witness Region > Upgrade Witness Site > Upgrade Witness Cage", "own"]'
    api POST /exports '{"entity": "items", "format": "csv", "own_values": true}'
    made=$(table '["location" in head, [r["location"] for r in rows if r["serial_number"] == "UWN0000X001"]]')
    authorized GET "$prefix/api/v1/items" --get --data-urlencode 'filter=location:within:Upgrade Witness Region'
    expect "pkg an export of the columns that can be set writes the location, and the item list finds the item within the region" \
        "$made $status $(json '[i["serial_number"] for i in d["items"]]')" \
        '[true, ["Upgrade Witness Region > Upgrade Witness Site > Upgrade Witness Cage"]] 200 ["UWN0000X001"]'
    api GET '/geography/tree'
    expect "pkg GET /geography/tree counts it at the location, the site and the region, and what is in the tree, what is nowhere and what is hidden add up to the totals" \
        "$status $(json '(lambda walk: [walk(walk, d["roots"][0]), d["roots"][0]["items"] + d["unplaced"]["items"] + d["hidden"]["items"] == d["totals"]["items"]])(lambda walk, n: [n["name"], n["items"]] + [walk(walk, c) for c in n["children"]])')" \
        '200 [["Upgrade Witness Region", 1, ["Upgrade Witness Site", 1, ["Upgrade Witness Cage", 1]]], true]'

    # Taken out again, so that the rest of this pass starts from a tree as empty as a
    # new installation's. A place is retired when nothing is in it.
    api GET "/items/$witness_item"
    api PATCH "/items/$witness_item" "{\"row_version\": $(json_field row_version), \"location_hid\": null}"
    made=$status
    api GET "/device-groups/$witness_stack"
    api PATCH "/device-groups/$witness_stack" "{\"row_version\": $(json_field row_version), \"location_hid\": null}"
    made="$made $status"
    api DELETE "/contact-assignments/$assignment"
    made="$made $status"
    api POST "/contacts/$contact/retire" '{"row_version": 1}'
    made="$made $status"
    api POST "/locations/$cage/retire" '{"row_version": 1}'
    made="$made $status"
    api POST "/sites/$site/retire" '{"row_version": 1}'
    made="$made $status"
    api POST "/regions/$region/retire" '{"row_version": 1}'
    made="$made $status"
    api GET '/geography/tree'
    expect "pkg the item and the stack are taken out again, the assignment is removed, and the contact, the location, the site and the region are retired: the tree is empty once more" \
        "$made $status $(json 'd["roots"]')" "200 200 204 200 200 200 200 200 []"
}
