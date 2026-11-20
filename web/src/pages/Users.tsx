import { type FormEvent, Fragment, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { ColourPicker, useColours } from "../components/ColourPicker";
import {
  CheckField,
  CheckGroupField,
  SelectField,
  TextAreaField,
  TextField,
} from "../components/Field";
import { GapLinks } from "../components/GapLinks";
import { OperatorMark } from "../components/Operator";
import { Pager, toOffset } from "../components/Pager";
import { PersonChooser } from "../components/Person";
import { Notice, Problem } from "../components/Problem";
import { SecretBox } from "../components/SecretBox";
import { AdminNav } from "../components/Shell";
import { SortTh } from "../components/SortTh";
import { Time } from "../components/Time";
import { ValueLink } from "../components/ValueLink";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import {
  briefMark,
  type FollowedLabel,
  followedLabel,
  followUsername,
  groupGrants,
  NEW_USER_FIELDS,
  newUserBody,
  newUserErrors,
  queryOf,
  typeLabel,
  USERS_GAPS,
  type UsersGap,
  usersAddress,
  usersGapOf,
  usersGapQuery,
} from "../lib/onboarding";
import { markOf } from "../lib/operators";
import { type PersonChoice, personChoice } from "../lib/people";
import { ROLES, roleLabel } from "../lib/roles";
import { USERS_SORT } from "../lib/tableSorts";
import { useServerSort } from "../lib/useServerSort";

const PAGE = 50;

type Created = Schemas["UserCreated"];
type User = Schemas["UserOut"];

/** Admin → Users: the list, the search box, and the form for a new user. */
export function Users() {
  useTitle("Users");
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const offset = toOffset(params.get("offset"));
  // 0.9.13: the gap the list is narrowed to, kept in the address, so that a link to it
  // can be sent to a colleague (P-280).
  const gap = usersGapOf(params);
  const [search, setSearch] = useState(q);
  const [adding, setAdding] = useState(false);
  const [created, setCreated] = useState<Created | null>(null);
  // The server pages this list and sorts it, over every user and not the page on show:
  // a header asks for the list in its order, from the first page.
  const sort = useServerSort<User>({
    fields: USERS_SORT,
    onChange: () => {
      if (offset > 0) show({ q, offset: 0, gap });
    },
  });
  const users = sort.held(
    useLoad(`users ${offset} ${q} ${gap} ${sort.param ?? ""}`, (signal) =>
      api.request("get", "/api/v1/users", {
        query: {
          q,
          ...usersGapQuery(gap),
          ...sort.query,
          limit: PAGE,
          offset,
        },
        signal,
      }),
    ),
  );
  const holdsAll = users.data ? users.data.total === users.data.items.length : false;

  function show(next: { q: string; offset: number; gap: UsersGap }) {
    setParams(usersAddress(next.q, next.gap, next.offset));
  }

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    show({ q: search.trim(), offset: 0, gap });
  }

  return (
    <>
      <AdminNav />
      <h1>Users</h1>

      {created && (
        <CreatedUser
          created={created}
          onDone={() => {
            setCreated(null);
          }}
        />
      )}

      <div className="toolbar">
        <form onSubmit={submitSearch} className="inline">
          <TextField
            label="Search users"
            name="q"
            type="search"
            value={search}
            onChange={setSearch}
            hint="Part of a username or of the name of its contact"
          />
          <button type="submit">Search</button>
        </form>
        {!adding && (
          <button
            type="button"
            className="primary"
            onClick={() => {
              setCreated(null);
              setAdding(true);
            }}
          >
            New user
          </button>
        )}
      </div>

      {adding && (
        <NewUser
          onCancel={() => setAdding(false)}
          onCreated={(answer) => {
            setAdding(false);
            setCreated(answer);
            users.reload();
          }}
        />
      )}

      {/* 0.9.13: the gaps, each one press away and an address of its own (P-280). */}
      <GapLinks
        label="Show users"
        links={USERS_GAPS.map((one) => ({
          text: one.label,
          to: `/admin/users${queryOf(usersAddress(q, one.value, 0))}`,
          current: one.value === gap,
        }))}
      />
      <Problem error={users.error} />
      {users.loading && !users.data && <p role="status">Loading…</p>}
      {users.data && (
        <>
          <p className="hint">
            A user is the part of a person who signs in. Its name, its email and its numbers are
            those of its contact, and are changed on the contact, or on the page of the user. The
            operators are the labels the person works equipment under.
          </p>
          <div className="scroll">
            <table data-testid="users" data-gap={gap || undefined}>
              <caption className="visually-hidden">
                Users, each with the contact it is and the operators it works as
                {gap === "no-contact" && ": those with no contact"}
                {gap === "no-operator" && ": those with no operator"}
              </caption>
              <thead>
                <tr>
                  <SortTh sort={sort.header("username", holdsAll)} column="username">
                    Username
                  </SortTh>
                  <SortTh sort={sort.header("display_name", holdsAll)} column="display_name">
                    Name
                  </SortTh>
                  <th scope="col">Email</th>
                  <th scope="col">Phone</th>
                  <th scope="col">Second phone</th>
                  <SortTh sort={sort.header("operators", holdsAll)} column="operators">
                    Operators
                  </SortTh>
                  <SortTh sort={sort.header("role", holdsAll)} column="role">
                    Role
                  </SortTh>
                  <SortTh sort={sort.header("groups", holdsAll)} column="groups">
                    Groups
                  </SortTh>
                  <SortTh sort={sort.header("kind", holdsAll)} column="kind">
                    Kind
                  </SortTh>
                  <SortTh sort={sort.header("state", holdsAll)} column="state">
                    State
                  </SortTh>
                  <SortTh sort={sort.header("last_sign_in", holdsAll)} column="last_sign_in">
                    Last sign-in
                  </SortTh>
                  <SortTh sort={sort.header("notes", holdsAll)} column="notes">
                    Notes
                  </SortTh>
                </tr>
              </thead>
              <tbody>
                {sort.arrange(users.data.items, holdsAll).map((user) => (
                  <tr
                    key={user.hid}
                    className={user.disabled ? "dim" : undefined}
                    data-user={user.username}
                  >
                    <th scope="row">
                      <Link to={`/admin/users/${encodeURIComponent(user.hid)}`}>
                        {user.username}
                      </Link>
                    </th>
                    {/* 0.9.3: the name, email and numbers of its contact (P-172). 0.9.13: the
                        contact as a link to its page, or no contact said plainly (P-280). */}
                    <td data-testid="user-name">
                      {user.contact ? (
                        <>
                          <Link to={`/contacts/${encodeURIComponent(user.contact.hid)}`}>
                            {user.display_name}
                          </Link>
                          {user.contact.record_status === "retired" && (
                            <span className="badge">Retired</span>
                          )}
                        </>
                      ) : user.is_service_account ? (
                        <span className="muted">Service account</span>
                      ) : (
                        <span className="people-gap">no contact</span>
                      )}
                    </td>
                    <td data-testid="user-email">{user.email}</td>
                    <td data-testid="user-phone">{user.contact?.phone}</td>
                    <td data-testid="user-phone2">{user.contact?.phone2}</td>
                    <td data-testid="user-operators">
                      <UserOperators user={user} />
                    </td>
                    <td>
                      {user.role ? roleLabel(user.role) : <span className="muted">none</span>}
                    </td>
                    <td>
                      {user.groups.map((group, index) => (
                        <Fragment key={group.hid}>
                          {index > 0 && ", "}
                          <ValueLink kind="user_group" hid={group.hid} admin>
                            {group.name}
                          </ValueLink>
                        </Fragment>
                      ))}
                    </td>
                    <td>{user.is_service_account ? "Service" : "Person"}</td>
                    <td>{user.disabled ? "Disabled" : "Active"}</td>
                    <td>
                      <Time at={user.last_sign_in_at} />
                    </td>
                    <td className="user-notes" data-testid="user-notes">
                      {user.notes}
                    </td>
                  </tr>
                ))}
                {users.data.items.length === 0 && (
                  <tr>
                    <td colSpan={12} className="muted">
                      {noUsers(q, gap)}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Pager
            total={users.data.total}
            limit={PAGE}
            offset={offset}
            noun="users"
            onChange={(next) => show({ q, offset: next, gap })}
          />
        </>
      )}
    </>
  );
}

/** What the list says when it holds nobody: of the search, of the gap, or of the whole. */
function noUsers(q: string, gap: UsersGap): string {
  if (q) return "No user matches the search.";
  if (gap === "no-contact") return "Every user who is a person has a contact.";
  if (gap === "no-operator") return "Every user who is a person works as an operator.";
  return "There are no users.";
}

/**
 * 0.9.13: the operators a user works as, each its label in its colour and a link to its
 * page, or no operator said plainly; a service account is no person, and has none to
 * have (P-280).
 */
function UserOperators({ user }: { user: User }) {
  if (user.operators.length > 0) {
    return (
      <span className="people-marks">
        {user.operators.map((operator) => (
          <OperatorMark key={operator.hid} mark={briefMark(operator)} />
        ))}
      </span>
    );
  }
  if (user.is_service_account) return <span className="muted">—</span>;
  return <span className="people-gap">no operator</span>;
}

function CreatedUser({ created, onDone }: { created: Created; onDone: () => void }) {
  const { user, access_code } = created;
  const made = <MadeWithUser created={created} />;
  if (access_code === null) {
    return (
      <>
        <Notice
          text={`The service account ${user.username} was created. It has no access code: open it to create a token.`}
        />
        {made}
      </>
    );
  }
  return (
    <>
      <SecretBox title={`Access code for ${user.username}`} secret={access_code} onDone={onDone} />
      {made}
    </>
  );
}

/** 0.9.13: what one Create made, each a link to its page: the user, its contact, its operator. */
function MadeWithUser({ created }: { created: Created }) {
  const { user } = created;
  const mark = markOf(created.operator);
  return (
    <p data-testid="user-made">
      Made: the user{" "}
      <Link to={`/admin/users/${encodeURIComponent(user.hid)}`}>{user.username}</Link>
      {user.contact && (
        <>
          {mark ? ", " : " and "}the contact{" "}
          <Link to={`/contacts/${encodeURIComponent(user.contact.hid)}`}>{user.contact.name}</Link>
        </>
      )}
      {mark && (
        <>
          {" "}
          and the operator <OperatorMark mark={mark} />
        </>
      )}
      .
    </p>
  );
}

interface NewUserProps {
  onCancel: () => void;
  onCreated: (created: Created) => void;
}

/**
 * A new user. 0.9.3: the person is a contact, a new one made with the user, or one there
 * is that is no other user's; a service account, which is no person, has none (P-172).
 * The username is what the person signs in with, and an Admin can change it later
 * (P-173). 0.9.13: one Create makes what a new person needs (P-282, P-283): Also a
 * contact and Also an operator are ticked from the start, the operator's label follows
 * the username until it is typed over and its colour is the next that no operator has,
 * with the role, the groups and the notes on the same form. Unticking the contact
 * unticks the operator, which needs one; ticking the operator ticks the contact.
 */
function NewUser({ onCancel, onCreated }: NewUserProps) {
  const [username, setUsername] = useState("");
  const [service, setService] = useState(false);
  const [alsoContact, setAlsoContact] = useState(true);
  const [person, setPerson] = useState<PersonChoice>(() => personChoice("new"));
  const [alsoOperator, setAlsoOperator] = useState(true);
  const [label, setLabel] = useState<FollowedLabel>(() => followedLabel(""));
  // The colour as chosen, or null until one is: it then shows the next no operator has.
  const [chosenColour, setChosenColour] = useState<string | null>(null);
  const [role, setRole] = useState("");
  const [groupHids, setGroupHids] = useState<string[]>([]);
  const [notes, setNotes] = useState("");
  const [accessCode, setAccessCode] = useState("");
  const [found, setFound] = useState<Record<string, string>>({});
  const groups = useLoad("user-groups", (signal) =>
    api.request("get", "/api/v1/user-groups", { signal }),
  );
  // Read afresh for the form: another operator may have taken a colour since the page was.
  const colours = useColours(true);
  // Until one is chosen the colour shows the next no operator has, and is left to the
  // server, which gives the same, and gives it too where the colours have not yet come.
  const colour = chosenColour ?? colours.data?.next_for_operators ?? "";
  const action = useAction();
  // What the server refused is said beside the field it names.
  const fields: Readonly<Record<string, string | undefined>> = {
    ...newUserErrors(action.error?.fields ?? {}),
    ...found,
  };

  async function submit(event: FormEvent) {
    event.preventDefault();
    const read = newUserBody({
      username,
      service,
      alsoContact,
      person,
      alsoOperator,
      label: label.label,
      colour: chosenColour,
      role,
      groupHids,
      notes,
      accessCode,
    });
    if (!read.ok) {
      action.clear();
      setFound({ [read.field]: read.error });
      return;
    }
    setFound({});
    const result = await action.run(() =>
      api.request("post", "/api/v1/users", { body: read.body }),
    );
    if (result.ok) onCreated(result.value);
  }

  return (
    <section className="panel" aria-labelledby="new-user">
      <h2 id="new-user">New user</h2>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={NEW_USER_FIELDS} />
        <TextField
          label="Username"
          name="username"
          value={username}
          onChange={(typed) => {
            setUsername(typed);
            setLabel((was) => followUsername(was, typed));
          }}
          required
          maxLength={64}
          autoComplete="off"
          hint="What the person signs in with: 1 to 64 letters, digits, dots, hyphens and underscores. An Admin can change it later."
          error={fields.username}
        />
        <CheckField
          label="Service account"
          name="is_service_account"
          checked={service}
          onChange={setService}
          hint="For automation. It cannot sign in with an access code: it holds tokens. It is no person, and has no contact and no operator."
          error={fields.is_service_account}
        />
        {!service && (
          <div className="onboard-part" data-testid="new-user-contact">
            <CheckField
              label="Also a contact"
              name="also_contact"
              checked={alsoContact}
              onChange={(ticked) => {
                setFound({});
                setAlsoContact(ticked);
                // The operator stands for the contact: without one there is none.
                if (!ticked) setAlsoOperator(false);
              }}
              hint="The person, whose name, email and numbers the user shows. Unticked, the user is shown by its username until it is given a contact."
            />
            {alsoContact && (
              <PersonChooser
                legend="The person"
                name="new-user"
                ways={["new", "contact"]}
                wayLabels={{ new: "A new contact", contact: "A contact there is" }}
                choice={person}
                onChange={(next) => {
                  setFound({});
                  setPerson(next);
                }}
                errors={fields}
                organization
                hint="A contact is one user's at most."
                disabled={action.busy}
              />
            )}
          </div>
        )}
        {!service && (
          <div className="onboard-part" data-testid="new-user-operator">
            <CheckField
              label="Also an operator"
              name="also_operator"
              checked={alsoOperator}
              onChange={(ticked) => {
                setAlsoOperator(ticked);
                // An operator stands for a contact, made or chosen with it.
                if (ticked) setAlsoContact(true);
              }}
              hint="The label the person works equipment under, which items, groups and places are given. Unticked for somebody who works no equipment."
              error={fields.operator}
            />
            {alsoOperator && (
              <div className="fields onboard-operator">
                <TextField
                  label="Label"
                  name="operator_label"
                  value={label.label}
                  onChange={(typed) => setLabel((was) => typeLabel(was, typed))}
                  maxLength={40}
                  autoComplete="off"
                  hint="The username until it is typed over: at most 40 characters, with no semicolon. It is what lists and reports show."
                  error={fields.label}
                  disabled={action.busy}
                />
                <ColourPicker
                  id="new-user-colour"
                  label="Colour"
                  name="operator_colour"
                  value={colour}
                  onChange={setChosenColour}
                  sample={label.label.trim() || username.trim()}
                  hint="The next colour that no operator has, unless another is chosen. Blank is no colour."
                  error={fields.colour}
                  disabled={action.busy}
                />
              </div>
            )}
          </div>
        )}
        <SelectField label="Role" name="role" value={role} onChange={setRole} error={fields.role}>
          <option value="">No role</option>
          {ROLES.map((name) => (
            <option key={name} value={name}>
              {roleLabel(name)}
            </option>
          ))}
        </SelectField>
        <Problem error={groups.error} />
        <CheckGroupField
          label="Groups"
          name="group_hids"
          options={(groups.data ?? []).map((group) => ({
            value: group.hid,
            label: `${group.name} (${groupGrants(group.roles)})`,
          }))}
          value={groupHids}
          onChange={setGroupHids}
          empty={groups.data ? "There are no groups." : "Loading…"}
          hint="The user is put in each group ticked, and holds the roles it grants."
          error={fields.group_hids}
          disabled={action.busy}
        />
        <TextAreaField
          label="Notes"
          name="notes"
          value={notes}
          onChange={setNotes}
          maxLength={10000}
          hint="What the account is for, who asked for it, when it is to end."
          error={fields.notes}
          disabled={action.busy}
        />
        {!service && (
          <TextField
            label="Access code"
            name="access_code"
            value={accessCode}
            onChange={setAccessCode}
            maxLength={200}
            autoComplete="off"
            hint="Leave empty to have one generated"
            error={fields.access_code}
          />
        )}
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy}>
            Create user
          </button>
          <button type="button" onClick={onCancel} disabled={action.busy}>
            Cancel
          </button>
        </p>
      </form>
    </section>
  );
}
