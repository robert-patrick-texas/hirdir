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
# migration could have taken for something else: its record status, whether it is
# disabled, the role in force, its groups, the state of its contact, and the operators
# its contact stands behind. The new version serves when this is asked.
said_0017() {
    json '[[u["username"][len("upgrade-17-"):], u["record_status"], u["disabled"], u["role"], sorted(g["name"] for g in u["groups"]), (u["contact"] or {}).get("record_status"), [o["label"] for o in u["operators"]]] for u in d["items"] if u["username"].startswith("upgrade-17-")]'
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

    # The person stands behind two operators. together_0017 retires them again, as a
    # person is retired from 0.9.14, before what came after the groups is taken out.
    api GET "/users/${users_0017[person]}"
    person_0017=$(json_field contact_hid)
    for label in UP17 UQ17; do
        colour='#2e7d32'
        if [ "$label" = UQ17 ]; then colour='#6a1b9a'; fi
        api POST /operators "{\"label\": \"$label\", \"description\": \"Made before the upgrade to 0.9.14\", \"colour\": \"$colour\", \"contact_hid\": \"$person_0017\"}"
        made="$made $status"
        wanted="$wanted 201"
        operators_0017+=("$(json_field hid)")
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
    local when=$1 backup made
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
    made=$(said_0017)
    api GET '/users?retired=only&limit=1000'
    expect "pkg $when the API says each of them is active, and none was taken for something else: the disabled one is disabled and the others are not; the one in two groups is in both and holds Inventory; the person holds View-only and its contact stands behind UP17 and UQ17; and the contact of the one who left is retired, while its user is as it was; and GET /users?retired=only lists no user at all" \
        "$made $status $(json_field total)" \
        '[["cli", "active", false, "admin", [], null, []], ["grouped", "active", false, "inventory", ["Upgrade Field Crew", "Upgrade Records Desk"], "active", []], ["left", "active", false, null, [], "retired", []], ["off", "active", true, null, [], "active", []], ["person", "active", false, "viewer", [], "active", ["UP17", "UQ17"]], ["robot", "active", false, "viewer", [], null, []], ["short", "active", false, null, [], null, []]] 200 0'
    if [ -n "$gaps_0017" ]; then
        expect "pkg $when each gap of the list of users holds those of them that it held with $previous_version: none is retired, so none is left out of a gap" \
            "$(gaps_now_0017)" "$gaps_0017"
    fi
}

# What is asked of what was carried over: each user from before signs in again, or is
# refused, as it did, the two with a typed code that is short among them; the token
# still works; and each still holds what it held. Then what 0.9.14 is for, tried on
# those users, by the functions below it: the least length of a code that is typed from
# now, a person's own profile (S56), an account retired and brought back (S57), a
# person retired together (S58), and the account whose contact was retired under it.
# They leave the users as a site would have them after it: one retired, the others
# active, and no operator of theirs that is not retired.
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

    # What 0.9.14 is for, on what was carried over.
    length_0017
    profile_0017
    retired_0017
    together_0017
    left_0017
}

# length_0017: the least length of a typed access code (P-295), on the upgraded
# install: 12 unless set, for every code that is typed from now, by the API and by
# hirdir admin, and for none that is held. An Admin sets it under Settings.
length_0017() {
    local admin=$token made code=0 shorter=sh-18

    api GET /settings
    made=$(json '[[s["value"], s["default"], s["is_default"]] for s in d if s["key"] == "access_code_min_length"]')
    api POST "/users/${users_0017[short]}/access-code" '{"access_code": "eleven-char"}'
    made="$made $status $(json '[[e["field"], e["message"]] for e in d["errors"]]')"
    api POST /users '{"username": "upgrade-17-never", "access_code": "eleven-char"}'
    made="$made $status $(json '[e["field"] for e in d["errors"]]')"
    inside hirdir admin reset-access-code upgrade-17-short --access-code eleven-char >"$work/admin-code.log" 2>&1 || code=$?
    made="$made $code $(matches 'at least 12 characters' "$work/admin-code.log")"
    code=0
    inside hirdir admin create-user upgrade-17-never --access-code eleven-char >"$work/admin-code.log" 2>&1 || code=$?
    made="$made $code $(matches 'at least 12 characters' "$work/admin-code.log")"
    api GET '/users?q=upgrade-17-never&retired=yes'
    made="$made $(json_field total)"
    signed_0017 short
    made="$made $status"
    token=$admin
    expect "pkg the upgraded install has the setting access_code_min_length at its default, 12, and from now a code that is typed shorter is refused, with the length said: by POST /users/{hid}/access-code and by POST /users with a 422 on access_code, and by hirdir admin reset-access-code and create-user, which exit with 4; no user was made, and the code of ${#typed_0017} characters from before, which nobody changed, still signs in" \
        "$made" '[[12, 12, true]] 422 [["access_code", "at least 12 characters (access_code_min_length)"]] 422 ["access_code"] 4 1 4 1 0 200'

    made=$(put_setting access_code_min_length ${#shorter})
    api POST "/users/${users_0017[short]}/access-code" "{\"access_code\": \"$shorter\"}"
    made="$made $status"
    signed_0017 short
    made="$made $status"
    codes_0017[short]=$shorter
    signed_0017 short
    made="$made $status"
    token=$admin
    made="$made $(put_setting access_code_min_length null)"
    signed_0017 short
    made="$made $status"
    token=$admin
    expect "pkg an Admin sets access_code_min_length to ${#shorter}, and a code of ${#shorter} characters is taken for that user: the code before signs in no longer, and the new one does; with the setting returned to its default the new code still signs in, since a code that is held is not looked at" \
        "$made" "200 ${#shorter} 200 401 200 200 12 200"

    # The Admin that was set up with a short code changes it on its own, the short code
    # being the one it has.
    signed_0017 cli
    api POST /auth/me/access-code "{\"current_access_code\": \"${codes_0017[cli]}\", \"access_code\": \"upgrade-17-cli-code\"}"
    made=$status
    token=$admin
    signed_0017 cli
    made="$made $status"
    codes_0017[cli]=upgrade-17-cli-code
    token=$admin
    signed_0017 cli
    api GET /auth/me
    token=$admin
    expect "pkg the Admin whose code of ${#typed_cli_0017} characters was typed with $previous_version changes it for a longer one by POST /auth/me/access-code, the short code being asked for as the one it has: the short code signs in no longer, the new one does, and it is an Admin still" \
        "$made $status $(json_field role)" '200 401 200 admin'
}

# profile_0017: S56 on what was carried over. The View-only person from before, a
# contact behind two operators, changes what is its own, and nothing of another.
profile_0017() {
    local admin=$token made here elsewhere mine hid=${users_0017[person]} other new=upgrade-17-person-code

    signed_0017 person
    made=$status
    here=$token
    token=$admin
    signed_0017 person
    made="$made $status"
    elsewhere=$token
    api GET /auth/me
    expect "S56 after the upgrade, the View-only person from before reads at GET /auth/me the contact it is, with its organization and a row_version to change it at, and the two operators it is behind, each with its own" \
        "$made $status $(json '[d["role"], d["contact"]["name"], d["contact"]["organization"], isinstance(d["contact"]["row_version"], int), [[o["label"], isinstance(o["row_version"], int)] for o in d["operators"]]]')" \
        '200 200 200 ["viewer", "Example Label Person", "Example Operations", true, [["UP17", true], ["UQ17", true]]]'

    token=$here
    api PATCH /auth/me/contact "{\"row_version\": $(json 'd["contact"]["row_version"]'), \"name\": \"Example Label Person-Smith\", \"email\": \"label.person-smith@example.net\", \"phone\": \"+1 555 0175\", \"phone2\": \"+1 555 0176\", \"organization\": \"Example Field Operations\"}"
    made=$status
    api PATCH "/auth/me/operators/${operators_0017[0]}" "{\"row_version\": $(json '[o["row_version"] for o in d["operators"] if o["label"] == "UP17"][0]'), \"label\": \"UP18\", \"colour\": \"#1f6feb\"}"
    made="$made $status $(json '[[o["label"], o["colour"]] for o in d["operators"]]')"
    token=$admin
    api GET "/contacts/$person_0017"
    expect "S56 it changes its own name, email, numbers and organization, and the label and the colour of one of its operators, and an Admin reads them on the contact" \
        "$made $(json '[d["name"], d["email"], d["phone"], d["phone2"], d["organization"]]')" \
        '200 200 [["UP18", "#1f6feb"], ["UQ17", "#6a1b9a"]] ["Example Label Person-Smith", "label.person-smith@example.net", "+1 555 0175", "+1 555 0176", "Example Field Operations"]'

    token=$here
    api POST /auth/me/access-code "{\"current_access_code\": \"not-the-code-i-have\", \"access_code\": \"$new\"}"
    made="$status $(json '[[e["field"], e["message"]] for e in d["errors"]]')"
    api POST /auth/me/access-code "{\"current_access_code\": \"${codes_0017[person]}\", \"access_code\": \"eleven-char\"}"
    made="$made $status $(json '[[e["field"], e["message"]] for e in d["errors"]]')"
    api GET /auth/me
    made="$made $status"
    token=$elsewhere
    api GET /auth/me
    made="$made $status"
    signed_0017 person
    made="$made $status"
    token=$admin
    api GET "/audit-events?action=set_access_code&record_hid=$hid"
    expect "S56 a wrong current code and a new code that is too short are each a 422 on its field that says why, and change nothing: both sessions stand, the code from before signs in, and no code was set" \
        "$made $(json_field total)" \
        '422 [["current_access_code", "this is not the access code you have"]] 422 [["access_code", "at least 12 characters (access_code_min_length)"]] 200 200 200 0'

    token=$here
    api POST /auth/me/access-code "{\"current_access_code\": \"${codes_0017[person]}\", \"access_code\": \"$new\"}"
    made="$status $(json 'sorted(d)')"
    mine=$(json_field token)
    token=$mine
    api GET /auth/me
    made="$made $status $(json 'd["contact"]["name"]')"
    token=$here
    api GET /auth/me
    made="$made $status"
    token=$elsewhere
    api GET /auth/me
    made="$made $status"
    token=$admin
    signed_0017 person
    made="$made $status"
    codes_0017[person]=$new
    token=$admin
    signed_0017 person
    expect "S56 with the code it has, the code is changed: the answer carries a new session for the one in hand, which stays signed in; the token that asked and the other session are ended; the code from before signs in no longer, and the new one does" \
        "$made $status" '200 ["expires_at", "token", "user"] 200 Example Label Person-Smith 401 401 401 200'

    token=$admin
    api GET "/audit-events?record_type=contact&record_hid=$person_0017&action=update&actor_hid=$hid"
    made=$(json '[sorted(c["field"] for c in e["changes"]) for e in d["items"]]')
    api GET "/audit-events?record_type=operator&record_hid=${operators_0017[0]}&action=update"
    made="$made $(json '[[e["actor_hid"] == "'"$hid"'", sorted(c["field"] for c in e["changes"])] for e in d["items"]]')"
    api GET "/audit-events?action=set_access_code&record_hid=$hid"
    made="$made $(json '[e["actor_name"] for e in d["items"]]')"
    api GET "/audit-events?action=access_code_refused&record_hid=$hid"
    expect "S56 each change is in the audit trail by that user: the five fields of the contact, the label and the colour of the operator, and the access code; and so is the code that was refused" \
        "$made $(json '[e["actor_name"] for e in d["items"]]')" \
        '[["email", "name", "organization", "phone", "phone2"]] [[true, ["colour", "label"]]] ["upgrade-17-person"] ["upgrade-17-person"]'

    # Nothing of another: the label of the witness, and the contact of the one in two
    # groups.
    api GET '/operators?filter=label:eq:UW7'
    other=$(json 'd["items"][0]["hid"]')
    token=$mine
    api PATCH "/auth/me/operators/$other" '{"row_version": 1, "label": "taken"}'
    made=$status
    api PATCH "/operators/$other" '{"row_version": 1, "label": "taken"}'
    made="$made $status"
    api PATCH "/contacts/$left_0017" '{"row_version": 1, "name": "Taken"}'
    made="$made $status"
    api POST "/users/${users_0017[grouped]}/access-code" '{}'
    made="$made $status"
    api GET /auth/me
    api PATCH /auth/me/contact "{\"row_version\": $(json 'd["contact"]["row_version"]'), \"email\": \"grouped.engineer@example.net\"}"
    made="$made $status $(json '[[e["field"] for e in d["errors"]], d["existing"]["label"]]')"
    token=$secret_0017
    api PATCH /auth/me/contact '{"row_version": 1, "name": "Taken"}'
    made="$made $status"
    token=$admin
    api GET "/operators/$other"
    expect "S56 and it changes nothing of another: an operator of another is not found by the routes of its own, and is not its to change by the routes of the inventory, nor are the contact and the access code of another; an email that another contact has is refused with that contact named; and the service token from before is refused by the routes of a person's own" \
        "$made $(json_field label)" '404 403 403 403 409 [["email"], "Example Grouped Engineer"] 403 UW7'
}

# retired_0017: S57 on what was carried over. The account from before that is in two
# groups with a role of its own is retired, left out until the retired are asked for,
# keeps its username, and is brought back with a new code and nothing else.
retired_0017() {
    local admin=$token made got request row gone which back code=0 hid=${users_0017[grouped]}

    signed_0017 grouped
    gone=$token
    token=$admin
    api GET "/users/$hid"
    row=$(json_field row_version)
    api POST "/users/$hid/retire" "{\"row_version\": $row}"
    made="$status $(json '[[e["field"] for e in d["errors"]], [[r["record_type"], r["label"]] for r in d["depends_on"]]]')"
    api POST "/users/$hid/retire" "{\"row_version\": $row, \"linked\": {\"contact\": \"keep\"}}"
    request=$(header x-request-id)
    made="$made $status $(json '[d["record_status"], d["disabled"], d["role"], d["groups"]]')"
    row=$(json_field row_version)
    token=$gone
    api GET /auth/me
    made="$made $status"
    token=$admin
    signed_0017 grouped
    made="$made $status"
    token=$admin
    expect "S57 after the upgrade, an Admin retires the account from before that is in two groups with a role of its own: saying nothing of its contact is a 409 that names the contact; with the contact kept, the account is retired, in no group and holds no role, its session is ended and its code signs in no longer; each is in the audit trail under the one request, the two memberships, the role and the retirement, and the contact is told that it is no user's" \
        "$made $(events_of "$request")" \
        '409 [["linked.contact"], [["contact", "Example Grouped Engineer"]]] 200 ["retired", false, null, []] 401 401 [["remove_member", "user_group"], ["remove_member", "user_group"], ["revoke_role", "user"], ["retire", "user"], ["update", "contact"]]'

    got=""
    for which in 'limit=1000' 'retired=yes&limit=1000' 'retired=only&limit=1000'; do
        api GET "/users?$which"
        got="$got $(json '[u["username"][len("upgrade-17-"):] for u in d["items"] if u["username"] in ("upgrade-17-grouped", "upgrade-17-off")]')"
    done
    for which in '' '?retired=yes' '?retired=only'; do
        authorized POST "$prefix/api/v1/users/export$which"
        got="$got $(table '[[r["username"][len("upgrade-17-"):], r["state"], r["record_status"]] for r in rows if r["username"] in ("upgrade-17-grouped", "upgrade-17-off")]')"
    done
    api GET '/users?operator=none&retired=yes&limit=1000'
    got="$got $(json '"upgrade-17-grouped" in [u["username"] for u in d["items"]]')"
    api GET "/users/$hid"
    api GET "/contacts/$(json_field contact_hid)"
    expect "S57 the list of users and the users' file leave it out until the retired are asked for, and the file says which each is, the disabled one from before disabled and active, and the retired one retired; it is in no gap, though the retired are asked for; and its contact says it is no user" \
        "$got $(json_field is_user)" \
        ' ["off"] ["grouped", "off"] ["grouped"] [["off", "disabled", "active"]] [["grouped", "enabled", "retired"], ["off", "disabled", "active"]] [["grouped", "enabled", "retired"]] false false'

    api POST /users '{"username": "upgrade-17-grouped"}'
    made="$status $(json '[[e["field"] for e in d["errors"]], d["existing"]["hid"] == "'"$hid"'", d["existing"]["label"]]')"
    inside hirdir admin reset-access-code upgrade-17-grouped >"$work/admin-code.log" 2>&1 || code=$?
    expect "S57 a new account of its username is refused with a 409 on username that names the retired one; and hirdir admin reset-access-code gives a retired account no code, and exits with 4" \
        "$made $code $(matches 'retired' "$work/admin-code.log")" '409 [["username"], true, "upgrade-17-grouped"] 4 1'

    api POST "/users/$hid/bring-back" "{\"row_version\": $row}"
    request=$(header x-request-id)
    back=$(json_field access_code)
    made="$status $(json '[d["user"]["record_status"], d["user"]["role"], d["user"]["groups"]]') $([ -n "$back" ] && [ "$back" != "${codes_0017[grouped]}" ] && echo new)"
    signed_0017 grouped
    made="$made $status"
    codes_0017[grouped]=$back
    token=$admin
    signed_0017 grouped
    made="$made $status"
    api GET /auth/me
    made="$made $(json_field role)"
    token=$admin
    expect "S57 brought back by an Admin, the account is active with a new access code, shown once, no role and no group: the code from before signs in no longer, and the new one does; it is audited as bring_back, and its contact is told that it is a user's again" \
        "$made $(events_of "$request")" \
        '200 ["active", null, []] new 401 200 null [["bring_back", "user"], ["update", "contact"]]'
}

# together_0017: S58 on what was carried over. The person from before, a user who is a
# contact behind two operators, is retired together or not at all, and is brought back
# by an Admin alone. The label that is handed over goes to the contact of the account
# in two groups, and is retired at the end, so that no operator of this file is left.
together_0017() {
    local admin=$token made got request row events back to hid=${users_0017[person]}

    api GET "/users/${users_0017[grouped]}"
    to=$(json_field contact_hid)
    api GET "/contacts/$person_0017"
    row=$(json_field row_version)
    api GET '/audit-events?limit=1'
    events=$(json_field total)
    api POST "/contacts/$person_0017/retire" "{\"row_version\": $row}"
    made="$status $(json '[sorted(e["field"] for e in d["errors"]), [[r["record_type"], r["label"]] for r in d["depends_on"]]]')"
    api GET "/contacts/$person_0017/linked"
    made="$made $(json '[d["user"]["record_status"], d["contact"]["record_status"], [o["record_status"] for o in d["operators"]]]')"
    api GET '/audit-events?limit=1'
    expect "S58 after the upgrade, retiring the contact of the person from before and saying nothing of the rest is a 409 that names the user and both operators; nothing is changed and no event is written" \
        "$made $(($(json_field total) - events))" \
        '409 [["linked.operators", "linked.user"], [["operator", "UP18"], ["operator", "UQ17"], ["user", "upgrade-17-person"]]] ["active", "active", ["active", "active"]] 0'

    api POST "/contacts/$person_0017/retire" "{\"row_version\": $row, \"linked\": {\"user\": \"retire\", \"operators\": [{\"hid\": \"${operators_0017[0]}\", \"action\": \"hand_over\", \"contact_hid\": \"$to\"}, {\"hid\": \"${operators_0017[1]}\", \"action\": \"retire\"}]}}"
    request=$(header x-request-id)
    made=$status
    got=$(events_of "$request")
    api GET "/users/$hid/linked"
    made="$made $(json '[d["user"]["record_status"], d["contact"]["record_status"], [[o["label"], o["record_status"]] for o in d["operators"]]]')"
    api GET "/operators/${operators_0017[0]}"
    expect "S58 with the user retired, one operator handed over to another person and one released, the person is retired in one change: the user and the contact are retired, the first label is behind the other person and the second is retired, each audited under the one request" \
        "$made $(json '[d["contact_hid"] == "'"$to"'", d["record_status"]]') $got" \
        '200 ["retired", "retired", [["UQ17", "retired"]]] [true, "active"] [["update", "operator"], ["retire", "operator"], ["revoke_role", "user"], ["retire", "user"], ["update", "contact"], ["retire", "contact"]]'

    # The second user of the pass holds Inventory through its group.
    sign_in upgrade-engineer "$engineer_code"
    api GET "/contacts/$person_0017"
    api PATCH "/contacts/$person_0017" "{\"row_version\": $(json_field row_version), \"record_status\": \"active\"}"
    made=$status
    api GET "/operators/${operators_0017[1]}"
    api PATCH "/operators/${operators_0017[1]}" "{\"row_version\": $(json_field row_version), \"record_status\": \"active\"}"
    made="$made $status"
    token=$admin
    api GET "/contacts/$person_0017"
    made="$made $(json_field record_status)"
    api GET "/operators/${operators_0017[1]}"
    expect "S58 the user from before who holds Inventory cannot bring the contact back, nor the label: each is a 403, and both stay retired" \
        "$made $(json_field record_status)" '403 403 retired retired'

    api GET "/users/$hid"
    row=$(json_field row_version)
    api POST "/users/$hid/bring-back" "{\"row_version\": $row}"
    made="$status $(json '[[e["field"] for e in d["errors"]], d["existing"]["hid"] == "'"$person_0017"'"]')"
    api POST "/users/$hid/bring-back" "{\"row_version\": $row, \"linked\": {\"contact\": \"bring_back\"}}"
    made="$made $status"
    back=$(json_field access_code)
    api GET "/users/$hid/linked"
    made="$made $(json '[d["user"]["record_status"], d["user"]["role"], d["contact"]["record_status"], [[o["label"], o["record_status"]] for o in d["operators"]]]')"
    codes_0017[person]=$back
    signed_0017 person
    made="$made $status"
    api GET /auth/me
    made="$made $(json_field role)"
    token=$admin
    expect "S58 an Admin brings the user back: alone it is a 409 on linked.contact that names the retired contact; with the contact, both are active again, the released label stays retired, and the person signs in with the new code and holds no role" \
        "$made" '409 [["linked.contact"], true] 200 ["active", null, "active", [["UQ17", "retired"]]] 200 null'

    api GET "/operators/${operators_0017[0]}"
    row=$(json_field row_version)
    api POST "/operators/${operators_0017[0]}/retire" "{\"row_version\": $row, \"linked\": $(linked_kept "operators/${operators_0017[0]}")}"
    expect "pkg the label that was handed over is retired, the person behind it and that person's account kept, which the request says: no operator of the users from before is left" \
        "$status $(json_field record_status)" '200 retired'
}

# left_0017: the user from before whose contact was left retired under it, which
# 0.9.14 reads as before, as no contact (P-297). It signs in and has no profile to
# change; and an Admin retires the account by itself, as docs/install.md says to do
# after the upgrade, with nothing to say of a contact that is retired already.
left_0017() {
    local admin=$token made hid=${users_0017[left]}

    signed_0017 left
    made=$status
    api GET /auth/me
    made="$made $(json '[d["contact"]["record_status"], d["operators"]]')"
    api PATCH /auth/me/contact "{\"row_version\": $(json 'd["contact"]["row_version"]'), \"phone\": \"+1 555 0177\"}"
    made="$made $status"
    token=$admin
    api GET "/users/$hid"
    api POST "/users/$hid/retire" "{\"row_version\": $(json_field row_version)}"
    made="$made $status $(json_field record_status)"
    signed_0017 left
    made="$made $status"
    token=$admin
    api GET '/users?contact=none&limit=1000'
    made="$made $(json '"upgrade-17-left" in [u["username"] for u in d["items"]]')"
    api GET '/users?retired=only&limit=1000'
    expect "pkg the user from before whose contact was left retired under it signs in, reads its contact as retired and no operator, and changes nothing of that contact, a 409; an Admin retires the account with its row_version alone, the contact being retired already: it signs in no longer, is in the gap of those with no contact no longer, and is the one retired account there is" \
        "$made $(json '[u["username"] for u in d["items"]]')" \
        '200 ["retired", []] 409 200 retired 401 false ["upgrade-17-left"]'
}
