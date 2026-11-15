# shellcheck shell=bash
# shellcheck disable=SC2034,SC2154  # Read by packaging/package-test.sh, whose names these are.
#
# Migration 0008, which came with hirdir 0.6.0: support agreements, contracts and what
# they cover, purchase requests and their lines, external systems and registrations,
# and capacity lines.
#
# packaging/package-test.sh reads this file when the upgrade it tests runs the
# migration, and calls the three functions below: see "what one upgrade alone has"
# there. The previous release is then at revision 0007 or before: it knows no contract,
# no purchase, no external system and no capacity line.
#
# The migration creates agreements, contracts, contract_coverage, purchase_requests
# and purchase_lines, and then makes the items table anew, with one column more: the
# purchase line an item arrived on. It creates external_systems and registrations,
# loads the capacity_category list, and leaves alone what it finds in it. Last of all
# it creates capacity_lines, which is the table that the pass whose migration fails
# puts in its way: everything else is done by then, the items table made anew among
# it. It changes no record there is and writes no audit event. docs/install.md says so
# under "From 0.5.0 to 0.6.0", and what is said there is what is looked for here.
writes_no_event=yes
# It loads the list beside the choices that are there.
may_add[choices]=yes
# Put after what an earlier migration of the upgrade adds, where there is one.
also new_columns items 'purchase_line_hid VARCHAR(36) NULL -'
also new_keys items 'foreign key purchase_line_hid to purchase_lines.hid
index ix_items_purchase_line_hid on purchase_line_hid unique=0 origin=c partial=0'

money_made=""
by_contract_before=""

# What the migration could harm, made with the previous release: choices of a site's
# own in the list that the migration loads. What it rebuilds, the items table, is in
# the inventory already, with every kind of value, and from revision 0007 with a
# location, a planned location and an operator on some of its rows.
before_0008() {
    local made
    [ -n "$witness_entry" ] || return 0
    money_made=yes

    # The previous release does not use the list, and takes a choice in it all the
    # same. One is the site's alone, and one has the value of a default under a label
    # of the site's: the migration is to leave both as they are.
    api POST /choices '{"list": "capacity_category", "value": "on-call", "label": "On-call rota"}'
    made=$status
    api POST /choices '{"list": "capacity_category", "value": "staff", "label": "Our own people"}'
    expect "pkg two choices of a site's own in the capacity_category list, which $previous_version does not use: one that is the site's alone, and one with the value of a default under a label of the site's" \
        "$made $status" "201 201"

    # What answers differently afterwards.
    api GET '/reports/summary?by=contract'
    by_contract_before="$status $(json 'd["errors"][0]["field"]')"
    api GET '/contracts'
    made=$status
    api GET "/items/$witness_item"
    expect "pkg $previous_version knows no contract: GET /contracts is not found, a summary by contract is refused, and the record of an item says nothing of cover, of registrations or of a purchase line" \
        "$made $by_contract_before $(json 'sorted(k for k in ("covered", "covered_until", "coverage", "registrations", "purchase_line_hid", "purchase_line") if k in d)')" \
        "404 422 query.by []"
    # A file of items with a purchase_line column, which the previous release does not
    # know. It is sent through nginx, which only the upgrade pass installs.
    if [ "$mode" = upgrade ]; then
        printf 'hid,purchase_line\n%s,UW-REQ-0001/1\n' "$witness_item" >"$work/arrived.csv"
        send "/imports/preview?entity=items&file_name=arrived.csv" "$work/arrived.csv"
        expect "pkg a file of items with a purchase_line column is refused by $previous_version, for its unknown column" \
            "$status $(json 'd["errors"][0]["field"]')" "422 column"
    fi
}

# What the migration made, and what the new version says of what was carried over,
# looked at by itself with the new version serving.
changed_0008() {
    local when=$1 database=/var/lib/hirdir/hirdir.db made name in_service weight
    [ -n "$money_made" ] || return 0

    # What is new is empty until somebody fills it in.
    expect "pkg $when the eight tables that the migration creates are empty: agreements, contracts, contract_coverage, purchase_requests, purchase_lines, external_systems, registrations and capacity_lines" \
        "$(sqlite_value "$database" 'SELECT (SELECT count(*) FROM agreements) + (SELECT count(*) FROM contracts) + (SELECT count(*) FROM contract_coverage) + (SELECT count(*) FROM purchase_requests) + (SELECT count(*) FROM purchase_lines) + (SELECT count(*) FROM external_systems) + (SELECT count(*) FROM registrations) + (SELECT count(*) FROM capacity_lines)')" 0
    expect "pkg $when the new column holds nothing: no item arrived on a purchase line" \
        "$(sqlite_value "$database" 'SELECT count(*) FROM items WHERE purchase_line_hid IS NOT NULL')" 0
    made=""
    for name in agreements contracts contract-coverage purchase-requests purchase-lines external-systems registrations capacity-lines; do
        api GET "/$name?include_drafts=true&include_archived=true&limit=1"
        made="$made$status:$(json_field total) "
    done
    expect "pkg $when and each of the eight lists is there and empty: the agreements, the contracts, their coverage, the purchase requests, their lines, the external systems, the registrations and the capacity lines" \
        "$made" "200:0 200:0 200:0 200:0 200:0 200:0 200:0 200:0 "
    api GET "$every_group"
    made=$(json 'sorted({json.dumps(g["registrations"]) for g in d["items"]})')
    api GET "$every_item"
    expect "pkg $when no item is under a contract, arrived on a purchase line or is registered anywhere, and no device group is registered, by what each says of itself" \
        "$made $(json 'sorted({json.dumps([i[k] for k in ("covered", "covered_until", "contract_count", "coverage", "registrations", "group_registrations", "purchase_line_hid", "purchase_line")]) for i in d["items"]})')" \
        '["[]"] ["[false, null, 0, [], [], [], null, null]"]'

    # The coverage report: every major item in service has no cover, which is true
    # until the contracts are entered. Which items are in service is read from what
    # the previous release said of each.
    in_service=$(python3 -c '
import json, sys
items = json.load(open(sys.argv[1], encoding="utf-8"))["items"]
print(sum(1 for i in items if i["is_major"] and i["record_status"] == "active"
          and i["effective"]["lifecycle_state"]["value"] in ("Assigned", "Test", "Prod", "Down")))' "$work/kept-items.json")
    # The counts that 0.6.0 has, and from 0.7.0 the items that are not to be renewed,
    # which are none: no model or item from before is flagged.
    api GET /reports/coverage
    expect "pkg $when GET /reports/coverage counts every major item that $previous_version had in Assigned, Test, Prod or Down, $in_service of them, as in service with no cover, and nothing as covered, as out of service under a contract, as running out, as under more than one contract, as under a renewal that is pending or as not to be renewed; and no contract has lapsed" \
        "$status $(json '[d["service_states"], {k: d["totals"][k] for k in ("covered", "expiring", "in_service", "out_of_service", "overlapping", "renewal_pending", "uncovered")}, d["totals"].get("not_renewed", 0), d["lapsed_contracts"]["count"]]')" \
        "200 [[\"Assigned\", \"Test\", \"Prod\", \"Down\"], {\"covered\": 0, \"expiring\": 0, \"in_service\": $in_service, \"out_of_service\": 0, \"overlapping\": 0, \"renewal_pending\": 0, \"uncovered\": $in_service}, 0, 0]"
    api GET /settings
    expect "pkg $when the one setting more, service_states, is at its default: Assigned, Test, Prod and Down" \
        "$status $(json '[[s["value"], s["is_default"]] for s in d if s["key"] == "service_states"]')" \
        '200 [[["Assigned", "Test", "Prod", "Down"], true]]'
    api GET '/reports/summary?by=contract'
    expect "pkg $when GET /reports/summary?by=contract, which $previous_version refused, has one row, of what no contract covers, which holds the items of the totals" \
        "$status $(json '[d["by"], [[r["key"], r["items"] == d["totals"]["items"]] for r in d["rows"]]]')" \
        '200 ["contract", [[null, true]]]'

    # The capacity report: the support weight of the inventory as demand, at 300 to
    # the resource unit, and no supply. The support weight is the one that the
    # previous release counted.
    weight=$(python3 -c 'import json, sys; print(json.loads(sys.argv[1])[3])' "$counted_before")
    api GET /reports/capacity
    expect "pkg $when GET /reports/capacity shows the support weight of the inventory, $weight as $previous_version counted it, as demand, a three-hundredth of it, with no other demand, no supply and no line in any category" \
        "$status $(json '[float(d["active"]["support_weight"]), d["weight_per_resource_unit"], d["active"]["infrastructure_demand"] == d["active"]["demand"], abs(float(d["active"]["demand"]) - float(d["active"]["support_weight"]) / 300) <= 0.005, d["active"]["other_demand"], d["active"]["supply"], float(d["active"]["balance"]) == -float(d["active"]["demand"]), sum(c["lines"] for c in d["active"]["by_category"]), d["with_drafts"]["supply"]]')" \
        "200 [$weight, \"300\", true, true, \"0\", \"0\", true, 0, \"0\"]"

    # The list is loaded beside what the site had in it.
    api GET '/choices?list=capacity_category'
    expect "pkg $when the capacity_category list holds its six defaults and the site's own, with staff there once, under the label the site gave it" \
        "$status $(json '" ".join(sorted(c["value"] + "=" + c["label"].replace(" ", "_") for c in d))')" \
        "200 on-call=On-call_rota other_work=Other_work professional_services=Professional_services services=Services smart_hands=Smart_hands staff=Our_own_people tools=Tools"
}

# What is new, tried on what was carried over.
after_0008() {
    local made vendor agreement contract request line system registration capacity
    local received last_year next_year far hid versions
    [ -n "$money_made" ] || return 0
    last_year=$(day_from_today -200)
    next_year=$(day_from_today 400)

    # A purchase request for the model from before, and the file that the previous
    # release refused: the item from before arrived on its line.
    api POST /purchase-requests "{\"reference\": \"UW-REQ-0001\", \"status\": \"ordered\", \"lines\": [{\"catalog_entry_hid\": \"$witness_entry\", \"quantity\": 3}]}"
    made="$status $(json '[[l["name"], l["catalog"]["pid"], l["quantity"], l["pending_quantity"]] for l in d["lines"]]')"
    request=$(json_field hid)
    line=$(json 'd["lines"][0]["hid"]')
    send "/imports/preview?entity=items&file_name=arrived.csv" "$work/arrived.csv"
    made="$made | $status $(job_counts)"
    apply_job "/imports/$(json 'd["job"]["hid"]')/apply"
    made="$made $status $(job_counts)"
    api GET "/items/$witness_item"
    expect "pkg a purchase request is made with a line of three of the model from before, and the file with a purchase_line column that $previous_version refused is previewed and applied: the item from before arrived on that line" \
        "$made | $(json '[d["purchase_line"]["name"], d["purchase_line_hid"] == "'"$line"'"]')" \
        '201 [["UW-REQ-0001/1", "UW-48P", 3, 3]] | 201 ["previewed", 1, 0, 1, 0, 0] 202 ["applied", 1, 0, 1, 0, 0] | ["UW-REQ-0001/1", true]'
    api GET "/purchase-lines/$line"
    api POST "/purchase-lines/$line/receive" "{\"row_version\": $(json_field row_version), \"items\": [{\"serial_number\": \"UWN0000R001\"}]}"
    made="$status $(json '[d["received_quantity"], d["pending_quantity"], [i["serial_number"] for i in d["items"]]]')"
    received=$(json 'd["items"][0]["hid"]')
    api POST "/purchase-lines/$line/receive" "{\"row_version\": $(json_field row_version), \"items\": [{\"serial_number\": \"UWN0000R002\"}, {\"serial_number\": \"UWN0000R003\"}]}"
    made="$made $status"
    api GET "/items/$received"
    expect "pkg one more is received on the line: it is a new item of that model, Delivered, which names the line, and the line has two of its three; two more than is left are refused" \
        "$made $(json '[d["catalog"]["pid"], d["lifecycle_state"], d["purchase_line"]["name"]]')" \
        '201 [2, 1, ["UWN0000R001"]] 422 ["UW-48P", "Delivered", "UW-REQ-0001/1"]'

    # A support agreement with the vendor from before, and a contract in it that says
    # nothing of its own period. It covers the item from before that has every value,
    # which is in Prod, the first switch of the stack, and the item that arrived.
    api GET /vendors
    vendor=$(json '[v["hid"] for v in d["items"] if v["name"] == "Upgrade Witness Networks"][0]')
    api POST /agreements "{\"name\": \"Upgrade Witness Agreement\", \"vendor_hid\": \"$vendor\", \"starts_on\": \"$last_year\", \"ends_on\": \"$next_year\", \"support_level\": \"8x5, next business day\"}"
    made=$status
    agreement=$(json_field hid)
    api POST /contracts "{\"number\": \"UW-CON-0001\", \"agreement_hid\": \"$agreement\", \"annual_cost\": \"1200.00\"}"
    made="$made $status $(json '[d["vendor"]["name"], d["starts_on"], d["effective"]["ends_on"]["value"], d["effective"]["ends_on"]["source"], d["effective"]["support_level"]["value"]]')"
    contract=$(json_field hid)
    api GET "/items/$witness_full"
    versions=$(json_field row_version)
    api GET "/items/$witness_switch"
    versions="$versions $(json_field row_version)"
    api POST "/contracts/$contract/coverage" "{\"items\": [{\"item_hid\": \"$witness_full\"}, {\"item_hid\": \"$witness_switch\"}, {\"item_hid\": \"$received\"}]}"
    expect "pkg an agreement is made with the vendor from before, and a contract in it, which has the vendor, the period and the support level of its agreement; two items from before and the one that arrived are put under it together, and each is covered from today" \
        "$made $status $(json 'sorted([c["item"]["serial_number"], c["in_force"], c["effective_ends_on"]] for c in d)')" \
        "201 201 [\"Upgrade Witness Networks\", null, \"$next_year\", \"agreement\", \"8x5, next business day\"] 201 [[\"UWN0000R001\", true, \"$next_year\"], [\"UWN0000S001\", true, \"$next_year\"], [\"UWN0000X002\", true, \"$next_year\"]]"
    api POST "/contracts/$contract/coverage" "{\"items\": [{\"item_hid\": \"$witness_retired\"}]}"
    made="$status $(json '[e["field"] for e in d["errors"]]')"
    api POST "/items/$received/retire" '{"row_version": 1}'
    made="$made $status"
    api GET /reports/coverage
    made="$made $status $(json '[d["totals"]["covered"], d["totals"]["out_of_service"]]')"
    api GET '/reports/coverage?section=out_of_service'
    expect "pkg the item that was retired before the upgrade is not put under a contract; the item that arrived is retired, and its coverage is ended on that day and says that it left service: GET /reports/coverage counts the two that are in service as covered, and lists that one as out of service under a contract that still runs" \
        "$made $status $(json '[[i["serial_number"], i["record_status"], [[c["ends_on"] == d["as_of"], c["left_service"]] for c in i["coverage"]]] for i in d["items"]]')" \
        '422 ["items.0.item_hid"] 200 200 [2, 1] 200 [["UWN0000R001", "retired", [[true, true]]]]'
    # The contract is renewed, in one place, for a period that has begun: the items
    # follow at once, and none is written to.
    far=$(day_from_today 800)
    api POST "/contracts/$contract/renew" "{\"row_version\": 1, \"number\": \"UW-CON-0002\", \"starts_on\": \"$last_year\", \"ends_on\": \"$far\"}"
    made="$status $(json '[d["number"], d["effective"]["ends_on"]["source"], d["covered_items"]]')"
    api GET "/items/$witness_full"
    made="$made $(json '[c["contract"]["number"] for c in d["coverage"]] + [d["covered_until"]]') $(json_field row_version)"
    api GET "/items/$witness_switch"
    made="$made $(json '[c["contract"]["number"] for c in d["coverage"]] + [d["covered_until"]]') $(json_field row_version)"
    api GET '/reports/summary?by=contract'
    expect "pkg POST /contracts/{hid}/renew gives the contract a new number and a period of its own, which covers the two that are not retired: the items under it show the new number and the new last day at once, each at the row_version it had ($versions), and the summary by contract has a row for the contract, labelled with its number and its vendor, beside the row of what no contract covers" \
        "$made $status $(json '[[r["label"], r["items"]] for r in d["rows"] if r["key"]]') $(json 'sum(r["key"] is None for r in d["rows"])')" \
        "200 [\"UW-CON-0002\", \"own\", 2] [\"UW-CON-0002\", \"$far\"] ${versions% *} [\"UW-CON-0002\", \"$far\"] ${versions#* } 200 [[\"UW-CON-0002 (Upgrade Witness Networks)\", 2]] 1"

    # The first stack from before is registered with an external system: the
    # registration is on the stack, and on none of its switches.
    api POST /external-systems '{"name": "Upgrade Witness Watch", "kind": "monitoring"}'
    made=$status
    system=$(json_field hid)
    api POST /registrations "{\"system_hid\": \"$system\", \"group_hid\": \"$witness_stack\", \"external_id\": \"node-0001\"}"
    made="$made $status $(json_field status)"
    registration=$(json_field hid)
    api GET "/device-groups/$witness_stack"
    made="$made $(json '[[x["system"]["name"], x["external_id"]] for x in d["registrations"]]')"
    api GET "/items/$witness_switch"
    expect "pkg an external system is made and the first stack from before is registered with it: the registration is on the stack, and not on the switch that is its master" \
        "$made $(json 'd["registrations"]')" \
        '201 201 registered [["Upgrade Witness Watch", "node-0001"]] []'

    # A capacity line in the category that the site entered before the upgrade.
    api POST /capacity-lines '{"side": "supply", "category": "on-call", "name": "Upgrade Witness Rota", "quantity": "2", "units_each": "0.25"}'
    made="$status $(json '[d["category_label"], d["units"]]')"
    capacity=$(json_field hid)
    api GET /reports/capacity
    expect "pkg a capacity line is entered in the category that the site had put into the list before the upgrade: the capacity report has a row for that category, under the site's label, and half a unit of supply" \
        "$made $status $(json '[d["active"]["supply"], [[c["label"], c["lines"], c["units"]] for c in d["active"]["by_category"] if c["category"] == "on-call"], [c["label"] for c in d["active"]["by_category"] if c["category"] == "staff"]]')" \
        '201 ["On-call rota", "0.5"] 200 ["0.5", [["On-call rota", 1, "0.5"]], ["Our own people"]]'

    # Taken out again, so that the rest of this pass starts from reports as empty as
    # those of a new installation. Nothing of this is deleted: a line and a system are
    # retired, a registration is marked as removed, a coverage is ended with a day,
    # and the one that says its item left service says so no longer, a contract and
    # then its agreement are retired, and a request is cancelled.
    api POST "/capacity-lines/$capacity/retire" '{"row_version": 1}'
    made=$status
    api PATCH "/registrations/$registration" '{"row_version": 1, "status": "removed"}'
    made="$made $status"
    api POST "/external-systems/$system/retire" '{"row_version": 1}'
    made="$made $status"
    api GET "/contracts/$contract/coverage?limit=1000"
    for hid in $(json '" ".join(c["hid"] + ":" + str(c["row_version"]) for c in d["items"])'); do
        api PATCH "/contracts/$contract/coverage/${hid%:*}" "{\"row_version\": ${hid#*:}, \"ends_on\": \"$(day_from_today -30)\", \"left_service\": false}"
        made="$made $status"
    done
    api GET "/contracts/$contract"
    api POST "/contracts/$contract/retire" "{\"row_version\": $(json_field row_version)}"
    made="$made $status"
    api POST "/agreements/$agreement/retire" '{"row_version": 1}'
    made="$made $status"
    api GET "/purchase-requests/$request"
    api PATCH "/purchase-requests/$request" "{\"row_version\": $(json_field row_version), \"status\": \"cancelled\"}"
    made="$made $status"
    api GET /reports/coverage
    made="$made | $status $(json '[d["totals"]["covered"], d["totals"]["out_of_service"]]')"
    api GET /reports/capacity
    expect "pkg the line and the system are retired, the registration is marked as removed, the three coverages are ended with a day, the contract and then its agreement are retired, and the request is cancelled: nothing is covered and there is no supply once more" \
        "$made $status $(json 'd["active"]["supply"]')" \
        '200 200 200 200 200 200 200 200 200 | 200 [0, 0] 200 0'
}
