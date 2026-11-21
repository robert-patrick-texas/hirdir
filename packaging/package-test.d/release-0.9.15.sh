# shellcheck shell=bash
# shellcheck disable=SC2034,SC2154  # Read by packaging/package-test.sh, whose names these are.
#
# hirdir 0.9.15, which has no migration, and refuses what the release before let an
# account that holds no role do (P-299).
#
# packaging/package-test.sh reads this file when the upgrade it tests crosses 0.9.15:
# the previous release is older, and the new version is 0.9.15 or a later one. It calls
# the three functions below: see "what one upgrade alone has" there.
#
# Nothing that is stored differs. Every release before 0.9.15 let an account with no
# role sign in, and see nothing, and 0.9.14 let it change its own details and its code.
# From 0.9.15 such an account is refused at sign-in, with a 403 that names whom to ask,
# and a session or a token that it holds is refused, a 401, as docs/install.md says
# under "From 0.9.14 to 0.9.15". So an account with no role that held a session before
# the upgrade has none after it, and none comes back when it is given a role: it signs
# in again, and holds the role. A service account with no role has its token refused
# until it is given one, and then the same token works, as an Admin may make one for it.

# The person with no role and the service account with no role that before_0_9_15
# makes, their HIDs, the access code of the person, the session it held with the
# previous release and the secret of the token of the service account.
noted_0_9_15=""
idle_0_9_15=""
idle_code_0_9_15=""
idle_session_0_9_15=""
robot_0_9_15=""
robot_secret_0_9_15=""

# idle_signed_0_9_15: sign in as the person with no role, through the API of whichever
# version serves. $status is the answer's, and $token is the session where it is 200.
idle_signed_0_9_15() {
    local body
    body=$(python3 -c 'import json, sys; print(json.dumps({"username": "upgrade-15-idle", "access_code": sys.argv[1]}))' \
        "$idle_code_0_9_15")
    api POST /auth/sign-in "$body"
    if [ "$status" = 200 ]; then token=$(json_field token); fi
}

# What the previous release lets an account with no role do: a person with no role is
# made and signs in, and keeps its session, and a service account with no role is made
# and given a token, which authenticates.
before_0_9_15() {
    local admin=$token made="" robot_hid
    noted_0_9_15=yes

    api POST /users '{"username": "upgrade-15-idle"}'
    made="$status"
    idle_0_9_15=$(json 'd["user"]["hid"]')
    idle_code_0_9_15=$(json 'd["access_code"] or ""')
    if [ "$status" = 201 ]; then users_made=$((users_made + 1)); fi
    api POST /users '{"username": "upgrade-15-robot", "is_service_account": true}'
    made="$made $status"
    robot_hid=$(json 'd["user"]["hid"]')
    robot_0_9_15=$robot_hid
    if [ "$status" = 201 ]; then users_made=$((users_made + 1)); fi
    api POST "/users/$robot_hid/service-tokens" '{"name": "upgrade 0.9.15 reader"}'
    made="$made $status"
    robot_secret_0_9_15=$(json_field secret)

    idle_signed_0_9_15
    made="$made $status"
    idle_session_0_9_15=$token
    api GET /auth/me
    made="$made $status $(json '[d["username"], d["role"]]')"
    token=$robot_secret_0_9_15
    api GET /auth/me
    made="$made $status $(json '[d["username"], d["role"]]')"
    token=$admin
    expect "pkg $previous_version lets an account with no role sign in: a person made with none signs in with its code and keeps the session, and a service account made with none has a token that authenticates" \
        "$made" '201 201 201 200 200 ["upgrade-15-idle", null] 200 ["upgrade-15-robot", null]'
}

# What the new version says of the session and the token from before, which it refuses
# as those of an account with no role. It changes nothing, and writes nothing: a refused
# request is no event.
changed_0_9_15() {
    local when=$1 admin=$token made
    [ -n "$noted_0_9_15" ] || return 0
    token=$idle_session_0_9_15
    api GET /auth/me
    made="$status $(json_field detail)"
    token=$robot_secret_0_9_15
    api GET /auth/me
    made="$made | $status $(json_field detail)"
    token=$admin
    expect "pkg $when the session that the account with no role held with $previous_version is refused, a 401 that says the account holds no role, and so is the token of the service account with none" \
        "$made" "401 the session has been ended: this account holds no role | 401 the token is not accepted: its service account holds no role"
}

# What is asked of the two accounts on the upgraded install: the person is refused at
# sign-in with a 403 that names whom to ask, as About does, and the refusal is in the
# audit trail; given a role, it signs in again and holds it, and the session from
# before stays refused; and the service account, given a role, has its token from
# before taken.
after_0_9_15() {
    local admin=$token made="" about
    [ -n "$noted_0_9_15" ] || return 0

    api GET /about
    about=$(json 'd["help"]')
    idle_signed_0_9_15
    made="$status $(json '[d["title"], d["detail"], sorted(d["help"]), "token" in d]') $([ "$(json 'd["help"]')" = "$about" ] && echo "as About")"
    token=$admin
    api GET "/audit-events?action=sign_in_no_role&record_hid=$idle_0_9_15"
    made="$made $(json '[[e["record_type"], e["actor_hid"] == "'"$idle_0_9_15"'"] for e in d["items"]]')"
    expect "pkg after the upgrade, the person with no role from $previous_version is refused at sign-in with its right code: a 403, No role, that says so and names whom to ask, as About names them, with no session; and the refusal is in the audit trail, sign_in_no_role" \
        "$made" '403 ["No role", "this account holds no role, and so cannot sign in: an Admin gives it one", ["email", "organization", "phone", "url"], false] as About [["user", true]]'

    api POST /role-grants "{\"role\": \"viewer\", \"user_hid\": \"$idle_0_9_15\"}"
    made=$status
    api POST /role-grants "{\"role\": \"viewer\", \"user_hid\": \"$robot_0_9_15\"}"
    made="$made $status"
    token=$idle_session_0_9_15
    api GET /auth/me
    made="$made $status"
    idle_signed_0_9_15
    made="$made $status"
    api GET /auth/me
    made="$made $(json '[d["username"], d["role"]]')"
    token=$robot_secret_0_9_15
    api GET /auth/me
    made="$made $status $(json '[d["username"], d["role"]]')"
    token=$admin
    expect "pkg given the View-only role, the person signs in with its code and holds it, and the session it held with $previous_version is still refused: it does not come back with the role; and the service account, given the role, has its token from before taken" \
        "$made" '201 201 401 200 ["upgrade-15-idle", "viewer"] 200 ["upgrade-15-robot", "viewer"]'
}
