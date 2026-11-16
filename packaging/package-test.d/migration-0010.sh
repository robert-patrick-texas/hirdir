# shellcheck shell=bash
# shellcheck disable=SC2034,SC2154  # Read by packaging/package-test.sh, whose names these are.
#
# Migration 0010, which came with hirdir 0.8.0: circuits with their carriers, their cost
# lines, the devices they connect and the contacts they name, the contacts of a vendor,
# circuit groups, and the support weight of a place.
#
# packaging/package-test.sh reads this file when the upgrade it tests runs the
# migration, and calls the three functions below: see "what one upgrade alone has"
# there. The previous release is then at revision 0009 or before: it knows no circuit,
# no contact of a vendor and no weight of a place, and has neither of the two lists that
# the migration loads.
#
# The migration gives regions, sites and locations support_weight, each by a batch
# alter, which on SQLite makes the table anew, with its indexes, and copies its rows
# across. It creates circuits, circuit_carriers, circuit_costs, circuit_devices,
# vendor_contacts, circuit_contacts and circuit_groups, and last of the tables
# circuit_group_members, which is the one that the pass whose migration fails puts in
# its way: the places have their column and seven tables are made by then, and all of
# it has to be undone. Then it loads the circuit_type and carrier_role lists, and
# leaves alone a value that it finds in either.
#
# It changes nothing that is held: no place is given a weight, no setting is set, and
# there is no circuit and no contact of a vendor until somebody enters one. It writes no
# audit event. What reads differently is that the support weight of the capacity report
# is in its parts, the items, the places and the circuits, of which the last two count
# nothing until something is weighed; that the capacity report is kept, and is worked
# out with the other long reports when the service starts; and that the six weights are
# blank and the side a new circuit counts at is A. docs/install.md says all of it under
# "From 0.7.0 to 0.8.0", and what is said there is what is looked for here.
writes_no_event=yes
# It loads two lists beside the choices that are there.
may_add[choices]=yes
also new_columns regions 'support_weight BIGINT NULL -'
also new_columns sites 'support_weight BIGINT NULL -'
also new_columns locations 'support_weight BIGINT NULL -'

# Set by before_0010 when the previous release holds an inventory, for the other two.
weighed=""
# The location of every kind of value that before_0010 makes and retires, and the
# region from before, by its HID.
weighed_retired=""
weighed_land=""

# written_choice LIST VALUE LABEL: put a choice straight into the database of the
# previous release, as the hirdir user, with an HID made as the application makes one.
# The previous release refuses a choice in a list that it does not have.
written_choice() {
    inside runuser -u hirdir -- /opt/hirdir/python/bin/python3 -I -c '
import sqlite3, sys, uuid
from datetime import UTC, datetime

now = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")
held = sqlite3.connect("/var/lib/hirdir/hirdir.db", timeout=10)
held.execute(
    "INSERT INTO choices (hid, list, value, value_key, label, sort, active, created_at, updated_at, row_version)"
    " VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, 1)",
    (str(uuid.uuid7()), sys.argv[1], sys.argv[2], sys.argv[2].casefold(), sys.argv[3], 5, now, now),
)
held.commit()' "$1" "$2" "$3"
}

# weight_moved NAME PATH...: what the capacity report in the last response counts of
# the places and the circuits, as its active view has them, and how much its support
# weight and the row of each region named by its path have gained since the report kept
# under NAME: places_weight, circuits_weight, the gain of the whole and that of each row.
weight_moved() {
    python3 -c '
import json, sys
from decimal import Decimal

was, now = (json.load(open(path, encoding="utf-8")) for path in sys.argv[1:3])
plain = lambda number: format(number.normalize(), "f")
rows = lambda answer: {r["path"]: Decimal(r["support_weight"]) for r in answer["active"]["demand_by_region"]}
then, rows_now = rows(was), rows(now)
gained = Decimal(now["active"]["support_weight"]) - Decimal(was["active"]["support_weight"])
print(json.dumps([now["active"]["places_weight"], now["active"]["circuits_weight"], plain(gained)]
                 + [plain(rows_now[path] - then.get(path, Decimal(0))) for path in sys.argv[3:]]))' \
        "$work/kept-$1.json" "$work/body" "${@:2}"
}

# What the migration could harm, made with the previous release. What it alters, the
# regions, sites and locations, are in the inventory already from revision 0007, with
# their shipping addresses, an operator, the contacts assigned there, and from 0009
# their links: this sees that they are, and makes a location of every kind of value
# beside them, which is retired. The two lists that it loads are refused by the
# previous release, so a site's own values in them are written into its database, as
# migration-0006.sh does for conditions; and the values that the site put into the
# other lists are in the inventory already.
before_0010() {
    local made wanted open
    [ -n "$witness_entry" ] || return 0
    weighed=yes

    # The lists. The previous release has neither, and refuses a choice in each; the
    # migration is written to leave alone what it finds there, so one with the value
    # of a default under a label of the site's, and two of the site's alone, are
    # written into the database.
    api POST /choices '{"list": "circuit_type", "value": "satellite", "label": "Satellite link"}'
    made="$status $(json '[e["field"] for e in d.get("errors", [])]')"
    api POST /choices '{"list": "carrier_role", "value": "reseller", "label": "Reseller of the circuit"}'
    expect "pkg $previous_version has no circuit_type list and no carrier_role list, and refuses a choice in either" \
        "$made $status $(json '[e["field"] for e in d.get("errors", [])]')" '422 ["list"] 422 ["list"]'
    if written_choice circuit_type internet "Internet access" >/dev/null 2>&1 &&
        written_choice circuit_type satellite "Satellite link" >/dev/null 2>&1 &&
        written_choice carrier_role reseller "Reseller of the circuit" >/dev/null 2>&1; then
        pass "pkg so three choices are written into its database as a site's own: internet in the circuit_type list under a label of the site's, satellite beside it, and reseller in the carrier_role list"
    else
        fail "pkg so three choices are written into its database as a site's own: internet in the circuit_type list under a label of the site's, satellite beside it, and reseller in the carrier_role list"
    fi
    api GET /choices
    wanted='["replacement_reason:site-swap", "state_reason:site-audit"]'
    if [ -n "$witness_contracts" ]; then wanted='["capacity_category:on-call", "replacement_reason:site-swap", "state_reason:site-audit"]'; fi
    expect "pkg and the values that the site put into the other lists are there beside them, which the migration is to leave as they are" \
        "$status $(json 'sorted(c["list"] + ":" + c["value"] for c in d if c["value"] in ("site-audit", "site-swap", "on-call"))') $(json 'sorted(c["list"] + ":" + c["value"] for c in d if c["list"] in ("circuit_type", "carrier_role"))')" \
        "200 $wanted [\"carrier_role:reseller\", \"circuit_type:internet\", \"circuit_type:satellite\"]"

    # The places that the migration alters, from 0.5.0, as witness_places made them,
    # and from 0.7.0 with their links.
    [ -n "$witness_site" ] || return 0
    api GET '/regions?include_drafts=true&include_archived=true&limit=1000'
    made="$status $(json '[len(d["items"]), sum(r["ship_address1"] is not None for r in d["items"]), sum(bool(r.get("links")) for r in d["items"])]')"
    weighed_land=$(json '[r["hid"] for r in d["items"] if r["name"] == "Upgrade Land"][0]')
    api GET '/sites?include_drafts=true&include_archived=true&limit=1000'
    made="$made $(json '[len(d["items"]), sum(s["ship_same_as_address"] for s in d["items"]), sum(s["operator_hid"] is not None for s in d["items"]), sorted(s["record_status"] for s in d["items"]), sum(bool(s.get("links")) for s in d["items"])]')"
    api GET '/locations?include_drafts=true&include_archived=true&limit=1000'
    made="$made $(json '[len(d["items"]), sum(l["ship_instructions"] is not None for l in d["items"]), sum(bool(l.get("links")) for l in d["items"])]')"
    api GET '/contact-assignments?limit=1000'
    wanted="[2, 1, 0] [2, 1, 1, [\"active\", \"draft\"], 0] [3, 1, 0] [3, [\"location\", \"region\", \"site\"]]"
    if [ -n "$witness_renewed" ]; then wanted="[2, 1, 1] [2, 1, 1, [\"active\", \"draft\"], 1] [3, 1, 1] [3, [\"location\", \"region\", \"site\"]]"; fi
    expect "pkg the inventory holds what migration 0010 alters: two regions, one with a shipping address, two sites, a draft among them, one whose deliveries go to its street address and one with an operator of its own, three locations, one with instructions for deliveries, from 0.7.0 a link on one of each, and the contacts assigned at a region, a site and a location" \
        "$made $(json '[len(d["items"]), sorted({("region" if a["region_hid"] else "site" if a["site_hid"] else "location") for a in d["items"]})]')" \
        "200 $wanted"

    # A location of every kind of value beside them: a code, a street address of its
    # own and another for deliveries, with instructions, where it is on the map, and an
    # operator of its own; and retired, so that what is counted counts it as nothing.
    api GET '/operators?limit=1000'
    open=$(json '[o["hid"] for o in d["items"] if o["label"] == "UW8"][0]')
    api POST /locations "{\"name\": \"Upgrade Loading Dock\", \"site_hid\": \"$witness_site\", \"kind\": \"warehouse\", \"code\": \"UWLD\", \"address1\": \"7 Witness Road\", \"city\": \"Riverton\", \"state\": \"NY\", \"postal_code\": \"00000\", \"country\": \"US\", \"ship_address1\": \"9 Witness Road\", \"ship_city\": \"Riverton\", \"ship_postal_code\": \"00000\", \"ship_country\": \"US\", \"ship_instructions\": \"Ring at the back gate\", \"latitude\": 41, \"longitude\": -74.5, \"operator_hid\": \"$open\", \"notes\": \"Made with the release before\", \"tags\": [\"upgrade-witness\"]}"
    made="$status $(json '[d["path"], d["operator"]["label"] if d.get("operator") else None]')"
    weighed_retired=$(json_field hid)
    api POST "/locations/$weighed_retired/retire" '{"row_version": 1}'
    expect "pkg and a location of every kind of value beside them, a code, a street address, another for deliveries with instructions, a place on the map and an operator of its own, which is then retired" \
        "$made $status $(json_field record_status)" \
        '201 ["Upgrade Land > North > Upgrade Site > Upgrade Loading Dock", "UW8"] 200 retired'

    # What the previous release does not know: a weight of a place, a circuit, a contact
    # of a vendor, the report of what circuits cost, Try and what is kept. A route it
    # does not have is not found, or, asked for by POST, not allowed.
    api GET "/sites/$witness_site"
    made="$(json 'sorted(k for k in ("support_weight", "effective") if k in d)')"
    made="$made $(said_of "$weighed_land" regions '"support_weight": "1.5"')"
    for path in /circuits /circuit-groups /reports/circuit-costs POST:/reports/capacity/try /kept-answers; do
        case $path in
            POST:*) api POST "${path#POST:}" '{}' ;;
            *) api GET "$path" ;;
        esac
        case $status in 404 | 405) made="$made none" ;; *) made="$made $status" ;; esac
    done
    api GET /settings
    expect "pkg $previous_version knows no weight of a place, and refuses one; it has no circuit, no circuit group, no report of what circuits cost, no Try and nothing kept to check, and none of the six weights and no circuit_cost_side among its settings" \
        "$made $status $(json '[s["key"] for s in d if s["key"] in "'"$weight_settings"'".split()]')" \
        '[] 422 none none none none none 200 []'
    # A file of regions with a support_weight column, which the previous release does
    # not know. It is sent through nginx, which only the upgrade pass installs; the new
    # version applies it, in after_0010.
    printf 'hid,support_weight\n%s,1.5\n' "$weighed_land" >"$work/weighed.csv"
    if [ "$mode" = upgrade ]; then
        send "/imports/preview?entity=regions&file_name=weighed.csv" "$work/weighed.csv"
        expect "pkg a file of regions with a support_weight column is refused by $previous_version, for its unknown column" \
            "$status $(json 'd["errors"][0]["field"]')" "422 column"
    fi
}

# What the migration made, and what the new version says of what was carried over,
# looked at by itself with the new version serving.
changed_0010() {
    local when=$1 database=/var/lib/hirdir/hirdir.db made
    [ -n "$weighed" ] || return 0

    # What is new is empty until somebody fills it in.
    expect "pkg $when the eight tables that the migration creates are empty: circuits, circuit_carriers, circuit_costs, circuit_devices, vendor_contacts, circuit_contacts, circuit_groups and circuit_group_members" \
        "$(sqlite_value "$database" 'SELECT (SELECT count(*) FROM circuits) + (SELECT count(*) FROM circuit_carriers) + (SELECT count(*) FROM circuit_costs) + (SELECT count(*) FROM circuit_devices) + (SELECT count(*) FROM vendor_contacts) + (SELECT count(*) FROM circuit_contacts) + (SELECT count(*) FROM circuit_groups) + (SELECT count(*) FROM circuit_group_members)')" 0
    expect "pkg $when the new column holds nothing: no region, site or location has a weight of its own" \
        "$(sqlite_value "$database" 'SELECT (SELECT count(*) FROM regions WHERE support_weight IS NOT NULL) + (SELECT count(*) FROM sites WHERE support_weight IS NOT NULL) + (SELECT count(*) FROM locations WHERE support_weight IS NOT NULL)')" 0
    expect "pkg $when and no row refers to a record that is not there, in the three tables of places, which the migration may have made anew, or anywhere else" \
        "$(sqlite_text 'PRAGMA foreign_key_check' | wc -l)" 0
    made=""
    for path in '/circuits?include_drafts=true&include_archived=true&limit=1' '/circuit-groups?include_drafts=true&include_archived=true&limit=1'; do
        api GET "$path"
        made="$made$status:$(json_field total) "
    done
    api GET /reports/circuit-costs
    made="$made$status $(json '[d["totals"][k] for k in ("circuits", "cost", "monthly_cost", "annual_cost")] + [d["rows"]]')"
    api GET '/vendors?limit=1000'
    expect "pkg $when the lists of circuits and of circuit groups are there and empty, the report of what circuits cost counts nothing, and no vendor names a contact" \
        "$made $status $(json 'sorted({json.dumps(v["contacts"]) for v in d["items"]})')" \
        '200:0 200:0 200 [0, "0.00", "0.00", "0.00", []] 200 ["[]"]'

    # The places say that they have no weight, and a site that it has none in force.
    api GET '/regions?include_drafts=true&include_archived=true&limit=1000'
    made="$status $(json 'sorted({json.dumps(r["support_weight"]) for r in d["items"]})')"
    api GET '/locations?include_drafts=true&include_archived=true&limit=1000'
    made="$made $status $(json 'sorted({json.dumps(l["support_weight"]) for l in d["items"]})')"
    api GET '/sites?include_drafts=true&include_archived=true&limit=1000'
    expect "pkg $when every region, site and location from before has no weight of its own, and every site has none in force" \
        "$made $status $(json 'sorted({json.dumps([s["support_weight"], s["effective"]["support_weight"]], sort_keys=True) for s in d["items"]})')" \
        "$(if [ -n "$witness_site" ]; then echo '200 ["null"] 200 ["null"] 200 ["[null, {\"raised_from\": null, \"source\": \"none\", \"source_hid\": null, \"value\": null}]"]'; else echo '200 [] 200 [] 200 []'; fi)"

    # The settings that 0.8.0 adds are at their defaults: the six weights blank, and a
    # new circuit counts at its A side.
    api GET /settings
    expect "pkg $when the six weights are blank, at their defaults, and so changes nothing until an Admin sets one; and circuit_cost_side is a, its default" \
        "$status $(json 'sorted([s["key"], s["value"], s["default"], s["is_default"]] for s in d if s["key"] in ("default_item_weight", "minimum_item_weight", "default_site_weight", "minimum_site_weight", "default_circuit_weight", "minimum_circuit_weight", "circuit_cost_side"))')" \
        '200 [["circuit_cost_side", "a", "a", true], ["default_circuit_weight", null, null, true], ["default_item_weight", null, null, true], ["default_site_weight", null, null, true], ["minimum_circuit_weight", null, null, true], ["minimum_item_weight", null, null, true], ["minimum_site_weight", null, null, true]]'
    api GET "$every_item"
    made="$status $(json 'sorted({json.dumps([i["effective"]["support_weight"]["raised_from"], i["effective"]["support_weight"]["source"] == "setting"]) for i in d["items"]})')"
    api GET "/items/$witness_full"
    expect "pkg $when so no item has its weight from a setting or raised to a minimum, and the item from before is connected to no circuit" \
        "$made $status $(json_field circuits)" '200 ["[null, false]"] 200 []'

    # The capacity report: the support weight in its parts, all of it that of the items,
    # as before, in each view.
    api GET /reports/capacity
    expect "pkg $when GET /reports/capacity gives its support weight in its parts: all of it is the items', and the places and the circuits count nothing, with nothing counted at a default or raised to a minimum, with and without the drafts" \
        "$status $(json '[[d[v]["support_weight"] == d[v]["items_weight"], d[v]["places_weight"], d[v]["circuits_weight"], d[v]["defaulted"], d[v]["raised"]] for v in ("active", "with_drafts")]')" \
        '200 [[true, "0", "0", {"circuits": 0, "items": 0, "sites": 0}, {"circuits": 0, "items": 0, "sites": 0}], [true, "0", "0", {"circuits": 0, "items": 0, "sites": 0}, {"circuits": 0, "items": 0, "sites": 0}]]'
    # It is kept, and the service, when it started, worked out the four long reports and
    # kept them, which nothing written since has made stale.
    api GET /kept-answers
    expect "pkg $when GET /kept-answers lists, beside what has been asked since, the four long reports that the service worked out when it started and keeps: the capacity report, the coverage report, the renewal worklist and the renewal alert" \
        "$status $(json 'sorted({e["report"] for e in d} & {"capacity", "coverage", "renewals", "renewal_alert"})')" \
        '200 ["capacity", "coverage", "renewal_alert", "renewals"]'

    # The two lists are loaded beside what the site had put into them.
    api GET '/choices?list=circuit_type'
    made="$status $(json '" ".join(sorted(c["value"] + "=" + c["label"].replace(" ", "_") for c in d))')"
    api GET '/choices?list=carrier_role'
    expect "pkg $when the circuit_type list holds its seven defaults and the site's own, with internet there once, under the label the site gave it, and the carrier_role list its four and the site's own" \
        "$made $status $(json '" ".join(sorted(c["value"] + "=" + c["label"].replace(" ", "_") for c in d))')" \
        "200 dark_fiber=Dark_fiber internet=Internet_access mpls=MPLS other=Other point_to_point=Point-to-point satellite=Satellite_link voice=Voice wavelength=Wavelength 200 cross_connect=Cross-connect_provider last_mile=Last_mile local_exchange=Local_exchange_carrier other=Other reseller=Reseller_of_the_circuit"
}

# What is new, tried on what was carried over.
after_0010() {
    local made land north building hall pat telecom exchange circuit fiber group vendor_link audited
    [ -n "$weighed" ] && [ -n "$witness_site" ] || return 0
    land=$weighed_land
    api GET '/locations?include_drafts=true&limit=1000'
    building=$(json '[l["hid"] for l in d["items"] if l["name"] == "Building 7"][0]')
    hall=$(json '[l["hid"] for l in d["items"] if l["name"] == "Hall"][0]')
    api GET '/contacts?limit=1000'
    pat=$(json '[c["hid"] for c in d["items"] if c["email"] == "upgrade.pat@example.net"][0]')

    # A place from before is given a weight: the region by the file that the previous
    # release refused, and the site by hand. The capacity report counts both as demand,
    # in the row of each region at or above them.
    api GET /reports/capacity
    keep capacity-unweighed
    send "/imports/preview?entity=regions&file_name=weighed.csv" "$work/weighed.csv"
    made="$status $(job_counts)"
    apply_job "/imports/$(json 'd["job"]["hid"]')/apply"
    made="$made $status $(job_counts)"
    api GET "/regions/$land"
    made="$made $(json_field support_weight) $(said_of "$witness_site" sites '"support_weight": "2"')"
    api GET "/sites/$witness_site"
    made="$made $(json '[d["support_weight"], d["effective"]["support_weight"]["value"], d["effective"]["support_weight"]["source"]]')"
    api GET /reports/capacity
    expect "pkg the region from before is given a weight by the file of regions that $previous_version refused, previewed and applied, and the site from before one by hand, which it has in force as its own: GET /reports/capacity counts 3.5 of places, 3.5 more of the whole, 3.5 more in the row of the region and 2 more in that of the region beneath it, where the site is" \
        "$made $(weight_moved capacity-unweighed 'Upgrade Land' 'Upgrade Land > North')" \
        '201 ["previewed", 1, 0, 1, 0, 0] 202 ["applied", 1, 0, 1, 0, 0] 1.5 200 ["2", "2", "own"] ["3.5", "0", "3.5", "3.5", "2"]'

    # A circuit between two locations from before, the room and the hall of the draft
    # site, with the item from before in the room on its A side. Its carrier, a vendor
    # that is new, names an account manager, a contact from before; another carrier is
    # the local exchange, with a number of its own; three cost lines, one of the local
    # exchange's and a credit that ends.
    api POST /vendors '{"name": "Upgrade Witness Telecom", "notes": "A fictional carrier"}'
    made=$status
    telecom=$(json_field hid)
    api POST /vendors '{"name": "Upgrade Witness Exchange", "notes": "A fictional local exchange carrier"}'
    made="$made $status"
    exchange=$(json_field hid)
    api POST "/vendors/$telecom/contacts" "{\"contact_hid\": \"$pat\", \"role\": \"account_manager\"}"
    made="$made $status $(json '[d["role"], d["priority"], d["contact"]["name"]]')"
    vendor_link=$(json_field hid)
    api POST /circuits "{\"name\": \"Upgrade Witness Link\", \"enterprise_circuit_id\": \"UW-EC-0001\", \"circuit_type\": \"point_to_point\", \"port_mbps\": \"1000\", \"a_location_hid\": \"$witness_room\", \"z_location_hid\": \"$hall\", \"carrier_hid\": \"$telecom\", \"carrier_circuit_number\": \"UWT/0001/000/UWTL\", \"owner_hid\": \"$witness_owner\"}"
    made="$made $status $(json '[d["cost_side"], d["cost_site_path"], d["a_side"]["path"], d["z_side"]["path"], d["speed"]]')"
    circuit=$(json_field hid)
    api POST "/circuits/$circuit/carriers" "{\"vendor_hid\": \"$exchange\", \"role\": \"local_exchange\", \"circuit_number\": \"UWX-0001\"}"
    made="$made $status"
    api POST "/circuits/$circuit/costs" '{"description": "Port", "monthly_cost": "800.00"}'
    made="$made $status"
    api POST "/circuits/$circuit/costs" "{\"description\": \"Local loop\", \"monthly_cost\": \"150.00\", \"vendor_hid\": \"$exchange\"}"
    made="$made $status"
    api POST "/circuits/$circuit/costs" "{\"description\": \"Promotional credit\", \"monthly_cost\": \"-50.00\", \"ends_on\": \"$(day_from_today 100)\"}"
    made="$made $status"
    api POST "/circuits/$circuit/devices" "{\"devices\": [{\"item_hid\": \"$witness_full\", \"side\": \"a\"}]}"
    expect "pkg a circuit is entered between two locations from before, the room and the hall of the draft site, with a new carrier that names a contact from before as its account manager: it counts at its A side, the site of the room, as the setting says unless an Admin changes it; the local exchange is a second carrier with a number of its own; three cost lines, one the local exchange bills and a credit that ends; and the item from before in the room is connected on the A side" \
        "$made $status" \
        '201 201 201 ["account_manager", 1, "Upgrade Pat"] 201 ["a", "Upgrade Land > North > Upgrade Site", "Upgrade Land > North > Upgrade Site > Building 7 > Room 701", "Upgrade Land > North > Upgrade New Site > Hall", "1G"] 201 201 201 201 201'
    api GET "/circuits/$circuit"
    made="$status $(json '[[[c["vendor"], c["role"], c["circuit_number"]] for c in d["carriers"]], d["monthly_cost"], d["annual_cost"], d["in_service"], [[x["item_hid"] == "'"$witness_full"'", x["side"]] for x in d["devices"]]]')"
    made="$made $(json '[d["effective"]["account_managers"]["source"], [c["contact"]["name"] for c in d["effective"]["account_managers"]["value"]], [[e["role"], e["source"], [c["contact"]["name"] for c in e["value"]]] for e in d["effective"]["site_contacts"]["a"]]]')"
    api GET "/items/$witness_full"
    expect "pkg it costs 900.00 a month, 10800.00 a year, and is in service; it has its carrier's account manager, from the vendor, and the technical contact of the region from before as the site contact of its A side, resolved from the room's places; and the item from before shows the circuit, on its A side" \
        "$made $(json '[[c["hid"] == "'"$circuit"'", c["side"]] for c in d["circuits"]]')" \
        '200 [[["Upgrade Witness Exchange", "local_exchange", "UWX-0001"]], "900.00", "10800.00", true, [[true, "a"]]] ["vendor", ["Upgrade Pat"], [["technical", "region", ["Upgrade Pat"]]]] [[true, "a"]]'

    # With the setting made z, a new circuit counts at its Z side, and the one there is
    # does not change; set back to a. A circuit group of the two; and what they cost.
    api GET /settings
    api PUT /settings/circuit_cost_side "{\"row_version\": $(json '[s["row_version"] for s in d if s["key"] == "circuit_cost_side"][0]'), \"value\": \"z\"}"
    made="$status $(json_field value)"
    api POST /circuits "{\"name\": \"Upgrade Witness Dark Fiber\", \"circuit_type\": \"dark_fiber\", \"port_mbps\": \"10000\", \"a_location_hid\": \"$building\", \"z_location_hid\": \"$hall\", \"production\": false, \"carrier_hid\": \"$exchange\"}"
    made="$made $status $(json '[d["cost_side"], d["cost_site_path"]]')"
    fiber=$(json_field hid)
    api POST "/circuits/$fiber/costs" '{"description": "Fiber lease", "monthly_cost": "300.00"}'
    made="$made $status"
    api GET "/circuits/$circuit"
    made="$made $(json_field cost_side)"
    api GET /settings
    api PUT /settings/circuit_cost_side "{\"row_version\": $(json '[s["row_version"] for s in d if s["key"] == "circuit_cost_side"][0]'), \"value\": null}"
    made="$made $status $(json_field value)"
    api POST /circuit-groups "{\"name\": \"Upgrade Witness Links\", \"owner_hid\": \"$witness_owner\"}"
    made="$made $status"
    group=$(json_field hid)
    api POST "/circuit-groups/$group/members" "{\"circuit_hids\": [\"$circuit\", \"$fiber\"]}"
    made="$made $status"
    api GET "/circuit-groups/$group"
    expect "pkg with circuit_cost_side made z by an Admin, a new circuit, a dark fiber from the building from before to the hall, counts at its Z side, the draft site, and the circuit there was still counts at its A side; set back, the setting is a; the two are put into a circuit group, which counts both as in service and what both cost, each once" \
        "$made $(json '[d["circuits"], d["in_service"], d["monthly_cost"], d["annual_cost"]]')" \
        '200 z 201 ["z", "Upgrade Land > North > Upgrade New Site"] 201 a 200 a 201 201 [2, 2, "1200.00", "14400.00"]'
    api GET '/reports/circuit-costs?by=carrier'
    made="$status $(json '[[d["totals"][k] for k in ("circuits", "monthly_cost", "annual_cost")], sorted([r["label"], r["circuits"], r["monthly_cost"], r["annual_cost"]] for r in d["rows"])]')"
    api GET '/reports/circuit-costs?by=site'
    made="$made $(json 'sorted([r["label"], r["circuits"], r["monthly_cost"], r["annual_cost"]] for r in d["rows"])')"
    api GET '/reports/circuit-costs?by=group'
    expect "pkg GET /reports/circuit-costs counts the two by the carrier that bills each line, by the site each counts at, and by their group: 1200.00 a month in all, 14400.00 a year" \
        "$made $(json 'sorted([r["label"], r["circuits"], r["monthly_cost"], r["annual_cost"]] for r in d["rows"])')" \
        '200 [[2, "1200.00", "14400.00"], [["Upgrade Witness Exchange", 2, "450.00", "5400.00"], ["Upgrade Witness Telecom", 1, "750.00", "9000.00"]]] [["Upgrade Land > North > Upgrade New Site", 1, "300.00", "3600.00"], ["Upgrade Land > North > Upgrade Site", 1, "900.00", "10800.00"]] [["Upgrade Witness Links", 2, "1200.00", "14400.00"]]'

    # The capacity report with a default weight set by an Admin: the two circuits, which
    # have none of their own, count at it, in the row of each region at or above the
    # site each counts at. Then a Try, which saves nothing and audits nothing.
    api GET /settings
    api PUT /settings/default_circuit_weight "{\"row_version\": $(json '[s["row_version"] for s in d if s["key"] == "default_circuit_weight"][0]'), \"value\": 0.5}"
    made="$status $(json '[d["value"], d["is_default"]]')"
    api GET "/circuits/$circuit"
    made="$made $(json '[d["effective"]["support_weight"][k] for k in ("value", "source")]')"
    api GET /reports/capacity
    made="$made $(weight_moved capacity-unweighed 'Upgrade Land' 'Upgrade Land > North') $(json '[d["active"]["defaulted"], d["active"]["raised"]]')"
    keep capacity-weighed
    api GET '/audit-events?limit=1'
    audited=$(json_field total)
    api POST /reports/capacity/try '{"default_circuit_weight": null, "default_site_weight": "1", "minimum_site_weight": "3"}'
    made="$made | $status $(python3 -c '
import json, sys
kept, tried = (json.load(open(path, encoding="utf-8")) for path in sys.argv[1:3])
print(json.dumps([tried["in_force"] == kept] + [[tried["tried"][v][k] for k in ("places_weight", "circuits_weight")] + [tried["tried"][v]["defaulted"]["sites"], tried["tried"][v]["raised"]["sites"]] for v in ("active", "with_drafts")] + [sorted(tried["parameters"]["changed"])]))' "$work/kept-capacity-weighed.json" "$work/body")"
    api GET '/audit-events?limit=1'
    made="$made $(json_field total)"
    api GET /settings
    expect "pkg default_circuit_weight set to 0.5: the circuit counts at it, from the setting, and GET /reports/capacity counts 1 of circuits, the two of them, beside the 3.5 of places, in the rows of both regions; a Try of no circuit weight, a site weight of 1 and a minimum of 3 answers the report in force as it is, and as it would be: no circuit weight, the site from before raised from 2 to 3, and with the drafts the draft site at the default raised to 3 as well; nothing is saved, and the audit trail has no event more ($audited)" \
        "$made $(json 'sorted([s["key"], s["value"]] for s in d if s["key"] in ("default_circuit_weight", "default_site_weight", "minimum_site_weight"))')" \
        "200 [0.5, false] [\"0.5\", \"setting\"] [\"3.5\", \"1\", \"4.5\", \"4.5\", \"3\"] [{\"circuits\": 2, \"items\": 0, \"sites\": 0}, {\"circuits\": 0, \"items\": 0, \"sites\": 0}] | 200 [true, [\"4.5\", \"0\", 0, 1], [\"7.5\", \"0\", 1, 2], [\"default_circuit_weight\", \"default_site_weight\", \"minimum_site_weight\"]] $audited [[\"default_circuit_weight\", 0.5], [\"default_site_weight\", null], [\"minimum_site_weight\", null]]"

    # The check of what is kept: each kept answer worked out anew is what was kept, and
    # the check is an event of its own, which leaves them good.
    api GET /reports/capacity
    api POST /kept-answers/check
    made="$status $(json '[d["checked"] >= 1, d["differed"]]')"
    api GET '/audit-events?limit=1'
    made="$made $(json '[d["items"][0]["action"], d["items"][0]["record_type"]]')"
    api GET /kept-answers
    expect "pkg POST /kept-answers/check, by the Admin, works out each kept answer anew, and none differs from what was kept; it is an audit event, kept_answers_checked, and the capacity report is kept still" \
        "$made $status $(json '"capacity" in {e["report"] for e in d}')" \
        '200 [true, []] ["kept_answers_checked", "kept_answers"] 200 true'

    # Taken out again, so that the rest of this pass starts from reports as empty as
    # those of a new installation: the weight of circuits is blank once more, the
    # circuits and their group are retired, and the naming of the carrier's account
    # manager is removed. The places keep their weights until they are retired with the
    # rest of what was carried over.
    api GET /settings
    api PUT /settings/default_circuit_weight "{\"row_version\": $(json '[s["row_version"] for s in d if s["key"] == "default_circuit_weight"][0]'), \"value\": null}"
    made=$status
    for hid in "$circuit" "$fiber"; do
        api GET "/circuits/$hid"
        api POST "/circuits/$hid/retire" "{\"row_version\": $(json_field row_version)}"
        made="$made $status"
    done
    api GET "/circuit-groups/$group"
    api POST "/circuit-groups/$group/retire" "{\"row_version\": $(json_field row_version)}"
    made="$made $status"
    api DELETE "/vendors/$telecom/contacts/$vendor_link"
    made="$made $status"
    api GET /reports/circuit-costs
    made="$made $(json '[d["totals"]["circuits"], d["totals"]["monthly_cost"]]')"
    api GET /reports/capacity
    expect "pkg the weight of circuits is blank again, the two circuits and their group are retired, and the account manager of the carrier is removed: no circuit costs anything, and the capacity report counts no circuit, and the 3.5 of places still" \
        "$made $(json '[d["active"]["circuits_weight"], d["active"]["places_weight"]]')" \
        '200 200 200 200 204 [0, "0.00"] ["0", "3.5"]'
}
