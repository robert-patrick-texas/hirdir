# shellcheck shell=bash
# shellcheck disable=SC2034,SC2154  # Read by packaging/package-test.sh, whose names these are.
#
# Migration 0006, which came with hirdir 0.4.1: the condition of an item and what is
# observed of it, and how a cluster is managed.
#
# packaging/package-test.sh reads this file when the upgrade it tests runs the
# migration, and calls the three functions below: see "what one upgrade alone has"
# there. The previous release is then at revision 0005 or before, and through its API
# no condition, no observation and no way of managing a cluster can be stored.
#
# The migration adds three columns and two indexes to the items table as it stands. It
# makes the device_groups table anew, with six columns more and a foreign key, and says
# of every cluster there is that it is managed as one node. It loads the item_condition
# list, and leaves alone what it finds in it. And it ends the memberships of the items
# that are Released or Archived, which the releases before it let stand, each with an
# event in the audit trail: a stack that is left with one switch loses its discount.
# It creates no table, so the pass that makes it fail does so by the trigger.

witness_pair=""
witness_parted=""
gone_endpoint=""
gone_switch=""
ended_before=0
pair_before=""

# The two views of the items that are counted before and after the upgrade: the two
# switches of the second stack, and every item but those.
the_pair='?filter=serial_number:in:UWN0000D001,UWN0000D002'
all_but_pair='?filter=serial_number:ne:UWN0000D001%20serial_number:ne:UWN0000D002'

# site_condition VALUE LABEL: put a choice of the item_condition list straight into the
# database of the previous release, as the hirdir user, with an HID made as the
# application makes one.
site_condition() {
    inside runuser -u hirdir -- /opt/hirdir/python/bin/python3 -I -c '
import sqlite3, sys, uuid
from datetime import UTC, datetime

now = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")
held = sqlite3.connect("/var/lib/hirdir/hirdir.db", timeout=10)
held.execute(
    "INSERT INTO choices (hid, list, value, value_key, label, sort, active, created_at, updated_at, row_version)"
    " VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, 1)",
    (str(uuid.uuid7()), "item_condition", sys.argv[1], sys.argv[1].casefold(), sys.argv[2], 5, now, now),
)
held.commit()' "$1" "$2"
}

# released ITEM: move an item out of the team's hands, to Released, in two moves.
released() {
    local move row_version
    api GET "/items/$1"
    row_version=$(json_field row_version)
    for move in Pending-Removal:decommissioned Released:disposed; do
        api POST "/items/$1/transition" "{\"to\": \"${move%:*}\", \"reason\": \"${move#*:}\", \"row_version\": $row_version}"
        row_version=$(json_field row_version)
    done
}

# standing_membership GROUP ITEM: the current membership of an item in a group, as the
# previous release gives it: its HID, its row_version and the day it began.
standing_membership() {
    api GET "/device-groups/$1/members?include_past=true&limit=1000"
    json '" ".join(str(m[k]) for m in d["items"] if m["item_hid"] == "'"$2"'" and m["left_on"] is None for k in ("hid", "row_version", "joined_on"))'
}

# What the migration could harm, and what it is meant to change, made with the previous
# release: two items that have left the team's hands and are members still, one of
# them of a stack of two; and two conditions of a site's own.
before_0006() {
    local d1 d2 made hid
    [ "${#witness_groups[@]}" -gt 0 ] || return 0

    # The endpoint of the controller domain leaves the team's hands. The previous
    # release lets it stay a member, where every release since ends the membership at
    # the move.
    released "$witness_endpoint"
    expect "pkg one endpoint is moved to Released, and with $previous_version it is a member of the domain still" \
        "$status $(json '[d["lifecycle_state"], [g["name"] for g in d["groups"]]]')" '200 ["Released", ["upgrade-wireless"]]'

    # A second stack, of two, whose second switch has left the team's hands as well.
    # With the previous release it is a stack of two still, and its first switch has
    # the discount of a stack.
    witness_made UWN0000D001 "$witness_entry" '"lifecycle_state": "Prod"'
    d1=$made_hid
    witness_made UWN0000D002 "$witness_entry" '"lifecycle_state": "Prod"'
    d2=$made_hid
    witness_parted=$d2
    api POST /device-groups "{\"type\": \"stack\", \"name\": \"upgrade-pair\", \"members\": [{\"item_hid\": \"$d1\", \"role\": \"master\", \"position\": 1}, {\"item_hid\": \"$d2\", \"role\": \"member\", \"position\": 2}]}"
    made=$status
    witness_pair=$(json_field hid)
    witness_groups+=("$witness_pair")
    members_made=$((members_made + 2))
    released "$d2"
    api GET "/device-groups/$witness_pair"
    expect "pkg a second stack, of two, whose second switch is moved to Released: with $previous_version it is a stack of two still" \
        "$made $status $(json '[d["member_count"], d["serial_number"]]') $not_made" '201 200 [2, "UWN0000D001"] 0'
    # The request that docs/install.md gives for finding such items before an upgrade.
    api GET '/items?filter=lifecycle_state:in:Released,Archived&include_archived=true'
    expect "pkg the request of docs/install.md, items in Released or Archived with the groups they are in, lists the two" \
        "$status $(json 'sorted([i["serial_number"], [g["name"] for g in i["groups"]]] for i in d["items"])')" \
        '200 [["UWN0000A002", ["upgrade-wireless"]], ["UWN0000D002", ["upgrade-pair"]]]'

    # The previous release has no list of conditions, so no site can have entered one
    # through it. The migration leaves alone what it finds in that list all the same,
    # and that is tried with two rows written into the database: one with the value of
    # a default, under a label of the site's, and one that is the site's alone.
    api POST /choices '{"list": "item_condition", "value": "in-repair", "label": "Away for repair"}'
    expect "pkg $previous_version has no item_condition list, and refuses a choice in it" "$status" 422
    if site_condition good "Works as it should" >/dev/null 2>&1 && site_condition in-repair "Away for repair" >/dev/null 2>&1; then
        pass "pkg so two conditions are written into its database as a site's own: good, under a label of the site's, and in-repair"
    else
        fail "pkg so two conditions are written into its database as a site's own: good, under a label of the site's, and in-repair"
    fi

    # What the previous release counts of the second stack. The rest of the inventory
    # must be counted after the upgrade as it was before, and this stack otherwise.
    counted_view=$all_but_pair
    pair_before=$(counted_now "$the_pair")
    expect "pkg $previous_version counts the two switches of the second stack as one component, the one in Prod, with half its support weight of 1.25: the discount of a stack of two" \
        "$pair_before" '[2, 1, 1, 0.63, "36000.00", "0.00"]'

    # What the migration is meant to change: the two memberships that the previous
    # release let stand, and what follows from them in what an item and a group say.
    gone_endpoint=$(standing_membership "$witness_domain" "$witness_endpoint")
    gone_switch=$(standing_membership "$witness_pair" "$witness_parted")
    check "pkg and the two memberships that $previous_version lets stand though their items are Released: of the endpoint and of the switch (${gone_endpoint:-none}; ${gone_switch:-none})" \
        test -n "$gone_endpoint" -a -n "$gone_switch"
    meant[items]+=" $witness_endpoint.groups $witness_endpoint.controllers $witness_parted.groups"
    meant[device-groups]+=" $witness_domain.member_count $witness_pair.member_count"
    for hid in "${gone_endpoint%% *}" "${gone_switch%% *}"; do
        meant[members]+=" $hid.left_on $hid.row_version $hid.updated_at"
    done
    rows_apart[device_group_members]="${gone_endpoint%% *},${gone_switch%% *}"
    ended_before=$(sqlite_value /var/lib/hirdir/hirdir.db 'SELECT count(*) FROM device_group_members WHERE left_on IS NOT NULL')
    # It loads the conditions beside the choices that are there.
    may_add[choices]=yes

    # What it adds to the tables that hold a site's records.
    new_columns[items]='condition VARCHAR(40) NULL -
observed_status VARCHAR(12) NULL -
observed_at DATETIME NULL -'
    new_keys[items]='index ix_items_condition on condition unique=0 origin=c partial=0
index ix_items_observed_status on observed_status unique=0 origin=c partial=0'
    new_columns[device_groups]='managed_as VARCHAR(20) NULL -
expected_members INTEGER NULL -
observed_status VARCHAR(12) NULL -
observed_at DATETIME NULL -
observed_master_hid VARCHAR(36) NULL -
master_observed_at DATETIME NULL -'
    new_keys[device_groups]='foreign key observed_master_hid to items.hid'
}

# membership_ended WHEN WHAT "HID ROW_VERSION JOINED_ON" GROUP ITEM: a membership that
# the previous release let stand, of an item that had left the team's hands, was ended
# by the upgrade: on the day of the upgrade, at the next row_version, with an event in
# the audit trail that the system made, and the item is in no group. The day is the one
# the upgrade ran on, by the clock of the host or by the calendar of the application.
membership_ended() {
    local when=$1 what=$2 member=${3%% *} group=$4 item=$5 version joined found left
    version=${3#* }
    joined=${version#* }
    version=${version%% *}
    api GET "/device-groups/$group/members?include_past=true&limit=1000"
    found=$(json '[[m["left_on"], m["row_version"], m["joined_on"]] for m in d["items"] if m["hid"] == "'"$member"'"]')
    left=$(json '([m["left_on"] for m in d["items"] if m["hid"] == "'"$member"'"] or [None])[0]')
    case " $upgrade_days $witness_day " in
        *" $left "*) ;;
        *) left="$left, which is not a day the upgrade ran on ($upgrade_days $witness_day)" ;;
    esac
    expect "pkg $when the membership of $what, which $previous_version let stand, is ended: on the day of the upgrade, at the next row_version" \
        "$status $found" "200 [[\"$left\", $((version + 1)), \"$joined\"]]"
    api GET "/audit-events?record_hid=$member&limit=1"
    expect "pkg $when and the audit trail holds that: an update of a device_group_member, made by the system, of left_on from nothing to that day" \
        "$status $(json '[[e["via"], e["action"], e["record_type"], e["actor_hid"], e["changes"]] for e in d["items"]]')" \
        "200 [[\"system\", \"update\", \"device_group_member\", null, [{\"field\": \"left_on\", \"new\": \"$left\", \"old\": null}]]]"
    api GET "/items/$item"
    expect "pkg $when and its item, which is Released, is in no group, and has no controllers of a domain" \
        "$status $(json '[d["lifecycle_state"], d["groups"], d["controllers"]]')" '200 ["Released", [], []]'
}

# What the migration changed, and what it put into the columns and the list it made,
# looked at by itself with the new version serving.
changed_0006() {
    local when=$1
    [ -n "$gone_endpoint" ] || return 0

    membership_ended "$when" "the endpoint in its domain" "$gone_endpoint" "$witness_domain" "$witness_endpoint"
    membership_ended "$when" "the switch in its stack" "$gone_switch" "$witness_pair" "$witness_parted"
    api GET "$every_group"
    expect "pkg $when the domain has two current members where it had three, and the second stack one where it had two" \
        "$(json '[[g["name"], g["member_count"]] for g in d["items"] if g["hid"] in ("'"$witness_domain"'", "'"$witness_pair"'")]')" \
        '[["upgrade-pair", 1], ["upgrade-wireless", 2]]'
    expect "pkg $when the device_group_members table holds four memberships that are ended where it held two" \
        "$(sqlite_value /var/lib/hirdir/hirdir.db 'SELECT count(*) FROM device_group_members WHERE left_on IS NOT NULL')" \
        "$((ended_before + 2))"

    # The columns it added hold nothing yet, but for how a cluster is managed.
    api GET "$every_item"
    expect "pkg $when each item has no condition, nothing observed of it, and a health of unknown" \
        "$(json 'sorted({json.dumps([i["condition"], i["observed_status"], i["observed_at"], i["health"]["value"]]) for i in d["items"]})')" \
        '["[null, null, null, \"unknown\"]"]'
    expect "pkg $when and the three new columns of the items table hold nothing" \
        "$(sqlite_value /var/lib/hirdir/hirdir.db 'SELECT count(*) FROM items WHERE condition IS NOT NULL OR observed_status IS NOT NULL OR observed_at IS NOT NULL')" 0
    expect "pkg $when of the six new columns of the device_groups table, managed_as says one for each of the two clusters and nothing for a group of any other type, and the other five hold nothing" \
        "$(sqlite_text "SELECT type, coalesce(managed_as, '-'), count(*), count(expected_members) + count(observed_status) + count(observed_at) + count(observed_master_hid) + count(master_observed_at) FROM device_groups GROUP BY type, managed_as ORDER BY type")" \
        "cluster one 2 0
controller_domain - 1 0
custom - 1 0
stack - 2 0"
    api GET "/device-groups/$witness_stack"
    expect "pkg $when the stack still shows the serial number of its master, which is the one intended: nothing is seen of a master yet" \
        "$status $(json '[d["serial_number"], d["serial_source"], d["master"]["serial_number"], d["observed_master_hid"], d["master_observed_at"], d["member_count"]]')" \
        '200 ["UWN0000S001", "intended", "UWN0000S001", null, null, 3]'
    api GET "/device-groups/$witness_cluster"
    expect "pkg $when the cluster is managed as one, as $previous_version counted every cluster" \
        "$status $(json_field managed_as)" "200 one"

    # The second stack is one switch alone now.
    expect "pkg $when the second stack is one switch alone, and its numbers follow: the same component, value and cost, and the whole support weight of 1.25, with no discount" \
        "$pair_before -> $(counted_now "$the_pair")" \
        '[2, 1, 1, 0.63, "36000.00", "0.00"] -> [2, 1, 1, 1.25, "36000.00", "0.00"]'
    api GET "/device-groups/$witness_pair"
    expect "pkg $when and it says that it is degraded, because it is one switch alone" \
        "$status $(json '[d["member_count"], d["serial_number"], d["health"]["value"], d["health"]["reasons"]]')" \
        '200 [1, "UWN0000D001", "degraded", ["it is one switch alone"]]'

    # The list of conditions, loaded beside what the site had in it.
    api GET '/choices?list=item_condition'
    expect "pkg $when the item_condition list is loaded: its six defaults and the site's two, with good there once, under the label the site gave it" \
        "$status $(json '" ".join(sorted(c["value"] + "=" + c["label"].replace(" ", "_") for c in d))')" \
        "200 dead=Dead degraded=Degraded failed=Failed good=Works_as_it_should in-repair=Away_for_repair suspect=Suspect untested=Untested"
    api GET /choices
    expect "pkg $when and the replacement_reason list is as $previous_version had it: its five defaults, rma under the label the site gave it, and the reason of the site's own" \
        "$(json '" ".join(sorted(c["value"] + "=" + c["label"].replace(" ", "_") for c in d if c["list"] == "replacement_reason"))')" \
        "other=Other project=Project refresh=Refresh rma=Returned_to_the_maker site-swap=Swapped_at_the_site upgrade=Upgrade"
}

# What is new can be said of what was carried over.
after_0006() {
    local made
    [ -n "$gone_endpoint" ] || return 0
    api GET "/items/$witness_item"
    api PATCH "/items/$witness_item" "{\"row_version\": $(json_field row_version), \"condition\": \"in-repair\", \"observed_status\": \"present\"}"
    expect "pkg an item from before takes the condition the site entered itself, and an observation, and has a health" \
        "$status $(json '[d["condition"], d["observed_status"], d["health"]["value"]]')" '200 ["in-repair", "present", "good"]'
    api GET "/device-groups/$witness_cluster"
    api PATCH "/device-groups/$witness_cluster" "{\"row_version\": $(json_field row_version), \"managed_as\": \"members\"}"
    made=$status
    api GET '/reports/summary?filter=group.name:eq:upgrade-cluster'
    expect "pkg and the cluster from before, said to be managed by its members, is two managed nodes" \
        "$made $status $(json 'd["totals"]["managed_node_count"]')" "200 200 2"
}
