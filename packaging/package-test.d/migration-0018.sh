# shellcheck shell=bash
# shellcheck disable=SC2034,SC2154  # Read by packaging/package-test.sh, whose names these are.
#
# Migration 0018, which came with hirdir 0.9.17: the kind of an account, and agents
# (P-316).
#
# packaging/package-test.sh reads this file when the upgrade it tests runs the
# migration, and calls the three functions below: see "what one upgrade alone has"
# there. The previous release is then at revision 0017 or before: an account is a
# person's or a service account, which its API says by is_service_account, true or
# false, and which POST /users takes, as hirdir admin create-user takes
# --service-account. It knows no kind of an account, no agent, and no person answerable
# for one, and its audit trail says of an event the account that made it and nothing
# more. P-306: the upgrade to 0.9.17 is tested from 0.9.16 alone, so this file talks to
# that release in its own API, and asks of nothing older.
#
# The migration makes the table of the users anew: it adds kind, service for each
# account that was a service account and person for every other, and answerable_hid,
# empty for each, with its foreign key to users and its index, and drops
# is_service_account. It adds for_hid to the audit trail, empty for every event. It
# creates no table and writes no audit event, so the pass whose migration fails puts the
# trigger on alembic_version in its way, and all of it has to be undone. Nothing else of
# a row is changed: every account is what it was, in another word, signs in or is
# refused as it was, and keeps its tokens, its role, its groups and its row_version.
# There is no agent after it: an agent is made by an Admin, from 0.9.17. Going back is by
# the backup the upgrade took. docs/install.md says all of it under "From 0.9.16 to
# 0.9.17", and what is said there is what is looked for here.
writes_no_event=yes
# The table of the accounts, which is no part of the inventory, is kept and compared as
# the inventory's tables are: every row holds what it held in the columns it keeps, and
# the two columns are after them. A file of an earlier migration may have named it.
case " $more_tables " in
    *" users "*) ;;
    *) more_tables="${more_tables:+$more_tables }users" ;;
esac
# So are the tables that name a user, which a table made anew could take rows from: the
# groups, their members, the grants of roles and the tokens, each row as it was.
for table_0018 in user_groups user_group_members role_grants service_tokens; do
    case " $more_tables " in
        *" $table_0018 "*) ;;
        *) more_tables="$more_tables $table_0018" ;;
    esac
done
unset table_0018
also new_columns users 'kind VARCHAR(10) NOT NULL -
answerable_hid VARCHAR(36) NULL -'
gone_columns[users]="${gone_columns[users]:+${gone_columns[users]} }is_service_account"
also new_keys users 'foreign key answerable_hid to users.hid
index ix_users_answerable_hid on answerable_hid unique=0 origin=c partial=0'
# The column of the audit trail, which the check that the upgrade wrote no event leaves
# out of what it compares, and which changed_0018 looks at by itself.
also new_columns audit_events 'for_hid VARCHAR(36) NULL -'

# Set by before_0018 where the previous release holds what this file makes.
noted_0018=""
# The users that before_0018 makes, each by what it is: person, a person with a contact
# who holds Inventory of their own; grouped, a person with a contact who holds View-only
# through a group alone; off, a disabled person; left, a retired one; robot, a service
# account that holds Inventory, with a token; idle, a service account that holds no
# role, with a token, which is refused; and cli, a service account that hirdir admin
# create-user --service-account made with View-only, with a token. Their usernames are
# upgrade-18- and that word. The HID of each, the access code of each person who signs
# in, and the secret of each token.
kinds_0018="cli grouped idle left off person robot"
declare -gA users_0018=() codes_0018=() secrets_0018=()
# The group that grants View-only.
group_0018=""
# What the previous release said of each sign-in and token, which the upgraded install
# is to say again.
signed_before_0018=""
# The users that the pass made itself, which changed_0018 also finds of their kind.
pass_users_0018="upgrade-admin upgrade-engineer upgrade-robot"

# signed_0018 KIND: sign in as the user of that kind that before_0018 made, with its
# access code, through the API of whichever version serves. $status is the answer's, and
# $token is the session where it is 200, and as it was otherwise.
signed_0018() {
    local body
    body=$(python3 -c 'import json, sys; print(json.dumps({"username": sys.argv[1], "access_code": sys.argv[2]}))' \
        "upgrade-18-$1" "${codes_0018[$1]:-none}")
    api POST /auth/sign-in "$body"
    if [ "$status" = 200 ]; then token=$(json_field token); fi
}

# signs_0018: what each user of the file answers when it signs in, and each token, as
# "kind status" pairs, through whichever version serves. It leaves $token as it found it.
signs_0018() {
    local admin=$token kind got=""
    for kind in person grouped off left; do
        signed_0018 "$kind"
        got="$got $kind $status"
        if [ "$status" = 200 ]; then
            api GET /auth/me
            got="$got $(json_field role)"
        fi
        token=$admin
    done
    for kind in robot idle cli; do
        token=${secrets_0018[$kind]:-none}
        api GET /auth/me
        got="$got $kind $status"
        if [ "$status" = 200 ]; then got="$got $(json_field role)"; else got="$got $(json_field detail)"; fi
        token=$admin
    done
    printf '%s' "${got# }"
}

# said_0018: what the last response, GET /users, says of each user of the file, with the
# new version serving: its kind, the person it is answerable to, its agents, its role,
# the role in force and why it is lower, whether it is disabled, its record status, and
# each grant with the group it comes through.
said_0018() {
    json '[[u["username"][len("upgrade-18-"):], u["kind"], u["answerable_hid"], u["agents"], u["role"], u["role_in_force"], u["role_capped_by"], u["disabled"], u["record_status"], [[g["role"], (g["group"] or {}).get("name")] for g in u["grants"]]] for u in d["items"] if u["username"].startswith("upgrade-18-")]'
}

# What the migration could harm, made with the previous release: a person of each state,
# one who holds a role of their own and one through a group alone, one disabled and one
# retired; and service accounts, one that holds a role and one that holds none, each with
# a token, and one that hirdir admin made. Each signs in, or is refused, before the
# upgrade, so that the rows kept are those it is to sign in to after it.
before_0018() {
    local admin=$token made="" wanted="" kind body hid
    previous_at 0017 || return 0
    noted_0018=yes

    # The accounts of the pass, made before this file made any. Their rows are let be by
    # the comparison of the rows of users, as an account of the pass signs in again
    # before it: the API looks at each, and the users of this file are compared there.
    api GET '/users?limit=1000'
    rows_apart[users]="${rows_apart[users]:+${rows_apart[users]},}$(json '",".join(u["hid"] for u in d["items"] if not __import__("re").match(r"upgrade-\d+-", u["username"]))')"

    api POST /user-groups '{"name": "Upgrade Kinds Desk", "description": "Made before the upgrade to 0.9.17"}'
    made="$made $status"
    group_0018=$(json_field hid)
    api POST /role-grants "{\"role\": \"viewer\", \"group_hid\": \"$group_0018\"}"
    made="$made $status"
    wanted="$wanted 201 201"
    groups_made=$((groups_made + 1))
    grants_made=$((grants_made + 1))

    # A user of each kind that the API of the previous release makes, in its words.
    for kind in person grouped off left robot idle; do
        case $kind in
            person) body='{"username": "upgrade-18-person", "contact": {"name": "Example Answerable Person", "email": "answerable.person@example.net"}, "role": "inventory"}' ;;
            grouped) body="{\"username\": \"upgrade-18-grouped\", \"contact\": {\"name\": \"Example Desk Person\"}, \"group_hids\": [\"$group_0018\"]}" ;;
            off) body='{"username": "upgrade-18-off", "contact": {"name": "Example Paused Person 18"}, "role": "viewer"}' ;;
            left) body='{"username": "upgrade-18-left", "role": "viewer"}' ;;
            robot) body='{"username": "upgrade-18-robot", "is_service_account": true, "role": "inventory"}' ;;
            idle) body='{"username": "upgrade-18-idle", "is_service_account": true}' ;;
        esac
        api POST /users "$body"
        made="$made $status"
        wanted="$wanted 201"
        users_0018[$kind]=$(json 'd["user"]["hid"]')
        codes_0018[$kind]=$(json 'd["access_code"] or ""')
        if [ "$status" = 201 ]; then users_made=$((users_made + 1)); fi
    done
    # person, off and robot hold a role of their own; left's is revoked as it is retired.
    grants_made=$((grants_made + 3))
    # And a service account that hirdir admin makes, on the host, as the previous release
    # spells it.
    inside hirdir admin create-user upgrade-18-cli --service-account --role viewer >"$work/create-user.log" 2>&1 || true
    made="$made $(grep -c '^created upgrade-18-cli with the viewer role$' "$work/create-user.log" || true) $(grep -c '^access code: ' "$work/create-user.log" || true)"
    wanted="$wanted 1 0"
    api GET '/users?limit=1000'
    users_0018[cli]=$(json '"".join(u["hid"] for u in d["items"] if u["username"] == "upgrade-18-cli")')
    if [ -n "${users_0018[cli]}" ]; then
        users_made=$((users_made + 1))
        grants_made=$((grants_made + 1))
    fi

    for kind in robot idle cli; do
        api POST "/users/${users_0018[$kind]}/service-tokens" "{\"name\": \"upgrade 0018 $kind\"}"
        made="$made $status"
        wanted="$wanted 201"
        secrets_0018[$kind]=$(json_field secret)
    done
    api PATCH "/users/${users_0018[off]}" '{"row_version": 1, "disabled": true}'
    made="$made $status"
    api POST "/users/${users_0018[left]}/retire" '{"row_version": 1}'
    made="$made $status $(json_field record_status)"
    wanted="$wanted 200 200 retired"

    # Each signs in, or is refused, and each token answers, or is refused. The retired
    # one is listed when the retired are asked for.
    signed_before_0018=$(signs_0018)
    api GET '/users?retired=yes&limit=1000'
    expect "pkg $previous_version holds accounts of each kind that migration 0018 gives a kind: a person who holds Inventory of their own, a person who holds View-only through a group alone, a disabled person and a retired one; a service account that holds Inventory, one that holds no role, and one that hirdir admin create-user --service-account made with View-only, each with a token. Each person signs in but the disabled and the retired one, and each token is taken but the one of the account with no role; and the API says is_service_account of each, and no kind" \
        "$made | $signed_before_0018 | $status $(json '[[u["username"][len("upgrade-18-"):], u["is_service_account"], "kind" in u, u["disabled"], u["record_status"], u["role"]] for u in d["items"] if u["username"].startswith("upgrade-18-")]')" \
        "$wanted | person 200 inventory grouped 200 viewer off 401 left 401 robot 200 inventory idle 401 the token is not accepted: its service account holds no role cli 200 viewer | 200 [[\"cli\", true, false, false, \"active\", \"viewer\"], [\"grouped\", false, false, false, \"active\", \"viewer\"], [\"idle\", true, false, false, \"active\", null], [\"left\", false, false, false, \"retired\", null], [\"off\", false, false, true, \"active\", \"viewer\"], [\"person\", false, false, false, \"active\", \"inventory\"], [\"robot\", true, false, false, \"active\", \"inventory\"]]"
    keep people-0018

    # What the previous release does not know: a kind, an agent and the person
    # answerable for one. Each is refused, and nothing changes.
    api POST /users "{\"username\": \"upgrade-18-agent\", \"kind\": \"agent\", \"answerable_hid\": \"${users_0018[person]}\"}"
    made="$status $(json '[e["field"] for e in d.get("errors", [])]')"
    api PATCH "/users/${users_0018[robot]}" '{"row_version": 1, "kind": "agent"}'
    made="$made $status"
    api GET '/audit-events?limit=1'
    made="$made $(json '[k for k in ("actor_kind", "for_hid", "for_name") if k in d["items"][0]]')"
    api GET '/users?retired=yes&limit=1000'
    expect "pkg $previous_version knows no kind of an account and no agent: POST /users of an agent is a 422 on what it does not take, a kind given to a service account by PATCH is a 422, and an event of the audit trail says no kind of its actor and no person it was for; and what was asked changed nothing of the seven users" \
        "$made $status $(unchanged people-0018 more)" \
        '422 ["kind", "answerable_hid"] 422 [] 200 same'

    # Every user from before answers is_service_account, which the new version answers
    # as kind: the comparison of the users passes over it, and changed_0018 looks at it.
    for hid in $(json '" ".join(u["hid"] for u in d["items"])'); do
        meant[users]="${meant[users]:-} $hid.is_service_account"
    done
}

# What the migration made, and what the new version says of the users from before,
# looked at by themselves with the new version serving. It changes nothing.
changed_0018() {
    local when=$1 backup made
    [ -n "$noted_0018" ] || return 0

    # The backup that the upgrade took is the way back.
    backup=$(sed -n 's/^hirdir: the database as it was before this upgrade is kept at //p' "$work/apt.log")
    expect "pkg $when the backup that the upgrade took holds every user, in a table with is_service_account and no column kind or answerable_hid, and an audit trail with no column for_hid, so going back to $previous_version is by that backup (${backup:-no backup})" \
        "$(sqlite_value "${backup:-/nonexistent}" "SELECT count(*) FROM pragma_table_info('users') WHERE name IN ('kind', 'answerable_hid')") $(sqlite_value "${backup:-/nonexistent}" "SELECT count(*) FROM pragma_table_info('users') WHERE name = 'is_service_account'") $(sqlite_value "${backup:-/nonexistent}" "SELECT count(*) FROM pragma_table_info('audit_events') WHERE name = 'for_hid'") $(sqlite_value "${backup:-/nonexistent}" 'SELECT count(*) FROM users')" \
        "0 1 0 $(sqlite_value /var/lib/hirdir/hirdir.db 'SELECT count(*) FROM users')"
    expect "pkg $when every account is of the kind it was: service where the backup holds a service account and person where it holds any other, none an agent, and none answerable to anybody; and a row written without a kind is a person's" \
        "$(inside runuser -u hirdir -- /opt/hirdir/python/bin/python3 -I -c '
import sqlite3, sys

then = sqlite3.connect(sys.argv[1]).execute("SELECT hid, CASE WHEN is_service_account THEN '"'service'"' ELSE '"'person'"' END FROM users ORDER BY hid").fetchall()
now = sqlite3.connect("/var/lib/hirdir/hirdir.db")
kinds = now.execute("SELECT hid, kind FROM users ORDER BY hid").fetchall()
counted = dict(now.execute("SELECT kind, count(*) FROM users GROUP BY kind").fetchall())
answerable = now.execute("SELECT count(*) FROM users WHERE answerable_hid IS NOT NULL").fetchone()[0]
default = now.execute("SELECT dflt_value FROM pragma_table_info('"'users'"') WHERE name = '"'kind'"'").fetchone()[0]
print("same" if then == kinds else "differ", sorted(counted), answerable, default)' "${backup:-/nonexistent}" 2>&1)" \
        "same ['person', 'service'] 0 'person'"
    expect "pkg $when the audit trail has the column for_hid after its others, and it is empty in every event: no agent made any" \
        "$(table_read audit_events columns | tail -n 1) $(sqlite_value /var/lib/hirdir/hirdir.db 'SELECT count(*) FROM audit_events WHERE for_hid IS NOT NULL')" \
        "for_hid VARCHAR(36) NULL - 0"

    # Each user from before, by the API: every field it had, as it was, but
    # is_service_account, which is its kind now.
    api GET '/users?retired=yes&limit=1000'
    expect "pkg $when each of the seven users made with $previous_version is as it was, field for field, its contact, its role, its groups and its row_version among them, but for is_service_account, which the new version answers as kind" \
        "$status $(unchanged people-0018 'fields more' "${meant[users]:-}")" "200 same"
    made=$(said_0018)
    expect "pkg $when the API says of each its kind, service where it was a service account and person where it was not, answerable to nobody and with no agents; each holds the role it held, which is the role in force; and each answers its grants, the one in the group through it" \
        "$made" \
        '[["cli", "service", null, [], "viewer", "viewer", null, false, "active", [["viewer", null]]], ["grouped", "person", null, [], "viewer", "viewer", null, false, "active", [["viewer", "Upgrade Kinds Desk"]]], ["idle", "service", null, [], null, null, null, false, "active", []], ["left", "person", null, [], null, null, null, false, "retired", []], ["off", "person", null, [], "viewer", "viewer", null, true, "active", [["viewer", null]]], ["person", "person", null, [], "inventory", "inventory", null, false, "active", [["inventory", null]]], ["robot", "service", null, [], "inventory", "inventory", null, false, "active", [["inventory", null]]]]'
    made=""
    for kind in person service agent; do
        api GET "/users?kind=$kind&retired=yes&limit=1000"
        made="$made $status $(json '[u["username"] for u in d["items"] if u["username"].startswith("upgrade-")]')"
    done
    expect "pkg $when GET /users?kind= lists the accounts from before by their kind: the persons, the service accounts, among them the pass's own, and no agent" \
        "$made" \
        ' 200 ["upgrade-18-grouped", "upgrade-18-left", "upgrade-18-off", "upgrade-18-person", "upgrade-admin", "upgrade-engineer"] 200 ["upgrade-18-cli", "upgrade-18-idle", "upgrade-18-robot", "upgrade-robot"] 200 []'
    api GET '/audit-events?actor_kind=agent&limit=1'
    made="$status $(json_field total)"
    api GET '/audit-events?limit=1000'
    expect "pkg $when the audit trail finds no event of an agent, and says of each event from before the kind of its actor, a person's for the Admin from before, none for what the system did, and that it was for nobody" \
        "$made $status $(json 'sorted({str(e["actor_kind"]) for e in d["items"] if e["actor_name"] == "upgrade-admin"})') $(json 'sorted({str(e["actor_kind"]) for e in d["items"] if e["actor_hid"] is None})') $(json 'sorted({str(e["for_hid"]) + "/" + str(e["for_name"]) for e in d["items"]})')" \
        '200 0 200 ["person"] ["None"] ["None/None"]'
}

# What is asked of what was carried over: each user from before signs in, or is refused,
# as it did, and each token is taken or refused as it was. Then what 0.9.17 is for, on
# those users: a service account from before is not made an agent; an agent answerable
# to the person from before acts with Inventory, for that person, in the audit trail; an
# agent answerable to the disabled person from before has its token refused, and none is
# made answerable to the retired one or to a service account; and the person from
# before is retired with the agent handed to the one who holds View-only through the
# group, whose role it is then held to. They leave the users as a site would have them
# after it.
after_0018() {
    local admin=$token made code=0 agent secret off_agent off_secret vendor rv
    [ -n "$noted_0018" ] || return 0

    expect "pkg each user from before signs in, or is refused, as it was with $previous_version: the persons who hold a role sign in and hold it, the disabled and the retired one are refused; and each token is taken with its role, or refused for want of one, as it was" \
        "$(signs_0018)" "$signed_before_0018"

    # A service account from before stays one: its kind is not changed.
    api GET "/users/${users_0018[robot]}"
    api PATCH "/users/${users_0018[robot]}" "{\"row_version\": $(json_field row_version), \"kind\": \"agent\"}"
    made="$status $(json '[e["field"] for e in d["errors"]]')"
    api GET "/users/${users_0018[robot]}"
    expect "pkg after the upgrade, the service account from before is not made an agent: its kind is set when the account is made, a 422 on kind, and it is a service still" \
        "$made $(json_field kind)" '422 ["kind"] service'

    # An agent answerable to the person from before, with Inventory and a token.
    api POST /users "{\"username\": \"upgrade-18-agent\", \"kind\": \"agent\", \"answerable_hid\": \"${users_0018[person]}\", \"role\": \"inventory\"}"
    made="$status $(json '[d["user"]["kind"], d["user"]["answerable"]["username"], d["user"]["role_in_force"]]')"
    agent=$(json 'd["user"]["hid"]')
    api POST "/users/$agent/service-tokens" '{"name": "upgrade 0018 agent"}'
    made="$made $status"
    secret=$(json_field secret)
    token=$secret
    api POST /vendors '{"name": "Upgrade Agent Networks"}'
    made="$made $status"
    vendor=$(json_field hid)
    token=$admin
    api GET "/audit-events?for_hid=${users_0018[person]}&limit=1000"
    made="$made $status $(json '[[e["record_hid"] == "'"$vendor"'", e["actor_name"], e["actor_kind"], e["for_name"]] for e in d["items"]]')"
    api GET "/users/${users_0018[person]}"
    expect "S61 after the upgrade, an agent is made answerable to the person from before who holds Inventory, and holds Inventory; its token makes a vendor, and the event is the agent's, for that person; and the person's page lists the agent" \
        "$made $(json '[a["username"] for a in d["agents"]]')" \
        '201 ["agent", "upgrade-18-person", "inventory"] 201 201 200 [[true, "upgrade-18-agent", "agent", "upgrade-18-person"]] ["upgrade-18-agent"]'

    # By hirdir admin: an agent answerable to the disabled person from before, whose
    # tokens are refused; and none answerable to the retired one or to a service account.
    inside hirdir admin create-user upgrade-18-off-agent --kind agent --for upgrade-18-off --role viewer >"$work/create-user.log" 2>&1 || code=$?
    made="$code $(matches '^created upgrade-18-off-agent, an agent answerable to upgrade-18-off, with the viewer role$' "$work/create-user.log") $(matches "^upgrade-18-off-agent's tokens are refused while upgrade-18-off is disabled$" "$work/create-user.log")"
    api GET '/users?q=upgrade-18-off-agent'
    off_agent=$(json '"".join(u["hid"] for u in d["items"])')
    api POST "/users/$off_agent/service-tokens" '{"name": "upgrade 0018 paused"}'
    made="$made $status"
    off_secret=$(json_field secret)
    token=$off_secret
    api GET /auth/me
    made="$made $status $(json_field detail)"
    token=$admin
    code=0
    inside hirdir admin create-user upgrade-18-never --kind agent --for upgrade-18-left --role viewer >"$work/create-user.log" 2>&1 || code=$?
    made="$made | $code $(matches 'is retired' "$work/create-user.log")"
    code=0
    inside hirdir admin create-user upgrade-18-never --kind agent --for upgrade-18-robot --role viewer >"$work/create-user.log" 2>&1 || code=$?
    made="$made $code"
    api GET '/users?q=upgrade-18-never&retired=yes'
    expect "S61 after the upgrade, hirdir admin create-user --kind agent --for the disabled person from before makes the agent, and says that its tokens are refused while that person is disabled; its token is refused, a 401 that says so; and no agent is made answerable to the retired person from before or to a service account, each exit 4" \
        "$made $(json_field total)" \
        "0 1 1 201 401 the token is not accepted: the agent upgrade-18-off-agent is answerable to upgrade-18-off, who is disabled | 4 1 4 0"

    # The person from before is retired: saying nothing of the agent is refused, and the
    # agent is handed to the person who holds View-only through the group.
    api GET "/users/${users_0018[person]}"
    rv=$(json_field row_version)
    api POST "/users/${users_0018[person]}/retire" "{\"row_version\": $rv, \"linked\": {\"contact\": \"keep\"}}"
    made="$status $(json '[[e["field"] for e in d["errors"]], [r["label"] for r in d.get("depends_on", [])]]')"
    api POST "/users/${users_0018[person]}/retire" "{\"row_version\": $rv, \"linked\": {\"contact\": \"keep\", \"agents\": [{\"hid\": \"$agent\", \"action\": \"hand_over\", \"user_hid\": \"${users_0018[grouped]}\"}]}}"
    made="$made $status $(json_field record_status)"
    api GET "/users/$agent"
    made="$made $(json '[d["answerable"]["username"], d["role"], d["role_in_force"], d["role_capped_by"]]')"
    token=$secret
    api GET "/vendors/$vendor"
    api PATCH "/vendors/$vendor" "{\"row_version\": $(json_field row_version), \"notes\": \"Never written\"}"
    made="$made $status"
    token=$admin
    api GET "/users/${users_0018[grouped]}"
    expect "S61 after the upgrade, the person from before is retired: saying nothing of the agent is a 409 on linked.agents that names it; handing it to the person from before who holds View-only through the group, the person is retired, the agent is answerable to the other, and is held to View-only, the other's role: its change is refused, a 403; and the other's page lists it" \
        "$made $(json '[a["username"] for a in d["agents"]]')" \
        '409 [["linked.agents"], ["upgrade-18-agent"]] 200 retired ["upgrade-18-grouped", "inventory", "viewer", "person_role"] 403 ["upgrade-18-agent"]'
}
