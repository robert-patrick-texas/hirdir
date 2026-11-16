# shellcheck shell=bash
# shellcheck disable=SC2034,SC2154  # Read by packaging/package-test.sh, whose names these are.
#
# Migration 0011, which came with hirdir 0.9.0: reference files, and the records they
# are on.
#
# packaging/package-test.sh reads this file when the upgrade it tests runs the
# migration, and calls the three functions below: see "what one upgrade alone has"
# there. The previous release is then at revision 0010 or before: it knows no reference,
# has no reference_kind list and no setting of the kinds of file, and its nginx snippet
# lets 20 MB through.
#
# The migration creates reference_files and then reference_attachments, which is the
# one that the pass whose migration fails puts in its way, with the first made by then
# and undone with the rest. Then it loads the reference_kind list, and leaves alone a
# value that it finds there. It alters no table that holds a site's records.
#
# It changes nothing that is held: there is no reference until somebody adds one, and no
# setting is set. It writes no audit event. Beside the database, the package makes
# /var/lib/hirdir/files, the store of the content, empty; puts max_reference_megabytes
# into the settings file, commented out; and writes the nginx snippet again with the
# larger of the two limits of that file, 100m. docs/install.md says all of it under
# "From 0.8.0 to 0.9.0", and what is said there is what is looked for here.
writes_no_event=yes
# It loads a list beside the choices that are there.
may_add[choices]=yes

# Set by before_0011 when the previous release holds an inventory, for the other two.
referenced=""

# reference_choice LIST VALUE LABEL: put a choice straight into the database of the
# previous release, as the hirdir user, with an HID made as the application makes one.
# The previous release refuses a choice in a list that it does not have.
reference_choice() {
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

# What the migration could harm, made with the previous release. It alters no table of
# the inventory, which witness_kept keeps and compares whole all the same. The list that
# it loads is refused by the previous release, so a site's own values in it are written
# into its database, as migration-0010.sh does; and a value that the list loads is put
# by the site into another list, which the migration is to leave as it is.
before_0011() {
    local made
    [ -n "$witness_entry" ] || return 0
    referenced=yes

    api POST /choices '{"list": "reference_kind", "value": "cabling_record", "label": "Cabling record"}'
    expect "pkg $previous_version has no reference_kind list, and refuses a choice in it" \
        "$status $(json '[e["field"] for e in d.get("errors", [])]')" '422 ["list"]'
    if reference_choice reference_kind photograph "Photograph of the site" >/dev/null 2>&1 &&
        reference_choice reference_kind cabling_record "Cabling record" >/dev/null 2>&1; then
        pass "pkg so two choices are written into its database as a site's own: photograph in the reference_kind list under a label of the site's, and cabling_record beside it"
    else
        fail "pkg so two choices are written into its database as a site's own: photograph in the reference_kind list under a label of the site's, and cabling_record beside it"
    fi
    api POST /choices '{"list": "state_reason", "value": "photograph", "label": "Photographed at the audit"}'
    made=$status
    api GET '/choices?list=state_reason'
    expect "pkg and photograph, a value that the reference_kind list loads, is a reason for a move of the site's own, through the API of $previous_version" \
        "$made $status $(json '[c["label"] for c in d if c["value"] == "photograph"]')" '201 200 ["Photographed at the audit"]'

    # What the previous release does not know: a reference, the list of what a record
    # has, and the setting of the kinds of file. A route it does not have is not found,
    # or, asked for by POST, not allowed.
    made=""
    for path in /reference-files POST:/reference-files/links "/locations/${witness_room:-none}/references" "/catalog-entries/$witness_entry/references"; do
        case $path in
            POST:*) api POST "${path#POST:}" '{}' ;;
            *) api GET "$path" ;;
        esac
        case $status in 404 | 405) made="$made none" ;; *) made="$made $status" ;; esac
    done
    api GET /settings
    expect "pkg $previous_version has no reference, no list of what a record has and no reference_file_types among its settings" \
        "$made $status $(json '[s["key"] for s in d if "reference" in s["key"]]')" ' none none none none 200 []'
}

# What the migration made, and what the new version says of what was carried over,
# looked at by itself with the new version serving.
changed_0011() {
    local when=$1 database=/var/lib/hirdir/hirdir.db made path
    [ -n "$referenced" ] || return 0

    expect "pkg $when the two tables that the migration creates are empty: reference_files and reference_attachments" \
        "$(sqlite_value "$database" 'SELECT (SELECT count(*) FROM reference_files) + (SELECT count(*) FROM reference_attachments)')" 0
    expect "pkg $when and no row refers to a record that is not there" \
        "$(sqlite_text 'PRAGMA foreign_key_check' | wc -l)" 0
    api GET '/reference-files?limit=1'
    made="$status:$(json_field total)"
    for path in "/catalog-entries/$witness_entry" "/items/$witness_full"; do
        api GET "$path/references?limit=1"
        made="$made $status:$(json_field total)"
    done
    if [ -n "$witness_site" ]; then
        for path in "/locations/$witness_room" "/sites/$witness_site"; do
            api GET "$path/references?limit=1"
            made="$made $status:$(json_field total)"
        done
    fi
    expect "pkg $when the list of references is there and empty, and so is what the catalog entry, the item, the room and the site from before have, of their own and from above" \
        "$made" "$(if [ -n "$witness_site" ]; then echo '200:0 200:0 200:0 200:0 200:0'; else echo '200:0 200:0 200:0'; fi)"

    # The list that it loads, beside what the site had put into it and into another.
    api GET '/choices?list=reference_kind'
    made="$status $(json '" ".join(sorted(c["value"] + "=" + c["label"].replace(" ", "_") for c in d))')"
    api GET '/choices?list=state_reason'
    expect "pkg $when the reference_kind list holds its twelve defaults and the site's own, with photograph there once, under the label the site gave it; and photograph in the reasons for a move is as the site made it" \
        "$made $status $(json '[c["label"] for c in d if c["value"] == "photograph"]')" \
        '200 administration_guide=Administration_guide cabling_record=Cabling_record data_sheet=Data_sheet diagram=Diagram floor_plan=Floor_plan installation_guide=Installation_guide letter_of_authorization=Letter_of_authorization map=Map other=Other photograph=Photograph_of_the_site release_notes=Release_notes sketch=Sketch test_results=Test_results 200 ["Photographed at the audit"]'

    # The setting of the kinds of file is at its default, and what is fixed beside it.
    api GET /settings
    expect "pkg $when reference_file_types is at its default, the twenty-four kinds of file from jpg to zip, and listed after the settings as fixed are refused_file_types, the forty-seven of a web page, a script or a program, and max_attachments_per_request, 1000" \
        "$status $(json '[[s["key"], s["is_default"], s.get("fixed", False)] + ([len(s["value"]), s["value"][0], s["value"][-1]] if isinstance(s["value"], list) else [s["value"]]) for s in d if s["key"] in ("reference_file_types", "refused_file_types", "max_attachments_per_request")]')" \
        '200 [["reference_file_types", true, false, 24, "jpg", "zip"], ["refused_file_types", true, true, 47, "htm", "cpl"], ["max_attachments_per_request", true, true, 1000]]'

    # Beside the database: the store, the settings file and the nginx snippet.
    expect "pkg $when /var/lib/hirdir/files is there, the hirdir user's alone, with no content in it, and hirdir admin check says so" \
        "$(inside stat -c '%a %U:%G' /var/lib/hirdir/files 2>&1) $(inside find /var/lib/hirdir/files -type f ! -path '*/.incoming/*' 2>&1 | wc -l) $(inside hirdir admin check 2>&1 | grep -c '^reference files: 0 with content, kept in 0 files of 0 bytes in /var/lib/hirdir/files$')" \
        "750 hirdir:hirdir 0 1"
    expect "pkg $when the settings file has max_reference_megabytes under [files], commented out at its default, and the nginx snippet the limit of 100m, the larger of the two" \
        "$(inside grep -cx '# max_reference_megabytes = 100' /etc/hirdir/config.toml 2>&1) $(inside grep -c '^    client_max_body_size 100m;$' /etc/nginx/snippets/hirdir.conf 2>&1)" "1 1"
}

# reference_lists RECORDS: what each record named has, as "HID:source" in order, one
# record to a group, from GET /RECORDS/HID/references.
reference_lists() {
    local entry listed=""
    for entry in "$@"; do
        api GET "/${entry%%:*}/${entry#*:}/references?limit=1000"
        listed="$listed $status$(json '"".join(" " + r["hid"] + ":" + r["source"] for r in d["items"])')"
    done
    printf '%s' "${listed# }"
}

# What is new, tried on what was carried over: files and a link on the records from
# before, one of them on three at once, the retired item among them, listed where they
# are attached and from above, downloaded byte for byte; then erased again, so that the
# rest of this pass starts with no reference and an empty store.
after_0011() {
    local land circuit guide photo link runbook made wanted hid
    [ -n "$referenced" ] && [ -n "$witness_site" ] || return 0
    api GET '/regions?limit=1000'
    land=$(json '[r["hid"] for r in d["items"] if r["name"] == "Upgrade Land"][0]')
    api GET '/circuits?include_drafts=true&include_archived=true&limit=1000'
    circuit=$(json '([c["hid"] for c in d["items"] if c["name"] == "Upgrade Witness Link"] or [""])[0]')

    reference_file "$work/upgrade-guide.pdf" pdf 1.5
    reference_file "$work/upgrade-room.png" png 2
    reference_file "$work/upgrade-runbook.pdf" pdf 0.5
    upload "$work/upgrade-guide.pdf" uw-48p-admin.pdf administration_guide "UW-48P administration guide" "$witness_entry"
    made=$status
    guide=$(json_field hid)
    upload "$work/upgrade-room.png" room-701.png photograph "Room 701" "$witness_room"
    made="$made $status"
    photo=$(json_field hid)
    api POST /reference-files/links "{\"title\": \"Upgrade Site map\", \"kind\": \"map\", \"url\": \"https://www.example.net/upgrade/site-map.pdf\", \"attach_to\": [\"$witness_site\"]}"
    made="$made $status $(json_field form)"
    link=$(json_field hid)
    upload "$work/upgrade-runbook.pdf" upgrade-runbook.pdf other "Upgrade runbook" "$land"
    made="$made $status"
    runbook=$(json_field hid)
    api POST "/reference-files/$runbook/attachments" "{\"records\": [${circuit:+\"$circuit\", }\"$witness_retired\"]}"
    expect "pkg on the records from before: an administration guide on the catalog entry, a photograph on the room, a link on the site, and a runbook on the region$([ -n "$circuit" ] && echo ', which is then put on the first circuit and') on the item that was retired, which takes it" \
        "$made $status $(json_field attachment_count)" "201 201 201 link 201 200 $([ -n "$circuit" ] && echo 3 || echo 2)"

    # Each is listed where it is attached, and from above: the item with every value is
    # of the model and in the room, which is in the building, at the site, in the region.
    wanted="200 $guide:catalog $photo:location $link:site $runbook:region 200 $runbook:own $guide:catalog 200 $photo:own $link:site $runbook:region"
    if [ -n "$circuit" ]; then wanted="$wanted 200 $runbook:own"; fi
    expect "pkg the item from before lists the guide from its model, the photograph from its room, the link from its site and the runbook from its region, nearest first; the retired item its own and its model's; the room its own and those above it$([ -n "$circuit" ] && echo '; the circuit its own')" \
        "$(reference_lists "items:$witness_full" "items:$witness_retired" "locations:$witness_room" ${circuit:+"circuits:$circuit"})" "$wanted"
    expect "pkg and each file comes back from the store byte for byte" \
        "$(stored_sums "$guide" "$photo" "$runbook" | xargs)" \
        "$(sha "$work/upgrade-guide.pdf") $(sha "$work/upgrade-room.png") $(sha "$work/upgrade-runbook.pdf")"

    # Erased again: the record and the content of each.
    made=""
    for hid in "$guide" "$photo" "$link" "$runbook"; do
        api DELETE "/reference-files/$hid"
        made="$made $status"
    done
    api GET '/reference-files?limit=1'
    expect "pkg the four are erased with $version, and the store holds none of their content" \
        "$made $status $(json_field total) $(inside find /var/lib/hirdir/files -type f ! -path '*/.incoming/*' 2>&1 | wc -l)" \
        " 204 204 204 204 200 0 0"
}
