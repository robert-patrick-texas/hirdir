# shellcheck shell=bash
# shellcheck disable=SC2034,SC2154  # Read by packaging/package-test.sh, whose names these are.
#
# hirdir 0.6.1, which has no migration, and says and reads differently some of what it
# holds as the release before held it.
#
# packaging/package-test.sh reads this file when the upgrade it tests crosses 0.6.1: the
# previous release is older, and the new version is 0.6.1 or a later one. It calls the
# three functions below: see "what one upgrade alone has" there. What they look at is
# made where the previous release is 0.6.0, which has contracts and purchases: one
# from before has none of it, and then they do nothing.
#
# Nothing that is stored differs. What reads differently is what docs/install.md says
# under "From 0.6.0 to 0.6.1", and that is what is looked for here:
#
#   - an earlier term of a contract that had no dates of its own has its agreement's,
#     as the agreement stood when the term ended, read from what 0.6.0 wrote in the
#     audit trail, where 0.6.0 gave it none; and an agreement lists its own earlier
#     terms, which 0.6.0 had no route for (D-160)
#   - each field that a contract may have from its agreement says what the agreement
#     gives for it (D-159)
#   - an item that 0.6.0 let onto a purchase line of another model is reported, on the
#     item and on the line, is let be when anything else of it is changed, and is held
#     to the line's model when its model is (D-161)
#   - the contracts that still count an item out of service are on its record and are
#     fields of the item list (D-162)
#   - the file of items has two columns more and that of purchase lines one, which an
#     import passes over
#
# Each of them is a field more, a route more or a column more, beside what 0.6.0 gave,
# and the comparison lets a record have fields more, so nothing is named in meant[]. The
# one value that 0.6.0 gave and 0.6.1 gives otherwise is the dates of the earlier term
# of a contract that had none: the answer that is compared for it leaves them out, and
# changed_0_6_1 looks at them by itself.

# What before_0_6_1 makes and finds with the previous release, for the other two.
# The agreement that is renewed late, and the contract in it with no dates of its own,
# which is renewed with a new number before the agreement is:
coterm_agreement=""
coterm_contract=""
#   the first period of the agreement, its second, and what its earlier term is to be:
#   the audit event of its renewal says when and by whom, as 0.6.0 wrote it
coterm_first=""
coterm_last=""
coterm_begun=""
coterm_ends=""
coterm_term=""
# The item that is put by hand on a line of another model, the line and the first
# line of the request, and a third model for it to be refused.
astray_item=""
astray_line=""
money_line=""
third_model=""
# The item in Archived that two contracts still count, and the item from before that
# was retired under the first contract.
archived_item=""
left_item=""
# Contracts and an agreement that witness_money made, and what the second contract
# overrides: its own last day, and that of the agreement.
money_agreement=""
money_overriding=""
money_alone=""
money_own_end=""
money_agreement_end=""

before_0_6_1() {
    local made vendor plain rv move
    [ -n "$witness_contracts" ] || return 0
    read -r plain money_overriding money_alone _ <<<"$witness_contracts"
    api GET "/catalog-entries/$witness_entry"
    vendor=$(json_field vendor_hid)
    api GET '/agreements?limit=1000'
    money_agreement=$(json '[a["hid"] for a in d["items"] if a["number"] == "UW-EA-0001"][0]')
    money_agreement_end=$(json '[a["ends_on"] for a in d["items"] if a["number"] == "UW-EA-0001"][0]')
    api GET "/contracts/$money_overriding"
    money_own_end=$(json 'd["effective"]["ends_on"]["value"]')
    expect "pkg $previous_version says of a contract what it has in force and where it came from, and nothing of what the agreement gives for a field that the contract overrides" \
        "$status $(json '[d["effective"]["support_level"]["source"], sorted({k for v in d["effective"].values() for k in v})]')" \
        '200 ["own", ["label", "source", "source_hid", "value"]]'

    # An item of UW-48P put by hand on the second line of the request from before,
    # which is of UW-24S. A third model, for the item to be refused afterwards.
    api GET '/purchase-lines?limit=1000'
    astray_line=$(json '[l["hid"] for l in d["items"] if l["name"] == "UW-REQ-1001/2"][0]')
    money_line=$(json '[l["hid"] for l in d["items"] if l["name"] == "UW-REQ-1001/1"][0]')
    api POST /catalog-entries "{\"vendor_hid\": \"$vendor\", \"pid\": \"UW-8T\"}"
    made=$status
    third_model=$(json_field hid)
    api POST /items "{\"catalog_entry_hid\": \"$witness_entry\", \"serial_number\": \"UWN0000L001\", \"lifecycle_state\": \"Delivered\"}"
    made="$made $status"
    astray_item=$(json_field hid)
    witness_items+=("$astray_item")
    api PATCH "/items/$astray_item" "{\"row_version\": 1, \"purchase_line_hid\": \"$astray_line\"}"
    made="$made $status $(json '[d["purchase_line"]["name"], d["row_version"], "purchase_line_mismatch" in d]')"
    api GET "/purchase-lines/$astray_line"
    expect "pkg an item of UW-48P is put by hand on the second line of the request from before, which is of UW-24S: $previous_version lets it in, counts it as arrived, and says nothing of its model, on the item or on the line" \
        "$made $status $(json '[d["received_quantity"], "mismatched_items" in d]')" \
        '201 201 200 ["UW-REQ-1001/2", 2, false] 200 [1, false]'

    # A support agreement whose term ended a month ago, and a contract in it with no
    # dates of its own. The vendor gives the contract a new number for the new term,
    # and the agreement's renewal is entered after that, late, for a period that began
    # the day after the last one ended. The earlier term of the contract then had the
    # agreement's first period, which the agreement no longer has.
    coterm_first=$(day_from_today -400)
    coterm_last=$(day_from_today -35)
    coterm_begun=$(day_from_today -34)
    coterm_ends=$(day_from_today 330)
    api POST /agreements "{\"name\": \"Upgrade Witness Campus Agreement\", \"number\": \"UW-EA-0002\", \"vendor_hid\": \"$vendor\", \"starts_on\": \"$coterm_first\", \"ends_on\": \"$coterm_last\", \"support_level\": \"8x5, next business day\", \"purchase_reference\": \"UW-PO-0006\", \"annual_cost\": \"9100.00\"}"
    made=$status
    coterm_agreement=$(json_field hid)
    api POST /contracts "{\"number\": \"UW-CON-1006\", \"agreement_hid\": \"$coterm_agreement\", \"purchase_reference\": \"UW-PO-0007\", \"annual_cost\": \"1300.00\"}"
    made="$made $status $(json '[d["effective"][k]["source"] for k in ("starts_on", "ends_on")]')"
    coterm_contract=$(json_field hid)
    api POST "/contracts/$coterm_contract/renew" '{"row_version": 1, "number": "UW-CON-2006"}'
    made="$made $status $(json_field number)"
    api GET "/contracts/$coterm_contract/terms"
    made="$made $status $(json '[[t["number"], t["starts_on"], t["ends_on"]] for t in d]')"
    api POST "/agreements/$coterm_agreement/renew" "{\"row_version\": 1, \"starts_on\": \"$coterm_begun\", \"ends_on\": \"$coterm_ends\", \"purchase_reference\": \"UW-PO-0008\", \"annual_cost\": \"9400.00\"}"
    made="$made $status $(json '[d["starts_on"], d["ends_on"]]')"
    api GET "/audit-events?record_hid=$coterm_agreement&action=renew"
    coterm_term=$(json "[[\"UW-EA-0002\", \"$coterm_first\", \"$coterm_last\", \"9100.00\", \"UW-PO-0006\", e[\"at\"], e[\"actor_name\"]] for e in d[\"items\"]]")
    made="$made $status $(json 'len(d["items"])')"
    api GET "/agreements/$coterm_agreement/terms"
    expect "pkg a support agreement whose term ended a month ago, with a contract in it that has no dates of its own, which $previous_version renews with a new number and gives an earlier term with no dates; then the agreement's renewal, entered late, for a period that has begun, with one audit event, and no list of the agreement's earlier terms" \
        "$made $status" \
        "201 201 [\"agreement\", \"agreement\"] 200 UW-CON-2006 200 [[\"UW-CON-1006\", null, null]] 200 [\"$coterm_begun\", \"$coterm_ends\"] 200 1 404"

    # An item in Prod under the first contract and under the one just renewed, which
    # is taken out of service to Archived: the move to Released ends both coverages
    # that day, as having left service, and both contracts still count it.
    api POST /items "{\"catalog_entry_hid\": \"$witness_entry\", \"serial_number\": \"UWN0000H001\", \"lifecycle_state\": \"Prod\"}"
    made=$status
    archived_item=$(json_field hid)
    witness_items+=("$archived_item")
    api POST "/contracts/$plain/coverage" "{\"items\": [{\"item_hid\": \"$archived_item\"}]}"
    made="$made $status"
    api POST "/contracts/$coterm_contract/coverage" "{\"items\": [{\"item_hid\": \"$archived_item\"}]}"
    made="$made $status"
    rv=1
    for move in Pending-Removal Released Archived; do
        api POST "/items/$archived_item/transition" "{\"to\": \"$move\", \"row_version\": $rv}"
        made="$made $status"
        rv=$(json_field row_version)
    done
    api GET "/items/$archived_item"
    made="$made $(json '[d["lifecycle_state"], sorted([c["contract"]["number"], c["left_service"]] for c in d["coverage"]), "out_of_service_contracts" in d]')"
    api GET "$every_item&filter=serial_number:eq:UWN0000Q002"
    left_item=$(json 'd["items"][0]["hid"]')
    api GET /reports/coverage
    expect "pkg an item in Prod under the first contract and the one just renewed is moved to Pending-Removal, Released and Archived: the move to Released ends both coverages as having left service, the report counts it out of service beside the item retired before, and $previous_version names on the item no contract that still counts it" \
        "$made $status $(json 'd["totals"]["out_of_service"]')" \
        '201 201 201 200 200 200 ["Archived", [["UW-CON-1001", true], ["UW-CON-2006", true]], false] 200 2'

    # A file of items with the columns that 0.6.1 adds, which the previous release
    # does not know.
    api POST "/imports/preview?file_name=columns-0.6.1.json" "{\"schema\": \"hirdir/1\", \"entity\": \"items\", \"mode\": \"upsert\", \"records\": [{\"hid\": \"$astray_item\", \"purchase_line_mismatch\": true, \"out_of_service_contracts\": []}]}"
    expect "pkg a file of items with the columns purchase_line_mismatch and out_of_service_contracts is refused by $previous_version, for a column it does not know" \
        "$status $(json 'd["errors"][0]["field"]')" "422 column"

    # Taken out again by the upgrade pass, the contract before its agreement.
    witness_undo=("contracts/$coterm_contract" "agreements/$coterm_agreement" "${witness_undo[@]}")
    witness_answers+=("co-termed|/contracts/$coterm_contract/terms|[[t[\"number\"], t[\"annual_cost\"], t[\"purchase_reference\"], t[\"renewed_at\"], t[\"renewed_by_name\"]] for t in d]|the contract with no dates of its own has the earlier term it had, its dates apart, which are looked at by themselves: its number, its cost, its purchase reference, and when and by whom it was renewed")
}

changed_0_6_1() {
    local when=$1 found
    [ -n "$coterm_contract" ] || return 0

    # The earlier terms (D-160, D-163).
    api GET "/contracts/$coterm_contract/terms"
    found=$(json '[[t[k] for k in ("number", "starts_on", "starts_on_source", "ends_on", "ends_on_source", "agreement_hid")] for t in d]')
    api GET "/agreements/$coterm_agreement/terms"
    expect "pkg $when the earlier term of the contract with no dates of its own, which $previous_version gave with none, has those of the agreement's term in force when the contract's term began, as the agreement stood then, and not as its renewal left it, each from the agreement, and names the agreement; and the agreement lists its own earlier term, from what $previous_version wrote of its renewal: number, period, cost, purchase reference, and when and by whom it was renewed" \
        "$found $status $(json '[[t[k] for k in ("number", "starts_on", "ends_on", "annual_cost", "purchase_reference", "renewed_at", "renewed_by_name")] for t in d]')" \
        "[[\"UW-CON-1006\", \"$coterm_first\", \"agreement\", \"$coterm_last\", \"agreement\", \"$coterm_agreement\"]] 200 $coterm_term"
    api GET "/contracts/$money_alone/terms"
    found=$(json '[[t[k] for k in ("number", "starts_on_source", "ends_on_source", "agreement_hid")] for t in d]')
    api GET "/agreements/$money_agreement/terms"
    expect "pkg $when the contract that stands by itself has its earlier term with its own dates and no agreement, and the agreement whose renewal was entered early has no earlier term: its next one is still to begin" \
        "$found $status $(json 'd')" '[["UW-CON-1003", "own", "own", null]] 200 []'

    # What the agreement gives (D-159).
    api GET "/contracts/$money_overriding"
    found=$(json '[[k] + [d["effective"][k][f] for f in ("source", "value", "from_agreement")] for k in ("ends_on", "support_level", "support_url")] + [[d["effective"]["reseller_hid"][f] for f in ("source", "label", "from_agreement_label")]]')
    api GET "/contracts/$money_alone"
    expect "pkg $when each field that a contract may have from its agreement says what the agreement gives for it: the contract that overrides the last day and the support level has its own beside the agreement's, and the support address and the reseller from it; the contract that stands by itself has nothing from an agreement" \
        "$found $status $(json 'sorted({v["from_agreement"] for v in d["effective"].values()} | {d["effective"]["reseller_hid"]["from_agreement_label"]})')" \
        "[[\"ends_on\", \"own\", \"$money_own_end\", \"$money_agreement_end\"], [\"support_level\", \"own\", \"8x5, next business day\", \"24x7, four-hour response\"], [\"support_url\", \"agreement\", \"https://support.example.com/upgrade\", \"https://support.example.com/upgrade\"], [\"agreement\", \"Upgrade Witness Reseller\", \"Upgrade Witness Reseller\"]] 200 [null]"

    # What 0.6.0 let onto a line of another model, reported (D-161).
    api GET "/items/$astray_item"
    found=$(json "[d[\"catalog_entry_hid\"] == \"$witness_entry\", d[\"purchase_line\"][\"name\"], d[\"purchase_line\"][\"catalog_entry_hid\"] == \"$witness_second\", d[\"purchase_line_mismatch\"], d[\"row_version\"]]")
    api GET "$every_item&filter=purchase_line_mismatch:eq:true"
    found="$found $status $(json '[i["serial_number"] for i in d["items"]]')"
    api GET '/purchase-lines?limit=1000'
    expect "pkg $when the item of UW-48P that $previous_version let onto the line of UW-24S is reported, at the row_version it had: its record names the line's model and says that it is not its own, the item list finds it and no other, and its line counts it, while the items that arrived on the first line are of its model" \
        "$found $status $(json 'sorted([l["name"], l["received_quantity"], l["mismatched_items"]] for l in d["items"])')" \
        '[true, "UW-REQ-1001/2", true, true, 2] 200 ["UWN0000L001"] 200 [["UW-REQ-1001/1", 3, 0], ["UW-REQ-1001/2", 1, 1], ["UW-REQ-1003/1", 0, 0]]'

    # The contracts that still count an item out of service (D-162).
    api GET "/items/$archived_item"
    found=$(json '[d["lifecycle_state"], [c["number"] for c in d["out_of_service_contracts"]], d["row_version"]]')
    api GET "/items/$left_item"
    found="$found $(json '[d["record_status"], [c["number"] for c in d["out_of_service_contracts"]]]')"
    api GET "/items/$witness_full"
    found="$found $(json '[d["covered"], d["out_of_service_contracts"]]')"
    api GET "$every_item&filter=out_of_service_contract.number:eq:UW-CON-1001&sort=serial_number"
    found="$found $(json '[i["serial_number"] for i in d["items"]]')"
    api GET "$every_item&filter=out_of_service_contract.hid:eq:$coterm_contract"
    expect "pkg $when the contracts that still count an item out of service are on its record: both for the item in Archived, whose coverages ended when it left, the first contract for the item retired before, and none for an item in service; and they are fields of the item list, by number and by HID" \
        "$found $status $(json '[i["serial_number"] for i in d["items"]]')" \
        '["Archived", ["UW-CON-1001", "UW-CON-2006"], 4] ["retired", ["UW-CON-1001"]] [true, []] ["UWN0000H001", "UWN0000Q002"] 200 ["UWN0000H001"]'

    # In files.
    api POST /exports "{\"entity\": \"items\", \"columns\": [\"serial_number\", \"purchase_line\", \"purchase_line_mismatch\", \"out_of_service_contracts\"], \"hids\": [\"$astray_item\", \"$archived_item\", \"$left_item\", \"$witness_full\"], \"sort\": [\"serial_number\"], \"include_archived\": true}"
    found="$status $(table '[head[1:]] + [[r[k] for k in head[1:]] for r in rows]')"
    api POST /exports "{\"entity\": \"purchase_lines\", \"columns\": [\"request\", \"line\", \"received_quantity\", \"mismatched_items\"], \"hids\": [\"$money_line\", \"$astray_line\"], \"sort\": [\"line\"]}"
    expect "pkg $when a file of items has the columns purchase_line_mismatch and out_of_service_contracts, with the numbers of the contracts, and one of purchase lines the column mismatched_items" \
        "$found $status $(table '[head[1:]] + [[r[k] for k in head[1:]] for r in rows]')" \
        '200 [["serial_number", "purchase_line", "purchase_line_mismatch", "out_of_service_contracts"], ["UWN0000H001", "", "false", "UW-CON-1001;UW-CON-2006"], ["UWN0000L001", "UW-REQ-1001/2", "true", ""], ["UWN0000Q002", "UW-REQ-1001/1", "false", "UW-CON-1001"], ["UWN0000X002", "", "false", ""]] 200 [["request", "line", "received_quantity", "mismatched_items"], ["UW-REQ-1001", "1", "3", "0"], ["UW-REQ-1001", "2", "1", "1"]]'
}

after_0_6_1() {
    local made rv
    [ -n "$coterm_contract" ] || return 0

    # What 0.6.0 let in is not held against an edit of anything else, and is held to
    # the line's model when its model is changed (D-161).
    api GET "/items/$astray_item"
    api PATCH "/items/$astray_item" "{\"row_version\": $(json_field row_version), \"description\": \"Put on its line by hand with $previous_version\"}"
    made="$status $(json '[d["description"], d["purchase_line_mismatch"], d["row_version"]]')"
    rv=$(json_field row_version)
    api PATCH "/items/$astray_item" "{\"row_version\": $rv, \"catalog_entry_hid\": \"$third_model\"}"
    made="$made $status $(json '[[e["field"], "UW-24S" in e["message"]] for e in d["errors"]]')"
    api PATCH "/items/$astray_item" "{\"row_version\": $rv, \"catalog_entry_hid\": \"$witness_second\"}"
    made="$made $status $(json '[d["purchase_line_mismatch"], d["row_version"]]')"
    api GET "/purchase-lines/$astray_line"
    made="$made $status $(json_field mismatched_items)"
    api GET "$every_item&filter=purchase_line_mismatch:eq:true"
    expect "pkg the item that $previous_version let onto a line of another model is given a description, and $version lets it, and reports it still; it is refused a third model, on catalog_entry_hid, with the line's model named; and given the line's model it is put right, and nothing is reported any more" \
        "$made $status $(json_field total)" \
        "200 [\"Put on its line by hand with $previous_version\", true, 3] 422 [[\"catalog_entry_hid\", true]] 200 [false, 4] 200 0 200 0"
    api POST /items "{\"catalog_entry_hid\": \"$witness_entry\", \"serial_number\": \"UWN0000L003\", \"purchase_line_hid\": \"$astray_line\"}"
    made="$status $(json '[e["field"] for e in d["errors"]]')"
    api POST /items "{\"serial_number\": \"UWN0000L002\", \"purchase_line_hid\": \"$astray_line\", \"lifecycle_state\": \"Delivered\"}"
    if [ "$status" = 201 ]; then witness_items+=("$(json_field hid)"); fi
    expect "pkg an item put on that line now that names another model is refused, on catalog_entry_hid, and one that names none takes the line's" \
        "$made $status $(json "[d[\"catalog_entry_hid\"] == \"$witness_second\", d[\"purchase_line_mismatch\"]]")" \
        '422 ["catalog_entry_hid"] 201 [true, false]'
    api GET "/catalog-entries/$third_model"
    api POST "/catalog-entries/$third_model/retire" "{\"row_version\": $(json_field row_version)}"
    expect "pkg the third model, which no item has, is retired" "$status $(json_field record_status)" "200 retired"

    # A file that $version writes with the new columns is taken back, and they are
    # passed over.
    api POST /exports "{\"entity\": \"items\", \"columns\": [\"serial_number\", \"purchase_line\", \"purchase_line_mismatch\", \"out_of_service_contracts\"], \"hids\": [\"$astray_item\", \"$archived_item\", \"$left_item\", \"$witness_full\"], \"sort\": [\"serial_number\"], \"include_archived\": true}"
    cp "$work/body" "$work/items-0.6.1.csv"
    send "/imports/preview?entity=items&mode=upsert&file_name=items-0.6.1.csv" "$work/items-0.6.1.csv"
    made="$status $(job_counts)"
    api POST /exports "{\"entity\": \"purchase_lines\", \"columns\": [\"request\", \"line\", \"received_quantity\", \"mismatched_items\"], \"hids\": [\"$money_line\", \"$astray_line\"], \"sort\": [\"line\"]}"
    cp "$work/body" "$work/lines-0.6.1.csv"
    send "/imports/preview?entity=purchase_lines&mode=upsert&file_name=lines-0.6.1.csv" "$work/lines-0.6.1.csv"
    expect "pkg that file of items, which $previous_version refused, and the file of purchase lines are taken back as $version exports them: the columns are passed over, and every row is unchanged" \
        "$made $status $(job_counts)" '201 ["previewed", 4, 0, 0, 4, 0] 201 ["previewed", 2, 0, 0, 2, 0]'

    # The client commands say it too.
    cli_run "$work/cli-0.6.1.agreement" agreements show "Upgrade Witness Campus Agreement"
    made="$code $(matches "^earlier term: +UW-EA-0002, $coterm_first to $coterm_last, UW-PO-0006$" "$work/cli-0.6.1.agreement")"
    cli_run "$work/cli-0.6.1.contract" contracts show UW-CON-2006
    made="$made $code $(matches "^earlier term: +UW-CON-1006, $coterm_first \(agreement\) to $coterm_last \(agreement\), UW-PO-0007$" "$work/cli-0.6.1.contract")"
    cli_run "$work/cli-0.6.1.override" contracts show UW-CON-1002
    expect "pkg hirdir agreements show prints the earlier term of the agreement from before, hirdir contracts show the earlier term of its contract with the agreement's dates marked, and an override beside what the agreement gives" \
        "$made $code $(matches "^support_level: +8x5, next business day \(in place of the agreement's 24x7, four-hour response\)$" "$work/cli-0.6.1.override")" \
        "0 1 0 1 0 1"
}
