# shellcheck shell=bash
# shellcheck disable=SC2034,SC2154  # Read by packaging/package-test.sh, whose names these are.
#
# hirdir 0.4.2, which has no migration, and says or reads two things differently of what
# it holds as the release before held it.
#
# packaging/package-test.sh reads this file when the upgrade it tests crosses 0.4.2: the
# previous release is older, and the new version is 0.4.2 or a later one. It calls the
# three functions below: see "what one upgrade alone has" there.
#
# The reason for a health that is not known names, from 0.4.2, the condition that is
# there. Nothing that is stored differs, and the health of the two items whose condition
# is the site's own, or untested, reads otherwise than the release before gave it.
#
# A moment that names no zone is read, from 0.4.2, in the application's time zone. The
# releases before read it as UTC and stored that moment. What is stored is a moment,
# and the upgrade changes none: only what is entered from then on is read the new way.

# What the previous release keeps for 09:00 written with no zone.
zoneless_moment=2026-11-03T09:00:00Z
zoneless_said="09:00 in UTC, as the releases before 0.4.2 read it"

before_0_4_2() {
    [ -n "$witness_own" ] || return 0
    meant[items]+=" $witness_own.health $witness_untested.health"
}

changed_0_4_2() {
    local when=$1 found
    [ -n "$witness_own" ] || return 0
    api GET "/items/$witness_own"
    found=$(json '[d["condition"], d["health"]]')
    api GET "/items/$witness_untested"
    expect "pkg $when the health of the two items whose condition is the site's own, or untested, is not known, as it was, and the reason of each names the condition that is there" \
        "$found $(json '[d["condition"], d["health"]]')" \
        '["in-repair", {"reasons": ["its condition is in-repair, which says nothing of its health, and nothing is observed"], "value": "unknown"}] ["untested", {"reasons": ["its condition is untested, and nothing is observed"], "value": "unknown"}]'
}

after_0_4_2() {
    local made
    [ -n "$witness_moment" ] || return 0
    api GET "/items/$witness_moment"
    made=$(json_field observed_at)
    api GET "/items/$witness_item"
    api PATCH "/items/$witness_item" "{\"row_version\": $(json_field row_version), \"observed_status\": \"present\", \"observed_at\": \"2026-11-03T09:00:00\"}"
    expect "pkg the moment that $previous_version stored for 09:00 with no zone is the moment it was, 09:00 in UTC; the same words given to $version are 09:00 in New York, 14:00 in UTC" \
        "$made $status $(json_field observed_at)" "2026-11-03T09:00:00Z 200 2026-11-03T14:00:00Z"
    api GET '/items?filter=observed_at:eq:2026-11-03T09:00:00&sort=serial_number'
    made=$(json '[i["serial_number"] for i in d["items"]]')
    api GET '/items?filter=observed_at:eq:2026-11-03T09:00:00Z&sort=serial_number'
    expect "pkg a filter on that moment reads its value the same way: with no zone it finds the item that was told so after the upgrade, and with Z the one from before" \
        "$made $status $(json '[i["serial_number"] for i in d["items"]]')" '["UWN0000X001"] 200 ["UWN0000F001"]'
    api GET "/device-groups/$witness_stack"
    api PATCH "/device-groups/$witness_stack" "{\"row_version\": $(json_field row_version), \"master_observed_at\": \"2026-11-03T09:00:00\"}"
    expect "pkg and so it is with the moment a master was seen at: stated again with no zone, it is 14:00 in UTC where it was 09:00" \
        "$status $(json_field master_observed_at)" "200 2026-11-03T14:00:00Z"
}
