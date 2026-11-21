# shellcheck shell=bash
# shellcheck disable=SC2034,SC2154  # Read by packaging/package-test.sh, whose names these are.
#
# Migration 0017, which came with hirdir 0.9.14: the record status of a user (P-292,
# P-296).
#
# packaging/package-test.sh reads this file when the upgrade it tests runs the
# migration, and calls the three functions below: see "what one upgrade alone has"
# there. The previous release is then at revision 0016 or before: a user is enabled or
# disabled and nothing else, and its API knows no record status of a user, no route that
# retires one or brings one back, none that says what is linked to a record, and none of
# a person's own under /auth/me. It takes an access code of any length that is typed.
#
# The migration adds one column to users, record_status, as the table stands, active
# for every user. It changes no row, creates no table and writes no audit event, so the
# pass whose migration fails puts the trigger on alembic_version in its way, and the
# column has to be undone with the rest. Nothing is worked out of what is held: a user
# that is disabled stays disabled and is not retired, and neither is one whose contact
# is retired. So each user from before is as it was and active, and signs in, or is
# refused, as it did, with the access code it had, also one that was typed shorter than
# 0.9.14 lets a code be typed: a code that is held is not looked at (P-295). Going back
# is by the backup the upgrade took, which has no such column. docs/install.md says all
# of it under "From 0.9.13 to 0.9.14", and what is said there is what is looked for here.
writes_no_event=yes
# The table of the accounts, which is no part of the inventory, is kept and compared as
# the inventory's tables are: every row holds what it held, and the column is after the
# others. A file of an earlier migration may have named it already.
case " $more_tables " in
    *" users "*) ;;
    *) more_tables="${more_tables:+$more_tables }users" ;;
esac
also new_columns users 'record_status VARCHAR(10) NOT NULL -'

# Set by before_0017 where the previous release makes a person of a user its contact.
noted_0017=""
# The users that before_0017 makes, each by what it is: grouped, a person in two groups
# who holds Inventory by a grant of its own; person, a person whose contact stands
# behind two operators, UP17 and UQ17, and who holds View-only; off, a disabled person;
# robot, a service account with a token; left, a person whose contact is retired; and
# short and cli, two with no contact whose access codes were typed, of 5 characters to
# the API and of 6 to hirdir admin, the second an Admin, as the first Admin of an
# install is made. Their usernames are upgrade-17- and that word. The HID of each, the
# access code of each that has one, and the secret of the robot's token.
kinds_0017="cli grouped left off person robot short"
declare -gA users_0017=() codes_0017=()
secret_0017=""
# The two codes that are typed. They are typed to the previous release alone, which
# takes them: from 0.9.14 a typed code has at least 12 characters.
typed_0017=sh-17
typed_cli_0017=cli-17
# The contact of the person, the two operators behind which it stands, and the contact
# that is retired, which the user left is.
person_0017=""
operators_0017=()
left_0017=""
# Which of these users each gap of the list of users holds, as the previous release
# says it, where it knows the gaps: from 0.9.13.
gaps_0017=""

# signed_0017 KIND: sign in as the user of that kind that before_0017 made, with its
# access code, through the API of whichever version serves. $status is the answer's,
# and $token is the session where it is 200, and as it was otherwise.
signed_0017() {
    local body
    body=$(python3 -c 'import json, sys; print(json.dumps({"username": sys.argv[1], "access_code": sys.argv[2]}))' \
        "upgrade-17-$1" "${codes_0017[$1]:-none}")
    api POST /auth/sign-in "$body"
    if [ "$status" = 200 ]; then token=$(json_field token); fi
}

# mine_0017: the users that before_0017 made, of the last response, GET /users, each as
# the API gives it, by username.
mine_0017() {
    python3 -c '
import json, sys

users = json.load(open(sys.argv[1], encoding="utf-8"))["items"]
print(json.dumps([u for u in users if u["username"].startswith("upgrade-17-")]))' "$work/body"
}

# said_0017: what the last response, GET /users, says of each of those users that the
# migration could have taken for something else: whether it is disabled, the role in
# force, its groups, the state of its contact, and the operators its contact stands
# behind. The new version serves when this is asked.
said_0017() {
    json '[[u["username"][len("upgrade-17-"):], u["disabled"], u["role"], sorted(g["name"] for g in u["groups"]), (u["contact"] or {}).get("record_status"), [o["label"] for o in u["operators"]]] for u in d["items"] if u["username"].startswith("upgrade-17-")]'
}

# gaps_now_0017: which of those users each gap of the list of users holds.
gaps_now_0017() {
    local gap got=""
    for gap in contact=none contact=some operator=none operator=some; do
        api GET "/users?$gap&limit=1000"
        got="$got $status $(json '[u["username"][len("upgrade-17-"):] for u in d["items"] if u["username"].startswith("upgrade-17-")]')"
    done
    printf '%s' "$got"
}

# What the migration could harm, made with the previous release: users of each kind,
# two groups, a grant of a role to a user itself, a person behind two operators, and a
# person whose contact is retired. Each signs in before the upgrade, so that the rows
# kept are those it is to sign in to after it. A release before 0.9.3 knows no contact
# of a user: migration-0012.sh then looks at the users, and this file at none.
before_0017() {
    local admin=$token mine="" made="" wanted="" body kind desk crew label colour
    previous_at 0012 || return 0
    noted_0017=yes

    # The accounts of the pass, made before this file made any. Their rows are let be by
    # the comparison of the rows of users, as an account of the pass may sign in again
    # before it: the API looks at each, and the users of this file are compared there.
    # The users that the file of another migration of the pair made are that file's.
    api GET '/users?limit=1000'
    rows_apart[users]="${rows_apart[users]:+${rows_apart[users]},}$(json '",".join(u["hid"] for u in d["items"] if not __import__("re").match(r"upgrade-\d+-", u["username"]))')"

    # Two groups, neither of which grants a role.
    api POST /user-groups '{"name": "Upgrade Records Desk", "description": "Made before the upgrade to 0.9.14"}'
    made="$made $status"
    desk=$(json_field hid)
    api POST /user-groups '{"name": "Upgrade Field Crew", "description": "Made before the upgrade to 0.9.14"}'
    made="$made $status"
    crew=$(json_field hid)
    wanted="$wanted 201 201"
    groups_made=$((groups_made + 2))

    # A user of each kind that the API makes. The role of each that has one is granted
    # to the user itself as it is made.
    for kind in grouped left off person robot short; do
        case $kind in
            grouped) body='{"username": "upgrade-17-grouped", "contact": {"name": "Example Grouped Engineer", "email": "grouped.engineer@example.net"}, "role": "inventory"}' ;;
            left) body='{"username": "upgrade-17-left", "contact": {"name": "Example Departed Person", "email": "departed.person@example.net"}}' ;;
            off) body='{"username": "upgrade-17-off", "contact": {"name": "Example Paused Person"}}' ;;
            person) body='{"username": "upgrade-17-person", "contact": {"name": "Example Label Person", "email": "label.person@example.net", "organization": "Example Operations", "phone": "+1 555 0171", "phone2": "+1 555 0172"}, "role": "viewer"}' ;;
            robot) body='{"username": "upgrade-17-robot", "is_service_account": true, "role": "viewer"}' ;;
            short) body="{\"username\": \"upgrade-17-short\", \"access_code\": \"$typed_0017\"}" ;;
        esac
        api POST /users "$body"
        made="$made $status"
        wanted="$wanted 201"
        users_0017[$kind]=$(json 'd["user"]["hid"]')
        codes_0017[$kind]=$(json 'd["access_code"] or ""')
        if [ "$status" = 201 ]; then users_made=$((users_made + 1)); fi
    done
    codes_0017[short]=$typed_0017
    grants_made=$((grants_made + 3))
    # And an Admin that hirdir admin makes, on the host, with a code that is typed
    # there, as the first Admin of an install may have been made.
    inside hirdir admin create-user upgrade-17-cli --role admin --access-code "$typed_cli_0017" >"$work/create-user.log" 2>&1 || true
    made="$made $(grep -c '^created upgrade-17-cli with the admin role$' "$work/create-user.log" || true) $(grep -c '^access code: ' "$work/create-user.log" || true)"
    wanted="$wanted 1 0"
    codes_0017[cli]=$typed_cli_0017
    api GET '/users?limit=1000'
    users_0017[cli]=$(json '"".join(u["hid"] for u in d["items"] if u["username"] == "upgrade-17-cli")')
    if [ -n "${users_0017[cli]}" ]; then
        users_made=$((users_made + 1))
        grants_made=$((grants_made + 1))
    fi

    api POST "/users/${users_0017[robot]}/service-tokens" '{"name": "upgrade 0017 reader"}'
    made="$made $status"
    secret_0017=$(json_field secret)
    api PATCH "/users/${users_0017[off]}" '{"row_version": 1, "disabled": true}'
    made="$made $status"
    api PUT "/user-groups/$desk/members/${users_0017[grouped]}"
    made="$made $status"
    api PUT "/user-groups/$crew/members/${users_0017[grouped]}"
    made="$made $status"
    wanted="$wanted 201 200 204 204"

    # The person stands behind two operators. They are retired again with what came
    # after the groups.
    api GET "/users/${users_0017[person]}"
    person_0017=$(json_field contact_hid)
    for label in UP17 UQ17; do
        colour='#2e7d32'
        if [ "$label" = UQ17 ]; then colour='#6a1b9a'; fi
        api POST /operators "{\"label\": \"$label\", \"description\": \"Made before the upgrade to 0.9.14\", \"colour\": \"$colour\", \"contact_hid\": \"$person_0017\"}"
        made="$made $status"
        wanted="$wanted 201"
        operators_0017+=("$(json_field hid)")
        witness_undo+=("operators/$(json_field hid)")
    done

    # The contact of the user left is retired, and the user stays as it is.
    api GET "/users/${users_0017[left]}"
    left_0017=$(json_field contact_hid)
    api GET "/contacts/$left_0017"
    api POST "/contacts/$left_0017/retire" "{\"row_version\": $(json_field row_version)}"
    made="$made $status $(json_field record_status)"
    wanted="$wanted 200 retired"

    # Each signs in with its access code but the disabled one, the two whose codes were
    # typed among them, and the token answers.
    for kind in cli left off short person grouped; do
        token=$admin
        signed_0017 "$kind"
        made="$made $status"
        if [ "$kind" = person ]; then mine=$token; fi
    done
    api GET /auth/me
    made="$made $status $(json '[d["role"], sorted(g["name"] for g in d["groups"])]')"
    token=$secret_0017
    api GET /auth/me
    made="$made $status $(json '[d["username"], d["role"]]')"
    token=$admin
    wanted="$wanted 200 200 401 200 200 200 200 [\"inventory\", [\"Upgrade Field Crew\", \"Upgrade Records Desk\"]] 200 [\"upgrade-17-robot\", \"viewer\"]"
    api GET /role-grants
    made="$made $(json '[g["role"] for g in d if g["user_hid"] == "'"${users_0017[grouped]}"'"]')"
    wanted="$wanted [\"inventory\"]"
    api GET '/users?limit=1000'
    expect "pkg $previous_version holds users of each kind that migration 0017 gives a record status: a person in two groups who holds Inventory by a grant of its own; a person whose contact stands behind two operators, UP17 and UQ17; a disabled person; a service account with a token; a person whose contact is retired; and two with no contact whose access codes were typed, of ${#typed_0017} characters to the API and of ${#typed_cli_0017} to hirdir admin, the second an Admin. Each signs in with its access code, and the disabled one does not; the token authenticates as its service account" \
        "$made $status $(json '[[u["username"], u["is_service_account"], u["disabled"], u["role"], (u["contact"] or {}).get("record_status")] for u in d["items"] if u["username"].startswith("upgrade-17-")]')" \
        "$wanted 200 [[\"upgrade-17-cli\", false, false, \"admin\", null], [\"upgrade-17-grouped\", false, false, \"inventory\", \"active\"], [\"upgrade-17-left\", false, false, null, \"retired\"], [\"upgrade-17-off\", false, true, null, \"active\"], [\"upgrade-17-person\", false, false, \"viewer\", \"active\"], [\"upgrade-17-robot\", true, false, \"viewer\", null], [\"upgrade-17-short\", false, false, null, null]]"
    mine_0017 >"$work/kept-people-0017.json"
    if previous_at 0016; then gaps_0017=$(gaps_now_0017); fi

    # What the previous release does not know. The person asks for what is its own with
    # the session it has.
    api GET "/users/${users_0017[person]}"
    made="$(json 'sorted(k for k in ("record_status",) if k in d)')"
    api POST "/users/${users_0017[person]}/retire" '{"row_version": 1}'
    made="$made $status"
    api POST "/users/${users_0017[person]}/bring-back" '{"row_version": 1}'
    made="$made $status"
    for kind in "users/${users_0017[person]}" "contacts/$person_0017" "operators/${operators_0017[0]}"; do
        api GET "/$kind/linked"
        made="$made $status"
    done
    token=$mine
    api GET /auth/me
    made="$made $status $(json '[sorted(k for k in ("organization", "row_version") if k in d["contact"]), sorted(k for k in ("row_version",) if k in d["operators"][0])]')"
    api PATCH /auth/me/contact '{"row_version": 1, "phone": "+1 555 0173"}'
    made="$made $status"
    api PATCH "/auth/me/operators/${operators_0017[0]}" '{"row_version": 1, "colour": "#1f6feb"}'
    made="$made $status"
    api POST /auth/me/access-code "{\"current_access_code\": \"${codes_0017[person]}\", \"access_code\": \"never-set-by-upgrade-17\"}"
    made="$made $status"
    token=$admin
    api GET '/users?limit=1000'
    expect "pkg $previous_version knows no record status of a user: a user answers none; there is no route that retires a user or brings one back, none that says what is linked to a user, a contact or an operator, and none of a person's own under /auth/me, which says of the contact a person is and of its operators no row_version to change them at; and what was asked changed nothing of the seven users" \
        "$made $status $(unchanged people-0017 more)" \
        '[] 405 405 404 404 404 200 [[], []] 405 405 405 200 same'
}

# What the migration made, and what the new version says of the users from before,
# looked at by themselves with the new version serving. It changes nothing.
changed_0017() {
    local when=$1 backup
    [ -n "$noted_0017" ] || return 0

    # The backup that the upgrade took is the way back.
    backup=$(sed -n 's/^hirdir: the database as it was before this upgrade is kept at //p' "$work/apt.log")
    expect "pkg $when the backup that the upgrade took holds every user, in a table with no column record_status, so going back to $previous_version is by that backup (${backup:-no backup})" \
        "$(sqlite_value "${backup:-/nonexistent}" "SELECT count(*) FROM pragma_table_info('users') WHERE name = 'record_status'") $(sqlite_value "${backup:-/nonexistent}" 'SELECT count(*) FROM users')" \
        "0 $(sqlite_value /var/lib/hirdir/hirdir.db 'SELECT count(*) FROM users')"
    expect "pkg $when the new column holds active for every user, the disabled one and the one whose contact is retired among them, and a row that is written without it is active" \
        "$(sqlite_text 'SELECT record_status, count(*) FROM users GROUP BY record_status') $(sqlite_text "SELECT u.username, u.record_status FROM users u WHERE u.username IN ('upgrade-17-off', 'upgrade-17-left') ORDER BY u.username" | xargs) $(sqlite_value /var/lib/hirdir/hirdir.db "SELECT dflt_value FROM pragma_table_info('users') WHERE name = 'record_status'")" \
        "active $(sqlite_value /var/lib/hirdir/hirdir.db 'SELECT count(*) FROM users') upgrade-17-left active upgrade-17-off active 'active'"

    # Each user from before, by the API: every field it had, as it was.
    api GET '/users?limit=1000'
    expect "pkg $when each of the seven users made with $previous_version is as it was, field for field, its contact, its role, its groups and its row_version among them" \
        "$status $(unchanged people-0017 'fields more')" "200 same"
    expect "pkg $when none of them was taken for something else: the disabled one is disabled and the others are not; the one in two groups is in both and holds Inventory; the person holds View-only and its contact stands behind UP17 and UQ17; and the contact of the one who left is retired, while its user is as it was" \
        "$(said_0017)" \
        '[["cli", false, "admin", [], null, []], ["grouped", false, "inventory", ["Upgrade Field Crew", "Upgrade Records Desk"], "active", []], ["left", false, null, [], "retired", []], ["off", true, null, [], "active", []], ["person", false, "viewer", [], "active", ["UP17", "UQ17"]], ["robot", false, "viewer", [], null, []], ["short", false, null, [], null, []]]'
    if [ -n "$gaps_0017" ]; then
        expect "pkg $when each gap of the list of users holds those of them that it held with $previous_version: none is retired, so none is left out of a gap" \
            "$(gaps_now_0017)" "$gaps_0017"
    fi
}

# What is asked of what was carried over: each user from before signs in again, or is
# refused, as it did, the two with a typed code that is short among them; the token
# still works; and each still holds what it held.
after_0017() {
    local admin=$token made="" kind
    [ -n "$noted_0017" ] || return 0

    for kind in cli left off short person grouped; do
        token=$admin
        signed_0017 "$kind"
        made="$made $status"
        if [ "$kind" = cli ]; then
            api GET /auth/me
            made="$made $(json_field role)"
        fi
    done
    api GET /auth/me
    made="$made $status $(json '[d["username"], d["role"], sorted(g["name"] for g in d["groups"])]')"
    token=$secret_0017
    api GET /auth/me
    made="$made $status $(json '[d["username"], d["role"]]')"
    token=$admin
    api GET /role-grants
    made="$made $(json '[g["role"] for g in d if g["user_hid"] == "'"${users_0017[grouped]}"'"]')"
    expect "pkg each user from before signs in with the access code it had with $previous_version, and the disabled one is still refused; the two whose codes were typed, of ${#typed_0017} and of ${#typed_cli_0017} characters, sign in with them, the second still an Admin, though a code that short is typed no longer: a code that is held is not looked at; the one whose contact is retired signs in as it did; the one in two groups still holds Inventory by its own grant; and the token of the service account still authenticates as it" \
        "$made" ' 200 admin 200 401 200 200 200 200 ["upgrade-17-grouped", "inventory", ["Upgrade Field Crew", "Upgrade Records Desk"]] 200 ["upgrade-17-robot", "viewer"] ["inventory"]'
    api GET "/contacts/$person_0017"
    made="$status $(json '[d["is_user"], d["is_operator"], [o["label"] for o in d["operators"]]]')"
    api GET "/users/${users_0017[left]}"
    made="$made $status $(json '[d["disabled"], d["contact"]["record_status"]]')"
    expect "pkg the contact of the person from before says it is a user and stands behind UP17 and UQ17; and the user whose contact is retired is not disabled, with its contact still retired" \
        "$made" '200 [true, true, ["UP17", "UQ17"]] 200 [false, "retired"]'
}
