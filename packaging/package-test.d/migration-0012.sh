# shellcheck shell=bash
# shellcheck disable=SC2034,SC2154  # Read by packaging/package-test.sh, whose names these are.
#
# Migration 0012, which came with hirdir 0.9.3: every person a contact, of which a user
# is a part that it plays, a second number for each contact, and the kinds of external
# system a list.
#
# packaging/package-test.sh reads this file when the upgrade it tests runs the
# migration, and calls the three functions below: see "what one upgrade alone has"
# there. The previous release is then at revision 0011 or before: a user keeps a display
# name and an email of its own, a contact has one number, and the kind of an external
# system is one of eight that are fixed.
#
# The migration adds phone2 to contacts as the table stands, and contact_hid to users,
# with its foreign key and its uniqueness, which on SQLite makes users anew. It gives
# each user that is no service account and has a display name or an email a contact,
# the users that may sign in before those that are disabled and each by username: the
# contact that has that email already, in any case, which it leaves as it is; or a new
# one, named with the display name, or with the username where there is none, that
# holds the email where it is of the form name@host, and nothing where it is not. Of two
# users with one email, the first has the contact and the second none, as a contact is
# one user's at most. It writes audit events made by system, with the request ID
# upgrade-0012: one for each contact it makes, one for each contact it gives a user,
# with the user, and one for each user that had a display name or an email, the service
# accounts among them, that keeps what was dropped and the contact it was given. Then it
# drops display_name and email from users, making the table anew again, so that a
# service account loses the display name it had; it gives the kind of an external
# system 40 characters, making that table anew; and last it loads the system_kind list
# with the eight kinds, leaving alone a value that it finds there. It creates no table,
# so the pass whose migration fails puts the trigger on alembic_version in its way, and
# all of it has to be undone.
#
# docs/install.md says what it does under "From 0.9.2 to 0.9.3", and what is said there
# is what is looked for here; P-172 and P-174 in docs/decisions.md say it in full.
upgrade_events=upgrade-0012
# It makes contacts, and loads a list beside the choices that are there.
may_add[contacts]=yes
may_add[choices]=yes
also new_columns contacts 'phone2 VARCHAR(50) NULL -'
also altered_columns external_systems 'kind VARCHAR(40) NOT NULL -'
# The table of the accounts, which is no part of the inventory, is kept and compared
# as the inventory's tables are.
more_tables="${more_tables:+$more_tables }users"
gone_columns[users]="${gone_columns[users]:+${gone_columns[users]} }display_name email"
also new_columns users 'contact_hid VARCHAR(36) NULL -'
also new_keys users 'foreign key contact_hid to contacts.hid'
also new_keys users 'index - on contact_hid unique=1 origin=u partial=0'

# Set by before_0012 when the previous release holds an inventory, for the other two.
peopled=""
# The users that before_0012 makes, by username, and the access code of the first.
declare -gA people_0012=()
people_code=""
# The contact from before that a user has the email of, in another case, by its HID.
people_pat=""
# The external systems that before_0012 makes, by kind.
declare -gA systems_0012=()

# What each user that before_0012 makes is to be after the upgrade: its username, the
# name and the email it shows, and the contact it is, by its name and email and whether
# it is a new one or one from before, or null; and by how much its row_version moves.
people_wanted_0012() {
    printf '%s' '[["upgrade-ana", "Upgrade Ana", "upgrade.ana@example.org", ["Upgrade Ana", "upgrade.ana@example.org", "new"], 1], ["upgrade-bot", "", "", null, 0], ["upgrade-jo", "", "", null, 0], ["upgrade-jo-2", "Upgrade Jo", "upgrade.jo@example.org", ["Upgrade Jo", "upgrade.jo@example.org", "new"], 1], ["upgrade-kim", "Upgrade Kim", "upgrade.kim@example.org", ["Upgrade Kim", "upgrade.kim@example.org", "new"], 1], ["upgrade-kim-2", "", "", null, 0], ["upgrade-lee", "", "", null, 0], ["upgrade-max", "Upgrade Max", "", ["Upgrade Max", null, "new"], 1]'
    if [ -n "$people_pat" ]; then
        printf '%s' ', ["upgrade-pat", "Upgrade Pat", "upgrade.pat@example.net", ["Upgrade Pat", "upgrade.pat@example.net", "from before"], 1]'
    fi
    printf '%s' ', ["upgrade-quinn", "upgrade-quinn", "upgrade.quinn@example.org", ["upgrade-quinn", "upgrade.quinn@example.org", "new"], 1], ["upgrade-ren", "Upgrade Ren", "", ["Upgrade Ren", null, "new"], 1], ["upgrade-sol", "upgrade-sol", "", ["upgrade-sol", null, "new"], 1]]'
}

# events_wanted_0012: the audit events of the upgrade that are to be in the trail, as
# changed_0012 prints those that are: for each user that had a display name or an email,
# by what people_wanted_0012 and accounts_wanted say of it, a create of the contact
# where it is a new one, an update of the contact, which names the user, where it was
# given one, and an update of the user, which keeps its display name and its email as
# they were, in that order, each to nothing, and the contact it was given.
events_wanted_0012() {
    python3 -c '
import json, sys

then = {u["username"]: u for u in json.load(open(sys.argv[1], encoding="utf-8"))["items"]}
events = []
for username, _, _, person, _ in json.loads(sys.argv[2]) + json.loads(sys.argv[3]):
    was = then[username]
    changes = [[field, was[field], None] for field in ("display_name", "email") if was[field]]
    if person:
        if person[2] == "new":
            events.append(["create", "contact", person[0], [["name", None, person[0]]] + ([["email", None, person[1]]] if person[1] else []) + [["record_status", None, "active"]]])
        events.append(["update", "contact", person[0], [["user_hid", None, username]]])
        changes.append(["contact_hid", None, person[0]])
    if changes:
        events.append(["update", "user", username, changes])
print(json.dumps([sorted(events, key=json.dumps), ["[\"system\", null, null]"]]))' \
        "$work/kept-people-0012.json" "$(people_wanted_0012)" "$(accounts_wanted)"
}

# system_choice VALUE LABEL: put a choice of the system_kind list straight into the
# database of the previous release, as the hirdir user, with an HID made as the
# application makes one. The previous release refuses a choice in a list it does not
# have.
system_choice() {
    inside runuser -u hirdir -- /opt/hirdir/python/bin/python3 -I -c '
import sqlite3, sys, uuid
from datetime import UTC, datetime

now = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")
held = sqlite3.connect("/var/lib/hirdir/hirdir.db", timeout=10)
held.execute(
    "INSERT INTO choices (hid, list, value, value_key, label, sort, active, created_at, updated_at, row_version)"
    " VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, 1)",
    (str(uuid.uuid7()), "system_kind", sys.argv[1], sys.argv[1].casefold(), sys.argv[2], 5, now, now),
)
held.commit()' "$1" "$2"
}

# people_now WHO: the users in the last response, GET /users, as people_wanted_0012
# gives them, beside what before_0012 kept of them and of the contacts: WHO is mine,
# the users that before_0012 made, or theirs, the accounts of the pass.
people_now() {
    python3 -c '
import json, sys

users_then, contacts_then, now = (json.load(open(path, encoding="utf-8")) for path in sys.argv[1:4])
mine = set(sys.argv[5].split())
then = {u["hid"]: u for u in users_then["items"]}
known = {c["hid"] for c in contacts_then.get("items", [])}
said = []
for user in now["items"]:
    if (user["username"] in mine) != (sys.argv[4] == "mine") or user["hid"] not in then:
        continue
    person = user["contact"]
    if person is not None:
        person = [person["name"], person["email"], "from before" if person["hid"] in known else "new"]
    said.append([user["username"], user["display_name"], user["email"], person, user["row_version"] - then[user["hid"]]["row_version"]])
print(json.dumps(sorted(said, key=lambda u: u[0])))' \
        "$work/kept-people-0012.json" "$work/kept-contacts-0012.json" "$work/body" "$1" "${!people_0012[*]}"
}

# accounts_wanted: what the accounts of the pass, which before_0012 found, are to be
# after the upgrade, as people_now prints them. None of them has an email: one that has
# a display name and is no service account is a new contact of that name, and the
# others have none and show nothing.
accounts_wanted() {
    python3 -c '
import json, sys

said = []
for user in json.load(open(sys.argv[1], encoding="utf-8"))["items"]:
    if user["display_name"] and not user["is_service_account"] and not user["email"]:
        said.append([user["username"], user["display_name"], "", [user["display_name"], None, "new"], 1])
    elif user["email"]:
        said.append([user["username"], "an email, which this file does not expect of an account of the pass", "", None, 0])
    else:
        said.append([user["username"], "", "", None, 0])
print(json.dumps(sorted(said, key=lambda u: u[0])))' "$work/kept-people-0012-accounts.json"
}

# What the migration could harm, made with the previous release: users of every kind
# that it acts on, beside the accounts of the pass, and an external system of each kind
# that it can hold. The list that it loads is refused by the previous release, so a
# value of the site's own in it, and one of its defaults under a label of the site's,
# are written into its database, as migration-0010.sh does.
before_0012() {
    local made wanted body name hid entry kind accounts="" changed=""
    local -a bodies
    [ -n "$witness_entry" ] || return 0
    peopled=yes

    # The accounts of the pass, made before this file made any. Each is let be by the
    # comparison of the rows of users, which signing in changes, and is looked at by the
    # API: the one with a display name is given a contact.
    api GET '/users?limit=1000'
    keep people-0012-accounts
    accounts=$(json '",".join(u["hid"] for u in d["items"])')
    changed=$(json '"".join((" " + u["hid"] + ".row_version " + u["hid"] + ".updated_at") if u["display_name"] and not u["is_service_account"] else (" " + u["hid"] + ".display_name" if u["display_name"] else "") for u in d["items"])')

    # Users of every kind that the migration acts on: with a display name and an email;
    # with an email and no display name; two of one email, the first by username and
    # the second; two of another, the first by username disabled; with neither; a
    # service account with a display name; three whose email a contact would refuse,
    # with a space, with no @ and with a second one, the second with no display name;
    # and, where the previous release has contacts, one with the email of the contact
    # from before, written in another case, and a display name of its own.
    bodies=('{"username": "upgrade-ana", "display_name": "Upgrade Ana", "email": "upgrade.ana@example.org"}'
        '{"username": "upgrade-quinn", "email": "upgrade.quinn@example.org"}'
        '{"username": "upgrade-kim", "display_name": "Upgrade Kim", "email": "upgrade.kim@example.org"}'
        '{"username": "upgrade-kim-2", "display_name": "Upgrade Kim, second account", "email": "upgrade.kim@example.org"}'
        '{"username": "upgrade-jo", "display_name": "Upgrade Jo, old account", "email": "upgrade.jo@example.org"}'
        '{"username": "upgrade-jo-2", "display_name": "Upgrade Jo", "email": "upgrade.jo@example.org"}'
        '{"username": "upgrade-lee"}'
        '{"username": "upgrade-bot", "is_service_account": true, "display_name": "Upgrade nightly robot"}'
        '{"username": "upgrade-max", "display_name": "Upgrade Max", "email": "upgrade max@example.org"}'
        '{"username": "upgrade-sol", "email": "upgrade.sol"}'
        '{"username": "upgrade-ren", "display_name": "Upgrade Ren", "email": "upgrade.ren@@example.org"}')
    if [ -n "$witness_site" ]; then
        api GET '/contacts?limit=1000'
        people_pat=$(json '([c["hid"] for c in d["items"] if c["email"] == "upgrade.pat@example.net"] or [""])[0]')
    fi
    if [ -n "$people_pat" ]; then
        bodies+=('{"username": "upgrade-pat", "display_name": "Pat of the upgrade", "email": "Upgrade.Pat@Example.NET"}')
    fi
    made=""
    wanted=""
    for body in "${bodies[@]}"; do
        name=$(python3 -c 'import json, sys; print(json.loads(sys.argv[1])["username"])' "$body")
        people_0012[$name]=none
    done
    for body in "${bodies[@]}"; do
        api POST /users "$body"
        made="$made $status"
        wanted="$wanted 201"
        name=$(python3 -c 'import json, sys; print(json.loads(sys.argv[1])["username"])' "$body")
        if [ "$status" = 201 ]; then
            people_0012[$name]=$(json 'd["user"]["hid"]')
            users_made=$((users_made + 1))
        fi
        if [ "$name" = upgrade-ana ]; then people_code=$(json_field access_code); fi
    done
    api PATCH "/users/${people_0012[upgrade-jo]}" '{"row_version": 1, "disabled": true}'
    made="$made $status"
    wanted="$wanted 200"
    api GET '/users?limit=1000'
    expect "pkg $previous_version holds users of every kind that migration 0012 acts on, each with no role: with a display name and an email, with an email alone, two with one email, two with another, the first by username disabled, with neither, a service account with a display name, three with an email that is no address$([ -n "$people_pat" ] && echo ', and one with the email of the contact from before, Upgrade Pat, in another case, and a name of its own'); each keeps the name and the email it was given" \
        "$made $status $(json 'sorted([u["username"], u["display_name"], u["email"], u["is_service_account"], u["disabled"], u["role"]] for u in d["items"] if u["username"] in "'"${!people_0012[*]}"'".split())')" \
        "$wanted 200 [[\"upgrade-ana\", \"Upgrade Ana\", \"upgrade.ana@example.org\", false, false, null], [\"upgrade-bot\", \"Upgrade nightly robot\", \"\", true, false, null], [\"upgrade-jo\", \"Upgrade Jo, old account\", \"upgrade.jo@example.org\", false, true, null], [\"upgrade-jo-2\", \"Upgrade Jo\", \"upgrade.jo@example.org\", false, false, null], [\"upgrade-kim\", \"Upgrade Kim\", \"upgrade.kim@example.org\", false, false, null], [\"upgrade-kim-2\", \"Upgrade Kim, second account\", \"upgrade.kim@example.org\", false, false, null], [\"upgrade-lee\", \"\", \"\", false, false, null], [\"upgrade-max\", \"Upgrade Max\", \"upgrade max@example.org\", false, false, null], $([ -n "$people_pat" ] && echo '["upgrade-pat", "Pat of the upgrade", "Upgrade.Pat@Example.NET", false, false, null], ')[\"upgrade-quinn\", \"\", \"upgrade.quinn@example.org\", false, false, null], [\"upgrade-ren\", \"Upgrade Ren\", \"upgrade.ren@@example.org\", false, false, null], [\"upgrade-sol\", \"\", \"upgrade.sol\", false, false, null]]"
    keep people-0012

    # What is meant to change of them, which the comparisons pass over by name: the
    # rows of users that are given a contact, and those of the accounts of the pass; and
    # by the API the version of each that is given one, and the name and the email that
    # each shows where they are now its contact's, or nothing.
    rows_apart[users]=$accounts
    for name in upgrade-ana upgrade-quinn upgrade-kim upgrade-jo-2 upgrade-max upgrade-ren upgrade-sol ${people_pat:+upgrade-pat}; do
        rows_apart[users]="${rows_apart[users]},${people_0012[$name]}"
        changed="$changed ${people_0012[$name]}.row_version ${people_0012[$name]}.updated_at"
    done
    for entry in upgrade-quinn.display_name upgrade-max.email upgrade-ren.email upgrade-sol.display_name \
        upgrade-sol.email ${people_pat:+upgrade-pat.display_name upgrade-pat.email} upgrade-kim-2.display_name \
        upgrade-kim-2.email upgrade-jo.display_name upgrade-jo.email upgrade-bot.display_name; do
        changed="$changed ${people_0012[${entry%.*}]}.${entry#*.}"
    done
    meant[users]="${meant[users]:-}$changed"
    if [ -n "$people_pat" ]; then
        api GET '/contacts?include_drafts=true&include_archived=true&limit=1000'
    else
        printf '{"items": []}' >"$work/body"
    fi
    keep contacts-0012

    # What the previous release does not know: the contact of a user, which it refuses,
    # and a second number.
    api POST /users '{"username": "upgrade-contacted", "contact_hid": "none"}'
    made="$status $(json '[e["field"] for e in d.get("errors", [])]')"
    api GET "/users/${people_0012[upgrade-ana]}"
    made="$made $(json 'sorted(k for k in ("contact", "contact_hid") if k in d)')"
    if [ -n "$people_pat" ]; then
        api POST /contacts '{"name": "Upgrade Second Number", "phone2": "+1 555 0189"}'
        made="$made $status $(json '[e["field"] for e in d.get("errors", [])]')"
        api GET "/contacts/$people_pat"
        made="$made $(json 'sorted(k for k in ("phone2", "user") if k in d)')"
    fi
    expect "pkg $previous_version knows no contact of a user, and refuses one$([ -n "$people_pat" ] && echo '; and a contact has no second number, which it refuses, and names no user')" \
        "$made" "422 [\"contact_hid\"] []$([ -n "$people_pat" ] && echo ' 422 ["phone2"] []')"

    # An external system of each kind that the previous release can hold, beside those
    # of the inventory: the last made with no kind, which it gives other, and the one
    # of discovery retired. A kind of the site's own is refused, and so is a choice in
    # the list that the migration loads; so a value of the site's own in it, and the
    # default dns under a label of the site's, are written into its database.
    [ -n "$witness_contracts" ] || return 0
    made=""
    wanted=""
    for kind in access_control sdn_controller cloud_service dns discovery other; do systems_0012[$kind]=none; done
    for entry in "access_control:Upgrade Witness Gate" "sdn_controller:Upgrade Witness Fabric" \
        "cloud_service:Upgrade Witness Cloud" "dns:Upgrade Witness Resolver" \
        "discovery:Upgrade Witness Finder" ":Upgrade Witness Other"; do
        kind=${entry%%:*}
        if [ -n "$kind" ]; then
            api POST /external-systems "{\"name\": \"${entry#*:}\", \"kind\": \"$kind\"}"
        else
            api POST /external-systems "{\"name\": \"${entry#*:}\"}"
        fi
        made="$made $status"
        wanted="$wanted 201"
        if [ "$status" = 201 ]; then systems_0012[$(json_field kind)]=$(json_field hid); fi
    done
    api POST "/external-systems/${systems_0012[discovery]}/retire" '{"row_version": 1}'
    made="$made $status"
    for kind in access_control sdn_controller cloud_service dns other; do
        witness_undo+=("external-systems/${systems_0012[$kind]}")
    done
    api POST /external-systems '{"name": "Upgrade Witness Ledger", "kind": "ipam"}'
    made="$made $status $(json '[e["field"] for e in d.get("errors", [])]')"
    api GET '/external-systems?include_drafts=true&include_archived=true&limit=1000'
    expect "pkg $previous_version holds an external system of each of the eight kinds it can hold: of access_control, sdn_controller, cloud_service, dns and discovery beside the monitoring and config_backup of the inventory, one of discovery retired, and one made with no kind, which it gives other; and it refuses a kind of the site's own" \
        "$made $status $(json 'sorted({s["kind"] for s in d["items"]})')" \
        "$wanted 200 422 [\"kind\"] 200 [\"access_control\", \"cloud_service\", \"config_backup\", \"discovery\", \"dns\", \"monitoring\", \"other\", \"sdn_controller\"]"
    api POST /choices '{"list": "system_kind", "value": "ipam", "label": "IP address management"}'
    made="$status $(json '[e["field"] for e in d.get("errors", [])]')"
    expect "pkg $previous_version has no system_kind list, and refuses a choice in it" "$made" '422 ["list"]'
    if system_choice ipam "IP address management" >/dev/null 2>&1 &&
        system_choice dns "Name service" >/dev/null 2>&1; then
        pass "pkg so two choices are written into its database as a site's own: ipam in the system_kind list, and dns, a kind that the migration loads, under a label of the site's"
    else
        fail "pkg so two choices are written into its database as a site's own: ipam in the system_kind list, and dns, a kind that the migration loads, under a label of the site's"
    fi
}

# What the migration made, and what the new version says of what was carried over,
# looked at by itself with the new version serving.
changed_0012() {
    local when=$1 database=/var/lib/hirdir/hirdir.db made wanted
    [ -n "$peopled" ] || return 0

    expect "pkg $when no row refers to a record that is not there: users, made anew twice, refers to contacts, and every table that refers to a user to users" \
        "$(sqlite_text 'PRAGMA foreign_key_check' | wc -l)" 0
    expect "pkg $when the new column of contacts holds nothing: no contact has a second number" \
        "$(sqlite_value "$database" 'SELECT count(*) FROM contacts WHERE phone2 IS NOT NULL')" 0

    # Each user, by the API: the name and the email it shows are its contact's, and
    # the contact is the one that had its email, or a new one, or none.
    api GET '/users?limit=1000'
    cp "$work/body" "$work/people-0012-now.json"
    expect "pkg $when each user that $previous_version held with a display name or an email is a contact: with both, a new contact of that name and email; with an email alone, a new one named with its username; of two with one email, the first by username, and the second none, so it shows no name and no email; of two with another, the one that may sign in, though the other comes first by username and is disabled; with an email that is no address, with a space, with no @ or with a second, a new contact without it; $([ -n "$people_pat" ] && echo 'with the email of the contact from before in another case, that contact, whose name and email it now shows, at the next row_version; ')with neither, none; and the service account none, so it loses its display name" \
        "$status $(people_now mine)" "200 $(people_wanted_0012)"
    expect "pkg $when and so is each account of the pass: one with a display name is a new contact of that name, and the others have none" \
        "$(people_now theirs)" "$(accounts_wanted)"

    # The contacts: those made, each one user's and holding nothing but its name and
    # email; and those from before, of which only the one that a user had the email of
    # is now a user's, and is otherwise as it was, which the comparison has looked at.
    if [ -n "$witness_site" ]; then
        api GET '/contacts?include_drafts=true&include_archived=true&limit=1000'
        expect "pkg $when the contacts that the migration made are the users' that are new, each active, a user's, which the Admin is told is that user, and with no organization, no number and no second number; of the contacts from before only $([ -n "$people_pat" ] && echo 'Upgrade Pat, whose email a user had, is a user'"'"'s, upgrade-pat' || echo 'none is a user'"'"'s')" \
            "$status $(python3 -c '
import json, sys
then = {c["hid"] for c in json.load(open(sys.argv[1], encoding="utf-8"))["items"]}
now = json.load(open(sys.argv[2], encoding="utf-8"))["items"]
made = sorted(([c["name"], c["email"], c["organization"], c["phone"], c["phone2"], c["record_status"], c["is_user"], (c["user"] or {}).get("username")] for c in now if c["hid"] not in then), key=json.dumps)
known = sorted([c["name"], c["is_user"], (c["user"] or {}).get("username")] for c in now if c["hid"] in then and (c["is_user"] or c["user"]))
print(json.dumps([made, known]))' "$work/kept-contacts-0012.json" "$work/body")" \
            "200 $(python3 -c '
import json, sys
users = json.loads(sys.argv[1]) + json.loads(sys.argv[2])
made = sorted(([u[3][0], u[3][1], None, None, None, "active", True, u[0]] for u in users if u[3] and u[3][2] == "new"), key=json.dumps)
known = sorted([u[3][0], True, u[0]] for u in users if u[3] and u[3][2] == "from before")
print(json.dumps([made, known]))' "$(people_wanted_0012)" "$(accounts_wanted)")"

        # The operators: the one whose contact is now a user's is internal, and the one
        # with nobody behind it has no scope.
        api GET '/operators?include_drafts=true&include_archived=true&limit=1000'
        expect "pkg $when the operator behind which the contact from before stands, UW7, is internal, as that contact is a user's, and names the user; the open one, UW8, has no scope; and the record of each shows its contact's email and numbers" \
            "$status $(json 'sorted([o["label"], o["scope"], (o["user"] or {}).get("username"), o["contact"] and [o["contact"]["email"], o["contact"]["phone"], o["contact"]["phone2"]]] for o in d["items"] if o["label"] in ("UW7", "UW8"))')" \
            "200 [[\"UW7\", $([ -n "$people_pat" ] && echo '"internal", "upgrade-pat"' || echo '"external", null'), [\"upgrade.pat@example.net\", \"+1 555 0181\", null]], [\"UW8\", null, null, null]]"
    fi

    # The audit events of the upgrade, by system and nobody, with its request ID: a
    # create for each contact it made, an update of each contact it gave a user, which
    # names the user, and an update of each user that had a display name or an email,
    # which keeps what was dropped and names the contact it was given.
    api GET "/audit-events?request_id=$upgrade_events&limit=1000"
    made="$status $(python3 -c '
import json, sys
events = json.load(open(sys.argv[1], encoding="utf-8"))["items"]
users = {u["hid"]: u for u in json.load(open(sys.argv[2], encoding="utf-8"))["items"]}
names = {u["contact"]["hid"]: u["contact"]["name"] for u in users.values() if u["contact"]}
usernames = {hid: u["username"] for hid, u in users.items()}
def said(e):
    changes = e["changes"] or []
    if e["record_type"] == "user":
        return [e["action"], "user", usernames.get(e["record_hid"]), [[c["field"], c["old"], names.get(c["new"], c["new"])] for c in changes]]
    return [e["action"], e["record_type"], names.get(e["record_hid"]), [[c["field"], c["old"], usernames.get(c["new"], c["new"])] for c in changes]]
print(json.dumps([sorted((said(e) for e in events), key=json.dumps), sorted({json.dumps([e["via"], e["actor_hid"], e["actor_name"]]) for e in events})]))' "$work/body" "$work/people-0012-now.json" 2>&1)"
    expect "pkg $when the audit trail has, by system and nobody, with the request ID $upgrade_events, a create of each contact that the upgrade made, with its name and the email it took; an update of each contact that it gave a user, which names the user; and an update of each user that had a display name or an email, the service account and the second of one email among them, which keeps the display name and the email that were dropped and names the contact it was given" \
        "$made" "200 $(events_wanted_0012)"

    # The kinds of external system: the list is loaded beside what the site had put
    # into it, and every system keeps the kind it had.
    [ -n "$witness_contracts" ] || return 0
    api GET '/choices?list=system_kind'
    made="$status $(json '[[c["value"], c["label"], c["sort"], c["active"]] for c in d]')"
    expect "pkg $when the system_kind list holds the eight kinds that were fixed, in their order and with the labels the page has shown, beside the site's own, ipam, and dns there once, under the label the site gave it" \
        "$made" \
        '200 [["dns", "Name service", 5, true], ["ipam", "IP address management", 5, true], ["monitoring", "Monitoring", 10, true], ["config_backup", "Configuration backup", 20, true], ["access_control", "Access control", 30, true], ["sdn_controller", "SDN controller", 40, true], ["cloud_service", "Cloud service", 50, true], ["discovery", "Discovery", 70, true], ["other", "Other", 80, true]]'
    api GET '/external-systems?include_drafts=true&include_archived=true&limit=1000'
    expect "pkg $when every external system from before has the kind it had, each a value of the list: two of monitoring, one retired, and one of every other kind, discovery's retired" \
        "$status $(json 'sorted([s["kind"], s["record_status"]] for s in d["items"])')" \
        '200 [["access_control", "active"], ["cloud_service", "active"], ["config_backup", "active"], ["discovery", "retired"], ["dns", "active"], ["monitoring", "active"], ["monitoring", "retired"], ["other", "active"], ["sdn_controller", "active"]]'
}

# kind_row VALUE: the HID and the row_version of that value of the system_kind list, as
# after_0012 read the list.
kind_row() {
    python3 -c '
import json, sys
found = [c for c in json.load(open(sys.argv[1], encoding="utf-8")) if c["value"] == sys.argv[2]][0]
print(found["hid"], found["row_version"])' "$work/kinds-0012.json" "$1"
}

# What is new, tried on what was carried over: a contact given to a user from before
# and refused to the service account and to the second user of one email; the fields
# of 0.9.2 refused; a user made with a new contact, by the API and by hirdir admin; a
# number entered once on a contact, shown on the user and on the operator; an operator
# made internal, external and open by the person behind it; which user a contact is,
# told to the Admin alone; a username changed, which keeps the user's session; and the
# list of the kinds of external system edited, a kind of the site's own given to a
# system, a kind that a system holds made inactive and kept, a system with no kind
# refused while other is not offered, and a kind longer than twenty characters. What
# it adds is retired, or given back, so that the rest of this pass starts as it would
# have.
after_0012() {
    local admin=$token made wanted="" entry lee kim_contact session hid row noor fitter
    local system dns other code
    [ -n "$peopled" ] || return 0
    api GET '/users?limit=1000'
    kim_contact=$(json '[u["contact_hid"] for u in d["items"] if u["username"] == "upgrade-kim"][0]')

    # A contact of the new version, with a second number, is refused to the service
    # account from before and given to the user from before that had neither; the
    # contact that the upgrade made for the first of two users of one email is refused
    # to the second.
    api POST /contacts '{"name": "Upgrade Lee", "email": "upgrade.lee@example.org", "phone": "+1 555 0190", "phone2": "+1 555 0191"}'
    made="$status $(json_field phone2)"
    lee=$(json_field hid)
    api GET "/users/${people_0012[upgrade-bot]}"
    api PATCH "/users/${people_0012[upgrade-bot]}" "{\"row_version\": $(json_field row_version), \"contact_hid\": \"$lee\"}"
    made="$made $status $(json '[e["field"] for e in d.get("errors", [])]')"
    api GET "/users/${people_0012[upgrade-kim-2]}"
    api PATCH "/users/${people_0012[upgrade-kim-2]}" "{\"row_version\": $(json_field row_version), \"contact_hid\": \"$kim_contact\"}"
    made="$made $status $(json '[e["field"] for e in d.get("errors", [])]')"
    api GET "/users/${people_0012[upgrade-lee]}"
    api PATCH "/users/${people_0012[upgrade-lee]}" "{\"row_version\": $(json_field row_version), \"contact_hid\": \"$lee\"}"
    made="$made $status $(json '[d["display_name"], d["email"], d["contact"]["phone"], d["contact"]["phone2"]]')"
    api GET "/audit-events?record_hid=${people_0012[upgrade-lee]}&limit=1"
    made="$made $(json '[[e["action"], [c["field"] for c in e["changes"]]] for e in d["items"]]')"
    api GET "/audit-events?record_hid=$lee&limit=1"
    expect "pkg a contact with a second number is refused to the service account from before, the contact that the upgrade made for upgrade-kim to upgrade-kim-2, and the contact is given to upgrade-lee, which had neither a name nor an email, and now shows its name, its email and its two numbers; audited on the user and on the contact" \
        "$made $(json '[[e["action"], [c["field"] for c in e["changes"]]] for e in d["items"]]')" \
        "201 +1 555 0191 422 [\"contact_hid\"] 409 [\"contact_hid\"] 200 [\"Upgrade Lee\", \"upgrade.lee@example.org\", \"+1 555 0190\", \"+1 555 0191\"] [[\"update\", [\"contact_hid\"]]] [[\"update\", [\"user_hid\"]]]"

    # What 0.9.2 took, which a user no longer keeps, is refused; a user is made with a
    # new contact, by the API and by hirdir admin.
    api GET "/users/${people_0012[upgrade-ana]}"
    api PATCH "/users/${people_0012[upgrade-ana]}" "{\"row_version\": $(json_field row_version), \"display_name\": \"Ana of the upgrade\"}"
    made="$status $(json '[e["field"] for e in d.get("errors", [])]')"
    api POST /users '{"username": "upgrade-named", "display_name": "Upgrade Named", "email": "upgrade.named@example.org"}'
    made="$made $status $(json 'sorted(e["field"] for e in d.get("errors", []))')"
    api POST /users '{"username": "upgrade-noor", "contact": {"name": "Upgrade Noor", "email": "upgrade.noor@example.org", "phone": "+1 555 0192", "phone2": "+1 555 0193"}}'
    made="$made $status $(json '[d["user"]["display_name"], d["user"]["email"], d["user"]["contact"]["phone2"]]')"
    noor=$(json 'd["user"]["contact_hid"]')
    inside hirdir admin create-user upgrade-cli --name "Upgrade Cli" --email upgrade.cli@example.org --phone2 "+1 555 0194" >"$work/create-user.log" 2>&1 || true
    made="$made $(grep -c '^access code: ' "$work/create-user.log" || true)"
    code=0
    inside hirdir admin create-user upgrade-unnamed --email upgrade.unnamed@example.org >"$work/create-user.log" 2>&1 || code=$?
    made="$made $code"
    api GET '/contacts?limit=1000'
    expect "pkg PATCH /users refuses a display name, and POST /users a display name and an email, which a user no longer keeps; POST /users makes a user with a new contact, its name, email and two numbers, which the user shows, and so does hirdir admin create-user --name --email --phone2, which refuses an email with no name" \
        "$made $(json 'sorted([c["name"], c["phone2"], (c["user"] or {}).get("username")] for c in d["items"] if c["name"] in ("Upgrade Noor", "Upgrade Cli"))')" \
        '422 ["display_name"] 422 ["display_name", "email"] 201 ["Upgrade Noor", "upgrade.noor@example.org", "+1 555 0193"] 1 2 [["Upgrade Cli", "+1 555 0194", "upgrade-cli"], ["Upgrade Noor", "+1 555 0193", "upgrade-noor"]]'

    # A number entered once, on the contact that the upgrade made for upgrade-kim, shows
    # on the user; and where there are operators, the one with nobody behind it is
    # internal with that contact behind it, showing the number, external with one that
    # is no user's, and open again, with no scope, when that contact is retired.
    api GET "/contacts/$kim_contact"
    api PATCH "/contacts/$kim_contact" "{\"row_version\": $(json_field row_version), \"phone2\": \"+1 555 0195\"}"
    made=$status
    api GET "/users/${people_0012[upgrade-kim]}"
    made="$made $(json '[d["display_name"], d["contact"]["phone2"]]')"
    if [ -n "$witness_site" ]; then
        api POST /contacts '{"name": "Upgrade Outside Fitter", "organization": "Upgrade Fitting Services", "email": "fitter@example.com"}'
        fitter=$(json_field hid)
        api GET '/operators?limit=1000'
        hid=$(json '[o["hid"] for o in d["items"] if o["label"] == "UW8"][0]')
        for entry in "$kim_contact" "$fitter"; do
            api GET "/operators/$hid"
            api PATCH "/operators/$hid" "{\"row_version\": $(json_field row_version), \"contact_hid\": \"$entry\"}"
            made="$made $status $(json '[d["scope"], (d["user"] or {}).get("username"), d["contact"] and d["contact"]["phone2"]]')"
        done
        api GET "/contacts/$fitter"
        api POST "/contacts/$fitter/retire" "{\"row_version\": $(json_field row_version)}"
        made="$made $status"
        api GET "/operators/$hid"
        made="$made $(json '[d["scope"], d["is_open"], d["contact"]["record_status"]]')"
        api PATCH "/operators/$hid" "{\"row_version\": $(json_field row_version), \"contact_hid\": null}"
        made="$made $status $(json '[d["scope"], d["is_open"], d["contact"]]')"
        wanted=' 200 ["internal", "upgrade-kim", "+1 555 0195"] 200 ["external", null, null] 200 [null, true, "retired"] 200 [null, true, null]'
    fi
    expect "pkg a second number entered once on the contact that the upgrade made for upgrade-kim shows on the user$([ -n "$witness_site" ] && echo '; the open operator from before, UW8, given that contact, is internal and names the user and shows the number, given a contact that is no user'"'"'s is external, and with that contact retired is open and has no scope, as with nobody behind it')" \
        "$made" "200 [\"Upgrade Kim\", \"+1 555 0195\"]$wanted"

    # Which user a contact is, the Admin alone is told: a View-only service token reads
    # that a contact is a user's, and that an operator is internal, and not who.
    if [ -n "$witness_site" ] && [ -n "${service_secret:-}" ]; then
        token=$service_secret
        api GET "/contacts/$kim_contact"
        made="$status $(json '[d["is_user"], d["user"]]')"
        api GET '/operators?limit=1000'
        made="$made $status $(json '[[o["scope"], o["user"]] for o in d["items"] if o["label"] == "UW7"]')"
        token=$admin
        api GET "/contacts/$kim_contact"
        made="$made $(json '[d["is_user"], (d["user"] or {}).get("username")]')"
        expect "pkg a View-only service token reads that the contact the upgrade made for upgrade-kim is a user's, and that UW7 is internal, and is not told which user; the Admin is" \
            "$made" '200 [true, null] 200 [["internal", null]] [true, "upgrade-kim"]'
    fi

    # A username changed by an Admin: the session that the user had goes on, under the
    # new name, which the access code signs in with, and the old one no longer.
    sign_in upgrade-ana "$people_code"
    made=$status
    session=$token
    token=$admin
    api GET "/users/${people_0012[upgrade-ana]}"
    api PATCH "/users/${people_0012[upgrade-ana]}" "{\"row_version\": $(json_field row_version), \"username\": \"upgrade-ana-renamed\"}"
    made="$made $status $(json_field username)"
    token=$session
    api GET /auth/me
    made="$made $status $(json_field username)"
    sign_in upgrade-ana-renamed "$people_code"
    made="$made $status"
    sign_in upgrade-ana "$people_code"
    made="$made $status"
    token=$admin
    expect "pkg upgrade-ana, a user from before, signs in; an Admin changes its username, and its session goes on under the new one, with which its access code signs it in, and not under the old" \
        "$made" "200 200 upgrade-ana-renamed 200 upgrade-ana-renamed 200 401"

    # The kinds of external system: a label changed, which the systems that hold the
    # value keep; the site's own value from before given to a system; a value added
    # and removed again; one that a system holds made inactive, which is not removed,
    # is kept by its system through a change and refused to a new one; and while other
    # is not offered, a system with no kind is refused, naming the field.
    [ -n "$witness_contracts" ] || return 0
    api GET '/choices?list=system_kind'
    cp "$work/body" "$work/kinds-0012.json"
    read -r hid row <<<"$(kind_row monitoring)"
    api PATCH "/choices/$hid" "{\"row_version\": $row, \"label\": \"Monitoring and alerting\"}"
    made="$status $(json_field label)"
    api GET '/external-systems?include_archived=true&limit=1000'
    made="$made $(json 'sorted(s["kind"] for s in d["items"] if s["name"] in ("Upgrade Witness Watch", "Upgrade Witness Old Monitor"))')"
    api PATCH "/choices/$hid" "{\"row_version\": $((row + 1)), \"label\": \"Monitoring\"}"
    made="$made $status"
    api POST /external-systems '{"name": "Upgrade Witness Ledger", "kind": "ipam"}'
    made="$made $status $(json_field kind)"
    system=$(json_field hid)
    api POST /choices '{"list": "system_kind", "value": "inventory_sync", "label": "Inventory sync"}'
    made="$made $status"
    api DELETE "/choices/$(json_field hid)"
    made="$made $status"
    expect "pkg an Admin renames a kind, monitoring, and the systems from before that hold it keep it; a system is given ipam, the site's own value from before; and a kind is added to the list and, held by no system, removed again" \
        "$made" '200 Monitoring and alerting ["monitoring", "monitoring"] 200 201 ipam 201 204'

    read -r dns row <<<"$(kind_row dns)"
    api PATCH "/choices/$dns" "{\"row_version\": $row, \"active\": false}"
    made="$status $(json_field active)"
    api DELETE "/choices/$dns"
    made="$made $status"
    hid=${systems_0012[dns]}
    api GET "/external-systems/$hid"
    api PATCH "/external-systems/$hid" "{\"row_version\": $(json_field row_version), \"notes\": \"Its kind is offered no more\"}"
    made="$made $status $(json_field kind)"
    api PATCH "/external-systems/$hid" "{\"row_version\": $(json_field row_version), \"kind\": \"dns\"}"
    made="$made $status $(json_field kind)"
    api POST /external-systems '{"name": "Upgrade Witness Second Resolver", "kind": "dns"}'
    made="$made $status $(json '[e["field"] for e in d.get("errors", [])]')"
    api PATCH "/choices/$dns" "{\"row_version\": $((row + 1)), \"active\": true}"
    made="$made $status"
    expect "pkg dns, which a system from before holds, is made inactive and not removed; that system keeps it through a change of its notes, and when it is given again; a new system is refused it; and it is offered again" \
        "$made" '200 false 409 200 dns 200 dns 422 ["kind"] 200'

    read -r other row <<<"$(kind_row other)"
    api PATCH "/choices/$other" "{\"row_version\": $row, \"active\": false}"
    made=$status
    api POST /external-systems '{"name": "Upgrade Witness Unkinded"}'
    made="$made $status $(json '[e["field"] for e in d.get("errors", [])]')"
    api PATCH "/choices/$other" "{\"row_version\": $((row + 1)), \"active\": true}"
    made="$made $status"
    api POST /external-systems '{"name": "Upgrade Witness Unkinded"}'
    made="$made $status $(json_field kind)"
    hid=$(json_field hid)
    expect "pkg with other made inactive, a system with no kind is refused, naming the field; offered again, such a system is given other" \
        "$made" '200 422 ["kind"] 200 201 other'

    # A kind longer than the twenty characters that a kind had until now, which the
    # migration made room for.
    api POST /choices '{"list": "system_kind", "value": "configuration_management_db", "label": "Configuration management database", "sort": 90}'
    made=$status
    api POST /external-systems '{"name": "Upgrade Witness Records", "kind": "configuration_management_db"}'
    made="$made $status $(json_field kind)"
    entry=$(json_field hid)
    api GET "/external-systems/$entry"
    expect "pkg a kind of 27 characters is added to the list and given to a system, which holds it" \
        "$made $status $(json_field kind)" '201 201 configuration_management_db 200 configuration_management_db'
    made=""
    for entry in "$system" "$hid" "$entry"; do
        api GET "/external-systems/$entry"
        api POST "/external-systems/$entry/retire" "{\"row_version\": $(json_field row_version)}"
        made="$made$status "
    done
    api GET '/choices?list=system_kind'
    expect "pkg the three systems made here are retired, and the list offers what it did after the upgrade, under the same labels, and the kind that one of them holds" \
        "$made$status $(json '[[c["value"], c["label"], c["active"]] for c in d]')" \
        '200 200 200 200 [["dns", "Name service", true], ["ipam", "IP address management", true], ["monitoring", "Monitoring", true], ["config_backup", "Configuration backup", true], ["access_control", "Access control", true], ["sdn_controller", "SDN controller", true], ["cloud_service", "Cloud service", true], ["discovery", "Discovery", true], ["other", "Other", true], ["configuration_management_db", "Configuration management database", true]]'
}
