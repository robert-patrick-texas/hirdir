# shellcheck shell=bash
# shellcheck disable=SC2034,SC2154  # Read by packaging/package-test.sh, whose names these are.
#
# Migration 0009, which came with hirdir 0.7.0: renewals with their members and the
# flag not to renew, the contacts of contracts, the lines of a purchase as procurement
# has them, lines of capacity that multiply, the balance kept week by week, links, and
# imports applied in the background.
#
# packaging/package-test.sh reads this file when the upgrade it tests runs the
# migration, and calls the three functions below: see "what one upgrade alone has"
# there. The previous release is then at revision 0008 or before: it applies an import
# in one transaction and answers with the job applied, and knows none of the rest.
#
# The migration gives catalog_entries do_not_renew and links, items do_not_renew,
# regions, sites and locations links, and contracts next_with_agreement and
# ends_with_term, each as a column added to the table as it stands. It makes
# purchase_lines anew, so that catalog_entry_hid may be blank, with part_number and
# description after the columns there are, and capacity_lines anew, so that quantity
# and units_each may be blank, with effect, factor and share. It gives import_jobs
# rows_done, applied and stale, and import_rows applied_outcome and applied_reasons.
# Then it creates contract_contacts, capacity_line_targets and renewal_alert_views, and
# last of all capacity_records, which is the table that the pass whose migration fails
# puts in its way: everything else is done by then, the two tables made anew among it.
#
# It changes one thing that is held, and says so: a job that the previous release
# applied, as one transaction, is given the counts that an apply keeps from now on,
# rows_done its rows and applied the rows it applied. That row of import_jobs is named
# as meant to change and is looked at by itself. Nothing else is changed: no model or
# item is flagged, no contract marked, no line loses its model, and no record of the
# balance is made. The migration writes no audit event. The service, once it has
# started, records the balance of the week, which has none, with an event of the
# system's own, and the check of the audit trail allows for that event by name.
# docs/install.md says all of it under "From 0.6.1 to 0.7.0", and what is said there is
# what is looked for here.
writes_no_event=yes
# The import jobs and their rows are no part of the inventory, and the migration
# changes them. The upgrade pass previews a file of its own before it compares, which
# is a job more with its rows: the jobs from before are compared by themselves.
more_tables="import_jobs import_rows"
may_add[import_jobs]=yes
may_add[import_rows]=yes
also new_columns catalog_entries 'do_not_renew BOOLEAN NOT NULL -
links JSON NOT NULL -'
also new_columns items 'do_not_renew BOOLEAN NULL -'
also new_columns regions 'links JSON NOT NULL -'
also new_columns sites 'links JSON NOT NULL -'
also new_columns locations 'links JSON NOT NULL -'
also new_columns contracts 'next_with_agreement BOOLEAN NOT NULL -
ends_with_term BOOLEAN NOT NULL -'
also altered_columns purchase_lines 'catalog_entry_hid VARCHAR(36) NULL -'
also new_columns purchase_lines 'part_number VARCHAR(100) NULL -
description TEXT NULL -'
also altered_columns capacity_lines 'quantity BIGINT NULL -
units_each BIGINT NULL -'
also new_columns capacity_lines 'effect VARCHAR(10) NOT NULL -
factor BIGINT NULL -
share BIGINT NULL -'
also new_columns import_jobs 'rows_done INTEGER NOT NULL -
applied INTEGER NOT NULL -
stale INTEGER NOT NULL -'
also new_columns import_rows 'applied_outcome VARCHAR(10) NULL -
applied_reasons JSON NOT NULL -'

# The three jobs that before_0009 makes with the previous release: one applied with a
# row of it rejected, one that failed because its record changed after the preview,
# and one that is previewed and waits to be applied. And what the table held of the
# one that was applied, in the columns it had.
applied_job=""
failed_job=""
waiting_job=""
applied_row=""

# tags_file RECORD...: the JSON of a file of tags, each record given as JSON.
tags_file() {
    local IFS=,
    printf '{"schema": "hirdir/1", "entity": "tags", "mode": "upsert", "records": [%s]}' "$*"
}

# What the migration could harm, made with the previous release. What it makes anew,
# purchase_lines and capacity_lines, and the tables that it gives columns, are in the
# inventory already from revision 0008, with every kind of record: this sees that they
# are. What is not there yet is made: three import jobs, applied, failed and waiting.
before_0009() {
    local made hid row_version
    [ -n "$witness_entry" ] || return 0

    if [ -n "$witness_contracts" ]; then
        api GET '/purchase-lines?limit=1000'
        made="$status $(json '[len(d["items"]), sum(l["received_quantity"] > 0 for l in d["items"])]')"
        api GET '/capacity-lines?include_drafts=true&include_archived=true&limit=1000'
        made="$made $(json '[len(d["items"]), sorted({l["side"] for l in d["items"]}), sorted({l["record_status"] for l in d["items"]})]')"
        api GET '/contracts?include_drafts=true&include_archived=true&limit=1000'
        made="$made $(json '[sum(c["next_term"] is not None for c in d["items"]), sum(c["agreement_hid"] is not None for c in d["items"])]')"
        api GET '/agreements?limit=1000'
        expect "pkg the inventory holds what migration 0009 makes anew and what it gives columns: three purchase lines, on one of which items arrived, six capacity lines of both sides, a draft and a retired one among them, a contract with a next term of its own and two in the agreement, which has a next term, beside the models, the items and the places" \
            "$made $(json '[a["next_term"] is not None for a in d["items"]]')" \
            '200 [3, 1] [6, ["demand", "supply"], ["active", "draft", "retired"]] [1, 2] [true]'

        # What the previous release does not know: it refuses a line with no model,
        # says nothing of a flag or a link on a model, and has no record of the balance
        # and no renewal alert.
        api POST /purchase-requests '{"reference": "UW-REQ-1009", "lines": [{"part_number": "UW-TAPE-25", "quantity": 10}]}'
        made="$status"
        api GET "/catalog-entries/$witness_entry"
        made="$made $(json 'sorted(k for k in ("do_not_renew", "links") if k in d)')"
        api GET /capacity-records
        made="$made $status"
        api GET /renewals/alert
        expect "pkg $previous_version refuses a purchase line that names no model, says nothing of a flag not to renew or of links on a model, and has no record of the capacity balance and no renewal alert" \
            "$made $status" "422 [] 404 404"
    fi

    # A file of tags with three rows, of which the third is rejected for its colour:
    # applied without it, the job is applied, in one transaction, as it always was.
    api POST '/imports/preview?file_name=upgrade-tags.json' "$(tags_file '{"label": "upgrade-imported", "description": "Brought by a file"}' '{"label": "upgrade-spare"}' '{"label": "upgrade-bad", "colour": "red"}')"
    made="$status $(job_counts)"
    applied_job=$(json 'd["job"]["hid"]')
    api POST "/imports/$applied_job/apply?skip_rejected=true"
    expect "pkg a file of three tags is previewed with $previous_version, one to create, one unchanged and one rejected for its colour, and applied without the rejected one, at once: the answer is the job, applied" \
        "$made $status $(job_counts)" \
        '201 ["previewed", 3, 1, 0, 1, 1] 200 ["applied", 3, 1, 0, 1, 1]'

    # A file that would change the tag it made, which a person changes after the
    # preview: the previous release applies none of it, and the job has failed.
    api POST '/imports/preview?file_name=upgrade-tags-again.json' "$(tags_file '{"label": "upgrade-imported", "description": "Brought by a second file"}')"
    made="$status $(job_counts)"
    failed_job=$(json 'd["job"]["hid"]')
    api GET /tags
    hid=$(json '[t["hid"] for t in d if t["label"] == "upgrade-imported"][0]')
    row_version=$(json '[t["row_version"] for t in d if t["label"] == "upgrade-imported"][0]')
    api PATCH "/tags/$hid" "{\"row_version\": $row_version, \"description\": \"Changed by a person\"}"
    made="$made $status"
    api POST "/imports/$failed_job/apply"
    made="$made $status"
    api GET "/imports/$failed_job"
    expect "pkg a second file would change that tag, and a person changes it after the preview: $previous_version applies none of the file, and the job has failed" \
        "$made $(json_field status)" '201 ["previewed", 1, 0, 1, 0, 0] 200 409 failed'

    # And a file that is previewed and not applied, which the new version applies.
    api POST '/imports/preview?file_name=upgrade-tags-later.json' "$(tags_file '{"label": "upgrade-later", "description": "Applied after the upgrade"}')"
    waiting_job=$(json 'd["job"]["hid"]')
    expect "pkg and a third file is previewed and waits to be applied" "$status $(job_counts)" '201 ["previewed", 1, 1, 0, 0, 0]'

    # Kept as the previous release gives them, to be compared field by field.
    for hid in "$applied_job" "$failed_job" "$waiting_job"; do
        api GET "/imports/$hid"
        keep "job-$hid"
    done
    # The job that was applied is meant to change, in the columns the migration adds:
    # its row is left out of the comparison of the table and looked at by itself.
    rows_apart[import_jobs]=$applied_job
    applied_row=$(table_rows import_jobs "$(table_columns import_jobs)" "$applied_job")
}

# What the migration made, and what the new version says of what was carried over,
# looked at by itself with the new version serving.
changed_0009() {
    local when=$1 database=/var/lib/hirdir/hirdir.db made record answer
    [ -n "$applied_job" ] || return 0

    # The jobs: the one applied before has the counts it would have had, the others
    # none, and nothing else of any of them is changed.
    expect "pkg $when the job that $previous_version applied, and only it, has the counts that an apply keeps from now on: rows_done its 3 rows, applied the 2 that were not rejected, and nothing stale; the other two have worked no row" \
        "$(sqlite_text "SELECT status, row_count, rows_done, applied, stale FROM import_jobs WHERE hid IN ('$applied_job', '$failed_job', '$waiting_job') ORDER BY created_at")" \
        "applied 3 3 2 0
failed 1 0 0 0
previewed 1 0 0 0"
    expect "pkg $when and in the columns it had, the row of that job holds what it held ($applied_row)" \
        "$(table_rows import_jobs "$(columns_then import_jobs)" "$applied_job")" "$applied_row"
    made=""
    for record in "$applied_job" "$failed_job" "$waiting_job"; do
        api GET "/imports/$record"
        made="$made$status $(unchanged "job-$record" fields "$record.rows_done $record.applied") $(json '[d["rows_done"], d["applied"], d["stale"]]') "
    done
    expect "pkg $when GET /imports/{hid} gives each of the three jobs as it gave them, with the counts beside: the applied one has worked its 3 rows and applied 2" \
        "${made% }" '200 same [3, 2, 0] 200 same [0, 0, 0] 200 same [0, 0, 0]'
    expect "pkg $when no row of a job from before says what an apply did with it: that is kept from now on" \
        "$(sqlite_value "$database" "SELECT count(*) FROM import_rows WHERE applied_outcome IS NOT NULL OR applied_reasons != '[]'")" 0

    # What is new is empty until somebody fills it in, but for the record of the
    # balance, which the service made when it started.
    expect "pkg $when the tables of the contacts of contracts, of the targets of capacity lines and of the renewal alerts that were seen are empty" \
        "$(sqlite_value "$database" 'SELECT (SELECT count(*) FROM contract_contacts) + (SELECT count(*) FROM capacity_line_targets) + (SELECT count(*) FROM renewal_alert_views)')" 0
    expect "pkg $when the new columns hold what the migration gives them and nothing more: no model or item is flagged not to be renewed, no model or place has a link, no contract is marked to end with its term or waits on its agreement, every purchase line has its model and no part number, and every capacity line adds, as many units as it had" \
        "$(sqlite_value "$database" "SELECT (SELECT count(*) FROM catalog_entries WHERE do_not_renew OR links != '[]') + (SELECT count(*) FROM items WHERE do_not_renew IS NOT NULL) + (SELECT count(*) FROM regions WHERE links != '[]') + (SELECT count(*) FROM sites WHERE links != '[]') + (SELECT count(*) FROM locations WHERE links != '[]') + (SELECT count(*) FROM contracts WHERE next_with_agreement OR ends_with_term) + (SELECT count(*) FROM purchase_lines WHERE catalog_entry_hid IS NULL OR part_number IS NOT NULL OR description IS NOT NULL) + (SELECT count(*) FROM capacity_lines WHERE effect != 'add' OR factor IS NOT NULL OR share IS NOT NULL OR quantity IS NULL OR units_each IS NULL)")" 0
    expect "pkg $when and no row refers to a record that is not there, in the two tables made anew or anywhere else" \
        "$(sqlite_text 'PRAGMA foreign_key_check' | wc -l)" 0

    # The record of the balance of the week, which the service made by itself when it
    # started, of what was carried over: its figures are those of the capacity report.
    api GET '/capacity-records?limit=1000'
    made="$status $(json_field total) $(json '[[d["items"][0][v][k] for k in ("demand", "supply", "balance")] + [d["items"][0]["adjusted"]] for v in ("active", "with_drafts")]')"
    record=$(json 'd["items"][0]["hid"]')
    api GET /reports/capacity
    answer=$(json '[[d[v][k] for k in ("demand", "supply", "balance")] + [False] for v in ("active", "with_drafts")]')
    api GET "/audit-events?record_hid=$record&limit=10"
    expect "pkg $when the service, when it started, recorded the capacity balance of the week, which had no record, by itself: one record, with the figures of the capacity report of what was carried over, and one event, which the system made" \
        "$made $(json '[[e["via"], e["action"], e["actor_hid"]] for e in d["items"]]')" \
        "200 1 $answer [[\"system\", \"create\", null]]"

    # The records say what the migration gave them.
    api GET '/catalog-entries?include_archived=true&limit=1000'
    made="$(json 'sorted({json.dumps([c["do_not_renew"], c["links"]]) for c in d["items"]})')"
    api GET "$every_item"
    expect "pkg $when every model from before says that it is to be renewed and has no link, and every item has its flag from its model, or none at all where it has no model" \
        "$made $(json 'sorted({json.dumps([i["do_not_renew"], i["effective"]["do_not_renew"]["value"], i["effective"]["do_not_renew"]["source"]]) for i in d["items"]})')" \
        '["[false, []]"] ["[null, false, \"catalog\"]", "[null, null, \"none\"]"]'
    api GET /reports/coverage
    made="$status $(json '[d["totals"]["not_renewed"], d["sections"]["not_renewed"]["count"], d["sections"]["not_renewed"]["by_model"]]')"
    api GET /settings
    expect "pkg $when GET /reports/coverage counts nothing as not to be renewed; and the five settings that 0.7.0 makes of what was held in the code are at their defaults: 90 days of warning of renewals, 60 days before a pending renewal is overdue, 730 days ahead for the end of life, of the LDoS, and 1,000 items to a request" \
        "$made $status $(json '[[s["key"], s["value"], s["is_default"]] for s in d if s["key"] in ("renewal_warning_days", "renewal_pending_overdue_days", "end_of_life_within_days", "end_of_life_date", "max_items_per_request")]')" \
        '200 [0, 0, []] 200 [["renewal_warning_days", 90, true], ["renewal_pending_overdue_days", 60, true], ["end_of_life_within_days", 730, true], ["end_of_life_date", "ldos", true], ["max_items_per_request", 1000, true]]'

    # The renewal worklist and the alert, of the contracts from before: the one whose
    # renewal is pending is on its list, and is not overdue; what more than one contract
    # covers is what the coverage report counts.
    api GET '/contracts?include_drafts=true&include_archived=true&limit=1000'
    made=$(json 'sum(c["status"] == "renewal_pending" and c["record_status"] == "active" for c in d["items"])')
    api GET /reports/coverage
    made="$made $(json 'd["totals"]["overlapping"]')"
    api GET /reports/renewals
    answer="$status $(json '[d["totals"][k] for k in ("ending", "lapsed", "renewal_pending", "overdue", "ends_with_term", "overlapping")]')"
    api GET /renewals/alert
    expect "pkg $when GET /reports/renewals lists of the contracts from before nothing that ends soon with no renewal entered and nothing that has lapsed, what is pending, ${made% *}, of which none is overdue, nothing that ends with its term, and the ${made#* } items that the coverage report has under more than one contract; GET /renewals/alert counts the same, and shows them to this Admin, who has not seen them" \
        "$answer $status $(json '[d["show"] == (d["lapsed"]["count"] + d["renewal_pending"]["count"] + d["ending"]["count"] + sum(d.get("agreements", {}).values()) > 0), d["ending"]["count"], d["lapsed"]["count"], d["renewal_pending"]["count"], d["overdue"]]')" \
        "200 [0, 0, ${made% *}, 0, 0, ${made#* }] 200 [true, 0, 0, ${made% *}, 0]"

    # The capacity report says beside its one balance where the work is: the regions at
    # the top and what is nowhere add up to the support weight of the whole.
    api GET /reports/capacity
    expect "pkg $when GET /reports/capacity has beside its balance the demand of each region, the support weight at and beneath it, and the regions at the top with what is nowhere add up to the support weight it counts, with and without the drafts" \
        "$status $(json '[sum(__import__("decimal").Decimal(r["support_weight"]) for r in d[v]["demand_by_region"] if r["parent_region_hid"] is None) == __import__("decimal").Decimal(d[v]["support_weight"]) for v in ("active", "with_drafts")]')" \
        '200 [true, true]'
}

# renewed_with_member: the agreement from before, renewed with its member, for
# after_0009.
renewed_with_member() {
    local made agreement plain versions start end
    api GET '/agreements?limit=1000'
    agreement=$(json '[a["hid"] for a in d["items"] if a["number"] == "UW-EA-0001"][0]')
    start=$(json '[a["next_term"]["starts_on"] for a in d["items"] if a["number"] == "UW-EA-0001"][0]')
    end=$(json '[a["next_term"]["ends_on"] for a in d["items"] if a["number"] == "UW-EA-0001"][0]')
    read -r plain _ <<<"$witness_contracts"
    api GET "/items/$witness_full"
    versions=$(json_field row_version)
    api GET "/agreements/$agreement"
    api POST "/agreements/$agreement/renew" "{\"row_version\": $(json_field row_version), \"withdraw\": true}"
    made="$status $(json_field next_term)"
    api POST "/agreements/$agreement/renew" "{\"row_version\": $(json_field row_version), \"starts_on\": \"$start\", \"ends_on\": \"$end\", \"purchase_reference\": \"UW-PO-0010\", \"members\": [{\"contract_hid\": \"$plain\", \"renewal\": \"new_number\", \"number\": \"UW-CON-4001\"}]}"
    made="$made $status $(json '[[m["number"], m["renewal"], m["left_behind"]] for m in d["members"]]')"
    api GET "/contracts/$plain"
    made="$made $(json '[d["number"], d["next_term"]["number"], d["next_term"]["starts_on"] == "'"$start"'", d["next_term"]["with_agreement"]]')"
    api GET "/items/$witness_full"
    made="$made $(json_field row_version)"
    api GET "/agreements/$agreement"
    api POST "/agreements/$agreement/renew" "{\"row_version\": $(json_field row_version), \"withdraw\": true}"
    made="$made | $status $(json_field next_term)"
    api GET "/contracts/$plain"
    expect "pkg the agreement from before is renewed with its member: its renewal entered early is withdrawn and entered again, and the contract in it with no dates of its own is to have a new number, which waits on the agreement's next term; the item under it is not written to (row_version $versions); withdrawn once more, the new number goes with it" \
        "$made $(json '[d["number"], d["next_term"]]')" \
        "200 null 200 [[\"UW-CON-4001\", \"new_number\", 0]] [\"UW-CON-1001\", \"UW-CON-4001\", true, true] $versions | 200 null [\"UW-CON-1001\", null]"
}

# What is new, tried on what was carried over.
after_0009() {
    local made counts flagged version engineer multiplier record
    [ -n "$applied_job" ] || return 0

    # The file that the previous release previewed is applied in the background: the
    # answer is 202 at once, and the job is applied, row by row, with what it did
    # with each. The job that failed before cannot be applied.
    apply_job "/imports/$waiting_job/apply"
    made="$status $(job_counts) $(json '[d["rows_done"], d["applied"], d["stale"]]')"
    api GET "/imports/$waiting_job/rows"
    made="$made $(json '[r["applied_outcome"] for r in d["items"]]')"
    api GET /tags
    made="$made $(json '[t["description"] for t in d if t["label"] == "upgrade-later"]')"
    api POST "/imports/$failed_job/apply"
    expect "pkg the file that $previous_version previewed is applied in the background: POST /imports/{hid}/apply answers 202 at once, and the job is applied with its row worked and applied, which says that it created its record; the tag is there; the job that failed before 0.7.0 is refused" \
        "$made $status" \
        '202 ["applied", 1, 1, 0, 0, 0] [1, 1, 0] ["create"] ["Applied after the upgrade"] 409'

    # The agreement from before is renewed with its members. Its renewal that was
    # entered early is withdrawn, and entered again: the contract in it with no dates of
    # its own is to have a new number, which waits on the next term; its items are not
    # written to. Withdrawn once more, the new number goes with it. A previous release
    # from before revision 0008 has no agreement.
    if [ -n "$witness_contracts" ]; then renewed_with_member; fi

    # Links on a model and a place from before, and what an item of the model shows.
    api GET "/catalog-entries/$witness_second"
    api PATCH "/catalog-entries/$witness_second" "{\"row_version\": $(json_field row_version), \"links\": [{\"url\": \"https://docs.example.com/uw-24s\", \"text\": \"Data sheet\"}]}"
    made="$status $(json '[[l["text"], l["url"]] for l in d["links"]]')"
    api GET "$every_item&filter=serial_number:eq:UWN0000F001"
    made="$made $(json '[[l["text"] for l in i["catalog"]["links"]] for i in d["items"]]')"
    if [ -n "$witness_room" ]; then
        made="$made $(said_of "$witness_room" locations '"links": [{"url": "https://intranet.example.net/upgrade-site/room-701", "text": ""}]')"
        api GET "/locations/$witness_room"
        made="$made $(json '[[l["text"], l["url"]] for l in d["links"]]')"
    fi
    expect "pkg links on a model from before, which an item of it shows, and on a room from before, with no text" \
        "$made" \
        "200 [[\"Data sheet\", \"https://docs.example.com/uw-24s\"]] [[\"Data sheet\"]]$(if [ -n "$witness_room" ]; then echo ' 200 [["", "https://intranet.example.net/upgrade-site/room-701"]]'; fi)"

    # The coverage report, with an item from before that is not to be renewed: a switch
    # in Prod that no contract covers is no gap, and is counted by itself, by model.
    api GET /reports/coverage
    counts=$(json '[d["totals"]["uncovered"], d["totals"]["not_renewed"]]')
    api GET "$every_item&filter=serial_number:eq:UWN0000S004"
    flagged=$(json 'd["items"][0]["hid"]')
    api PATCH "/items/$flagged" "{\"row_version\": $(json 'd["items"][0]["row_version"]'), \"do_not_renew\": true}"
    made="$status $(json '[d["effective"]["do_not_renew"]["value"], d["effective"]["do_not_renew"]["source"]]')"
    version=$(json_field row_version)
    api GET /reports/coverage
    made="$made $(json '[d["totals"]["uncovered"], d["totals"]["not_renewed"], [[m["pid"], m["count"]] for m in d["sections"]["not_renewed"]["by_model"]]]')"
    api PATCH "/items/$flagged" "{\"row_version\": $version, \"do_not_renew\": null}"
    made="$made $status $(json 'd["effective"]["do_not_renew"]["source"]')"
    api GET /reports/coverage
    expect "pkg a switch from before, in Prod and under no contract, is flagged not to be renewed: GET /reports/coverage counts it as no gap, by itself under its model, and one fewer as not covered ($counts before); with its flag taken off it has its model's, and is counted as it was" \
        "$made $(json '[d["totals"]["uncovered"], d["totals"]["not_renewed"]]')" \
        "$(python3 -c 'import json, sys; u, n = json.loads(sys.argv[1]); print(200, json.dumps([True, "own"]), json.dumps([u - 1, n + 1, [["UW-48P", 1]]]), 200, "catalog", json.dumps([u, n]))' "$counts")"

    # The balance, recorded by hand on what was carried over, with a line that
    # multiplies the engineers from before: the record of the week is replaced, with
    # an event that holds what it was, and it is corrected with a reason. A previous
    # release from before capacity lines has no engineers to multiply.
    api GET '/capacity-lines?limit=1000'
    engineer=$(json '[l["hid"] for l in d["items"] if l["name"] == "Upgrade Witness Engineer"]')
    [ "$engineer" != "[]" ] || return 0
    api POST /capacity-lines "{\"side\": \"supply\", \"category\": \"tools\", \"name\": \"Upgrade Witness Automation\", \"effect\": \"multiply\", \"factor\": \"1.5\", \"share\": \"0.5\", \"applies_to\": $engineer}"
    multiplier=$(json_field hid)
    made="$status $(json '[d["effect"], d["quantity"], d["units_each"]]')"
    api GET /reports/capacity
    made="$made $(json '[d["active"]["supply"], [[m["name"], m["units"]] for m in d["active"]["multiplying_lines"]]]')"
    api POST /capacity-records '{"note": "Recorded by hand after the upgrade"}'
    made="$made $status $(json '[d["active"]["supply"], d["adjusted"], d["row_version"]]')"
    record=$(json_field hid)
    api GET "/audit-events?record_hid=$record&limit=10"
    made="$made $(json 'sorted([e["via"], e["action"]] for e in d["items"])')"
    api GET "/capacity-records/$record"
    api PATCH "/capacity-records/$record" "{\"row_version\": $(json_field row_version), \"note\": \"Corrected after the upgrade\", \"active\": {\"supply\": \"9.00\"}}"
    made="$made $status $(json '[d["active"]["supply"], d["adjusted"], d["note"]]')"
    api POST "/capacity-lines/$multiplier/retire" '{"row_version": 1}'
    expect "pkg the capacity balance is recorded by hand on what was carried over, with a line that multiplies half of the engineers from before by one and a half, 0.75 units more: the record of the week that the system made is replaced through the API, with an event of its own, and corrected with a reason; the line is retired again" \
        "$made $status" \
        '201 ["multiply", null, null] ["4.25", [["Upgrade Witness Automation", "0.75"]]] 201 ["4.25", false, 2] [["api", "update"], ["system", "create"]] 200 ["9", true, "Corrected after the upgrade"] 200'
}
