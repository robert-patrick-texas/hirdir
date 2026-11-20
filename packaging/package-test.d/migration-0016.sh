# shellcheck shell=bash
# shellcheck disable=SC2034,SC2154  # Read by packaging/package-test.sh, whose names these are.
#
# Migration 0016, which came with hirdir 0.9.13: the notes of a user (P-281).
#
# packaging/package-test.sh reads this file when the upgrade it tests runs the
# migration, and calls the three functions below: see "what one upgrade alone has"
# there. The previous release is then at revision 0015 or before: a user has no notes,
# and its API knows none, nor the groups and the operator that 0.9.13 takes with a new
# user, nor the operators that a user answers, nor GET /colours.
#
# The migration adds one column to users, notes, as the table stands, blank for every
# user. It changes no row, creates no table and writes no audit event, so the pass whose
# migration fails puts the trigger on alembic_version in its way, and the column has to
# be undone with the rest. What else 0.9.13 says of a user is worked out when it is read:
# the operators its contact stands behind, and the gaps of the list. So each user from
# before is as it was, with its notes blank, signs in as it did, and answers the
# operators that its contact stood behind before the upgrade. Going back is by the
# backup the upgrade took, which has no such column. docs/install.md says all of it
# under "From 0.9.12 to 0.9.13", and what is said there is what is looked for here.
writes_no_event=yes
# The table of the accounts, which is no part of the inventory, is kept and compared as
# the inventory's tables are: every row holds what it held, and the column is after the
# others. A file of an earlier migration may have named it already.
case " $more_tables " in
    *" users "*) ;;
    *) more_tables="${more_tables:+$more_tables }users" ;;
esac
also new_columns users 'notes TEXT NULL -'

# Set by before_0016 where the previous release makes a person of a user its contact.
noted_0016=""
# The users that before_0016 makes, each by what it is: person, a person whose contact
# stands behind an operator; nobody, a person with no contact; robot, a service account
# with a token; off, a disabled person; and grouped, a person in two groups, who holds
# Inventory by one of them. Their usernames are upgrade-16- and that word. The HID of
# each, the access code of each that has one, and the secret of the robot's token.
kinds_0016="grouped nobody off person robot"
declare -gA users_0016=() codes_0016=()
secret_0016=""
# The contact of the person, and the operator behind which it stands, UN16.
person_0016=""
operator_0016=""

# signed_0016 KIND: sign in as the user of that kind that before_0016 made, with its
# access code, through the API of whichever version serves. $status is the answer's,
# and $token is the session where it is 200, and as it was otherwise.
signed_0016() {
    local body
    body=$(python3 -c 'import json, sys; print(json.dumps({"username": sys.argv[1], "access_code": sys.argv[2]}))' \
        "upgrade-16-$1" "${codes_0016[$1]:-none}")
    api POST /auth/sign-in "$body"
    if [ "$status" = 200 ]; then token=$(json_field token); fi
}

# mine_0016: the users that before_0016 made, of the last response, GET /users, each as
# the API gives it, by username.
mine_0016() {
    python3 -c '
import json, sys

users = json.load(open(sys.argv[1], encoding="utf-8"))["items"]
print(json.dumps([u for u in users if u["username"].startswith("upgrade-16-")]))' "$work/body"
}

# What the migration could harm, made with the previous release: users of each kind, a
# person of them behind an operator, and two groups, one of which grants a role. Each
# signs in before the upgrade, so that the rows kept are those it is to sign in to after
# it. A release before 0.9.3 knows no contact of a user: migration-0012.sh then looks at
# the users, and this file at none.
before_0016() {
    local admin=$token made="" wanted="" body kind day night
    previous_at 0012 || return 0
    noted_0016=yes

    # The accounts of the pass, made before this file made any. Their rows are let be by
    # the comparison of the rows of users, as an account of the pass may sign in again
    # before it: the API looks at each, and the users of this file are compared there.
    api GET '/users?limit=1000'
    rows_apart[users]="${rows_apart[users]:+${rows_apart[users]},}$(json '",".join(u["hid"] for u in d["items"])')"

    # Two groups, the second of which grants Inventory.
    api POST /user-groups '{"name": "Upgrade Day Desk", "description": "Made before the upgrade to 0.9.13"}'
    made="$made $status"
    day=$(json_field hid)
    api POST /user-groups '{"name": "Upgrade Night Shift", "description": "Holds Inventory, made before the upgrade to 0.9.13"}'
    made="$made $status"
    night=$(json_field hid)
    api POST /role-grants "{\"role\": \"inventory\", \"group_hid\": \"$night\"}"
    made="$made $status"
    wanted="$wanted 201 201 201"
    groups_made=$((groups_made + 2))
    grants_made=$((grants_made + 1))

    # A user of each kind.
    for kind in $kinds_0016; do
        case $kind in
            person) body='{"username": "upgrade-16-person", "contact": {"name": "Example Person", "email": "example.person@example.net", "phone": "+1 555 0161"}}' ;;
            nobody) body='{"username": "upgrade-16-nobody"}' ;;
            robot) body='{"username": "upgrade-16-robot", "is_service_account": true, "role": "viewer"}' ;;
            off) body='{"username": "upgrade-16-off", "contact": {"name": "Example Former Person"}}' ;;
            grouped) body='{"username": "upgrade-16-grouped", "contact": {"name": "Example Grouped Person", "email": "example.grouped@example.net"}}' ;;
        esac
        api POST /users "$body"
        made="$made $status"
        wanted="$wanted 201"
        users_0016[$kind]=$(json 'd["user"]["hid"]')
        codes_0016[$kind]=$(json 'd["access_code"] or ""')
        if [ "$status" = 201 ]; then users_made=$((users_made + 1)); fi
    done
    # The service account was given its role as it was made: a grant of its own.
    grants_made=$((grants_made + 1))
    api POST "/users/${users_0016[robot]}/service-tokens" '{"name": "upgrade 0016 reader"}'
    made="$made $status"
    secret_0016=$(json_field secret)
    api PATCH "/users/${users_0016[off]}" '{"row_version": 1, "disabled": true}'
    made="$made $status"
    api PUT "/user-groups/$day/members/${users_0016[grouped]}"
    made="$made $status"
    api PUT "/user-groups/$night/members/${users_0016[grouped]}"
    made="$made $status"
    wanted="$wanted 201 200 204 204"

    # The person stands behind an operator, of a colour that is none of those that
    # 0.9.13 offers, which is as good as one that is. It is retired again with what came
    # after the groups.
    api GET "/users/${users_0016[person]}"
    person_0016=$(json_field contact_hid)
    api POST /operators "{\"label\": \"UN16\", \"description\": \"Made before the upgrade to 0.9.13\", \"colour\": \"#2e7d32\", \"contact_hid\": \"$person_0016\"}"
    made="$made $status $(json '[d["scope"], (d["user"] or {}).get("username")]')"
    wanted="$wanted 201 [\"internal\", \"upgrade-16-person\"]"
    operator_0016=$(json_field hid)
    witness_undo+=("operators/$operator_0016")

    # Each signs in with its access code but the disabled one, and the token answers.
    for kind in person nobody off grouped; do
        token=$admin
        signed_0016 "$kind"
        made="$made $status"
    done
    api GET /auth/me
    made="$made $status $(json '[d["role"], sorted(g["name"] for g in d["groups"])]')"
    token=$secret_0016
    api GET /auth/me
    made="$made $status $(json '[d["username"], d["role"]]')"
    token=$admin
    wanted="$wanted 200 200 401 200 200 [\"inventory\", [\"Upgrade Day Desk\", \"Upgrade Night Shift\"]] 200 [\"upgrade-16-robot\", \"viewer\"]"
    api GET '/users?limit=1000'
    expect "pkg $previous_version holds users of each kind that migration 0016 gives a column: a person whose contact stands behind an operator, UN16; a person with no contact; a service account with a token; a disabled person; and a person in two groups, who holds Inventory by one of them. Each signs in with its access code, and the disabled one does not; the token authenticates as its service account" \
        "$made $status $(json '[[u["username"], u["is_service_account"], u["disabled"], u["role"], bool(u["contact"])] for u in d["items"] if u["username"].startswith("upgrade-16-")]')" \
        "$wanted 200 [[\"upgrade-16-grouped\", false, false, \"inventory\", true], [\"upgrade-16-nobody\", false, false, null, false], [\"upgrade-16-off\", false, true, null, true], [\"upgrade-16-person\", false, false, null, true], [\"upgrade-16-robot\", true, false, \"viewer\", false]]"
    mine_0016 >"$work/kept-people-0016.json"

    # What the previous release does not know.
    api POST /users '{"username": "upgrade-16-noted", "notes": "Asked for before the upgrade", "group_hids": [], "operator": {}}'
    made="$status $(json 'sorted(e["field"] for e in d.get("errors", []))')"
    api GET "/users/${users_0016[person]}"
    made="$made $(json 'sorted(k for k in ("notes", "operators") if k in d)')"
    api GET "/contacts/$person_0016"
    made="$made $(json 'sorted(k for k in ("is_operator", "operators") if k in d)')"
    api GET /colours
    made="$made $status"
    expect "pkg $previous_version knows no notes of a user: it refuses notes, groups and an operator on a new user; a user answers neither notes nor operators, and a contact not whether it stands behind one; and there is no GET /colours" \
        "$made" "422 [\"group_hids\", \"notes\", \"operator\"] [] [] 404"
}

# What the migration made, and what the new version says of the users from before,
# looked at by themselves with the new version serving. It changes nothing.
changed_0016() {
    local when=$1 backup got gap
    [ -n "$noted_0016" ] || return 0

    # The backup that the upgrade took is the way back.
    backup=$(sed -n 's/^hirdir: the database as it was before this upgrade is kept at //p' "$work/apt.log")
    expect "pkg $when the backup that the upgrade took holds every user, in a table with no column notes, so going back to $previous_version is by that backup (${backup:-no backup})" \
        "$(sqlite_value "${backup:-/nonexistent}" "SELECT count(*) FROM pragma_table_info('users') WHERE name = 'notes'") $(sqlite_value "${backup:-/nonexistent}" 'SELECT count(*) FROM users')" \
        "0 $(sqlite_value /var/lib/hirdir/hirdir.db 'SELECT count(*) FROM users')"
    expect "pkg $when the new column holds nothing: no user has notes" \
        "$(sqlite_value /var/lib/hirdir/hirdir.db 'SELECT count(*) FROM users WHERE notes IS NOT NULL')" 0

    # Each user from before, by the API: every field it had, as it was, and beside them
    # its notes, blank, and the operators its contact stands behind.
    api GET '/users?limit=1000'
    expect "pkg $when each of the five users made with $previous_version is as it was, field for field, its contact, its role and its groups among them" \
        "$status $(unchanged people-0016 'fields more')" "200 same"
    expect "pkg $when every user answers notes, and none has any; and each of the five answers the operators that its contact stands behind, the person UN16 with its colour, which is none of the grid, and the others none" \
        "$(json 'sorted({str(u.get("notes", "no notes")) for u in d["items"]})') $(json '[[u["username"], [[o["label"], o["colour"], o["record_status"]] for o in u.get("operators", ["none"])]] for u in d["items"] if u["username"].startswith("upgrade-16-")]')" \
        '["None"] [["upgrade-16-grouped", []], ["upgrade-16-nobody", []], ["upgrade-16-off", []], ["upgrade-16-person", [["UN16", "#2e7d32", "active"]]], ["upgrade-16-robot", []]]'

    # The gaps of the list, among the users from before.
    got=""
    for gap in contact=none contact=some operator=none operator=some; do
        api GET "/users?$gap&limit=1000"
        got="$got $status $(json '[u["username"][len("upgrade-16-"):] for u in d["items"] if u["username"].startswith("upgrade-16-")]')"
    done
    api GET "/contacts/$person_0016"
    got="$got $status $(json '[d["is_user"], d["is_operator"], [o["label"] for o in d["operators"]]]')"
    expect "pkg $when the gaps are found among the users from before: with no contact, the person made with none; with one, the other three persons; behind no operator, all of them but the one behind UN16, the disabled one among them; behind one, that one; and the service account in none of them. The contact of that person says it is a user and stands behind UN16" \
        "$got" ' 200 ["nobody"] 200 ["grouped", "off", "person"] 200 ["grouped", "nobody", "off"] 200 ["person"] 200 [true, true, ["UN16"]]'
}

# What is new, tried on what was carried over: each user from before signs in again and
# its token still works; an Admin gives each notes, which it answers and the audit trail
# holds; and the users as a file, for an Admin, say of each what it is, with no access
# code and no token in it. The notes are left: they are what a site would have.
after_0016() {
    local admin=$token made="" wanted="" kind text grouped secret found=0 looked=0
    [ -n "$noted_0016" ] || return 0

    for kind in person nobody off grouped; do
        token=$admin
        signed_0016 "$kind"
        made="$made $status"
    done
    api GET /auth/me
    made="$made $status $(json '[d["username"], d["role"], sorted(g["name"] for g in d["groups"])]')"
    grouped=$token
    token=$secret_0016
    api GET /auth/me
    made="$made $status $(json '[d["username"], d["role"]]')"
    token=$admin
    expect "pkg each user from before signs in with the access code it had with $previous_version, and the disabled one is still refused; the one in two groups still holds Inventory by one of them; and the token of the service account still authenticates as it" \
        "$made" ' 200 200 401 200 200 ["upgrade-16-grouped", "inventory", ["Upgrade Day Desk", "Upgrade Night Shift"]] 200 ["upgrade-16-robot", "viewer"]'

    # Notes, given by an Admin to each, the service account and the disabled one among
    # them.
    made=""
    for kind in $kinds_0016; do
        text="Kept since $previous_version: upgrade-16-$kind, noted after the upgrade"
        api GET "/users/${users_0016[$kind]}"
        api PATCH "/users/${users_0016[$kind]}" "{\"row_version\": $(json_field row_version), \"notes\": \"$text\"}"
        made="$made $status"
        api GET "/users/${users_0016[$kind]}"
        made="$made $(json_field notes)"
        api GET "/audit-events?record_hid=${users_0016[$kind]}&limit=1"
        made="$made $(json '[[e["action"], [[c["field"], c["old"], c["new"]] for c in e["changes"]]] for e in d["items"]]')"
        wanted="$wanted 200 $text [[\"update\", [[\"notes\", null, \"$text\"]]]]"
    done
    expect "pkg an Admin gives each user from before notes, the service account and the disabled one among them: each answers them, and each change is audited as any change of a user is, from none to the text" \
        "$made" "$wanted"

    # The users as a file, for an Admin.
    authorized POST "$prefix/api/v1/users/export"
    cp "$work/body" "$work/users-0016.csv"
    expect "pkg POST $prefix/api/v1/users/export gives an Admin a row to each user from before: its person, the role in force, which the one in two groups holds by one of them, its groups, the operator its contact stands behind, its kind, its state, whether it has signed in, and its notes; a number that a spreadsheet would take for a formula is guarded" \
        "$status $(table '[[r["username"], r["name"], r["email"], r["phone"], r["role"], r["groups"], r["operators"], r["kind"], r["state"], bool(r["last_sign_in_at"]), r["notes"]] for r in rows if r["username"].startswith("upgrade-16-")]')" \
        "200 $(python3 -c '
import json, sys

noted = lambda kind: f"Kept since {sys.argv[1]}: upgrade-16-{kind}, noted after the upgrade"
print(json.dumps([
    ["upgrade-16-grouped", "Example Grouped Person", "example.grouped@example.net", "", "inventory", "Upgrade Day Desk;Upgrade Night Shift", "", "person", "enabled", True, noted("grouped")],
    ["upgrade-16-nobody", "", "", "", "", "", "", "person", "enabled", True, noted("nobody")],
    ["upgrade-16-off", "Example Former Person", "", "", "", "", "", "person", "disabled", False, noted("off")],
    ["upgrade-16-person", "Example Person", "example.person@example.net", "'"'"'+1 555 0161", "", "", "UN16", "person", "enabled", True, noted("person")],
    ["upgrade-16-robot", "", "", "", "viewer", "", "", "service", "enabled", False, noted("robot")],
]))' "$previous_version")"
    for secret in "${codes_0016[@]}" "$secret_0016" $(sqlite_text "SELECT access_code_hash FROM users WHERE username LIKE 'upgrade-16-%' AND access_code_hash IS NOT NULL UNION ALL SELECT token_hash FROM service_tokens WHERE user_hid = '${users_0016[robot]}'"); do
        [ -n "$secret" ] || continue
        looked=$((looked + 1))
        if grep -qF -- "$secret" "$work/users-0016.csv"; then found=$((found + 1)); fi
    done
    expect "pkg and it holds none of their access codes, nor the token of the service account, nor what the database keeps of either: the four codes, the token and the five hashes, $looked looked for" \
        "$found $looked" "0 10"
    token=$grouped
    authorized POST "$prefix/api/v1/users/export"
    made=$status
    token=$secret_0016
    authorized POST "$prefix/api/v1/users/export"
    made="$made $status"
    token=$admin
    expect "pkg and the file is refused to the user from before who holds Inventory by its group, and to the View-only token from before" \
        "$made" "403 403"
}
