import { type FormEvent, useState } from "react";
import { Link, useParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { ConfirmButton } from "../components/ConfirmButton";
import { CheckField, TextAreaField, TextField } from "../components/Field";
import { GenerateCode } from "../components/GenerateCode";
import { GroupBoxes } from "../components/GroupBoxes";
import { MakeOperator } from "../components/MakeOperator";
import { OperatorMark } from "../components/Operator";
import { ContactChanges, PersonChooser } from "../components/Person";
import { PersonChain } from "../components/PersonChain";
import { PersonUserField } from "../components/PersonUserField";
import { Notice, Problem } from "../components/Problem";
import { BringBackUser, RetirePerson } from "../components/RetirePerson";
import { SecretBox } from "../components/SecretBox";
import { AdminNav } from "../components/Shell";
import { SortTh } from "../components/SortTh";
import { Time } from "../components/Time";
import {
  cappedWords,
  holdsTokens,
  kindName,
  noRoleWords,
  sourceWords,
  tokenRefused,
} from "../lib/accounts";
import { appZone, momentIn } from "../lib/format";
import { useAction, useLoad, useReloadOn, useTitle } from "../lib/hooks";
import { userState } from "../lib/linked";
import { useSettings } from "../lib/lists";
import { accessCodeHint, behindOperator, briefMark, leastCodeLength } from "../lib/onboarding";
import type { Option } from "../lib/patch";
import { type PersonChoice, personChoice, personLabel, readPerson } from "../lib/people";
import type { BroughtBack } from "../lib/person";
import { roleLabel } from "../lib/roles";
import { dateValue } from "../lib/sort";
import { useSorting } from "../lib/useSorting";

type User = Schemas["UserOut"];
type Token = Schemas["ServiceTokenOut"];

/**
 * Admin → Users → one user: details, the person it is, access code, sessions and service
 * tokens. 0.9.3: the person is a contact, whose name, email and numbers the user shows
 * and this page changes on the contact (P-172), and the username is changed here (P-173).
 * 0.9.14: an account is retired here, with what is said of its contact and its labels,
 * and brought back; a retired account's page offers only what the server changes of it,
 * its username, its notes and its contact taken away, and says why (P-291, P-292, P-296).
 */
export function UserDetail() {
  const { hid = "" } = useParams();
  // The page is of one account: what it holds of one, as a new access code shown once,
  // is never on show for another, whichever way the address came to change (review 1).
  return <UserPage key={hid} hid={hid} />;
}

function UserPage({ hid }: { hid: string }) {
  const auth = useAuth();
  const user = useLoad(`user ${hid}`, (signal) =>
    api.request("get", "/api/v1/users/{hid}", { path: { hid }, signal }),
  );
  useTitle(user.data ? `User ${user.data.username}` : "User");
  // What a retirement did, and the account brought back with its new code, shown once.
  const [done, setDone] = useState("");
  const [back, setBack] = useState<BroughtBack | null>(null);
  const retired = user.data ? userState(user.data) === "Retired" : false;

  return (
    <>
      <AdminNav />
      <p className="crumbs">
        <Link to="/admin/users">Users</Link>
      </p>
      <h1>
        {user.data ? user.data.username : "User"}
        {retired && <span className="badge">Retired</span>}
      </h1>
      <Problem error={user.error} />
      <Notice text={done} />
      {back && <BroughtBackUser back={back} onDone={() => setBack(null)} />}
      {user.loading && !user.data && <p role="status">Loading…</p>}
      {user.data && (
        <>
          {/* 0.9.14: the person it belongs to, operator, contact, user (P-291). */}
          <PersonChain kind="user" hid={user.data.hid} turn={user.data.row_version} />
          <Facts
            user={user.data}
            onRoleChanged={() => {
              user.reload();
              // The reader's own role may be what changed.
              if (auth.user.hid === hid) auth.refresh();
            }}
          />
          {retired && (
            <p className="alert" data-testid="user-retired">
              This account is retired: it signs in with nothing, is in no group and holds no role.
              Its username, its notes and its contact taken away are all that is changed of it. An
              access code, a role, a group, a token and another contact are given once it is brought
              back.
            </p>
          )}
          <Details
            key={`${user.data.hid} ${user.data.row_version}`}
            user={user.data}
            reload={user.reload}
          />
          {/* 0.9.13: its groups, a box to each, changed at once (P-282). */}
          {!retired && (
            <GroupBoxes
              key={`groups ${user.data.hid}`}
              user={user.data}
              onChanged={() => {
                user.refresh();
                // A group can carry a role, the reader's own included.
                if (auth.user.hid === hid) auth.refresh();
              }}
            />
          )}
          {/* 0.9.17: an agent's person, and the agent handed to another (P-316). */}
          {user.data.kind === "agent" && !retired && (
            // Not keyed on the version: the words of a hand-over outlast the page read again
            // (review 2).
            <Answerable key={`answerable ${user.data.hid}`} user={user.data} reload={user.reload} />
          )}
          {user.data.kind === "person" && (
            <Person
              key={`person ${user.data.hid} ${user.data.row_version}`}
              user={user.data}
              reload={user.reload}
            />
          )}
          {!retired && user.data.kind === "person" && (
            <AccessCode user={user.data} reload={user.reload} />
          )}
          {!retired && <Sessions user={user.data} reload={user.reload} />}
          {holdsTokens(user.data.kind) && <Tokens user={user.data} refresh={user.refresh} />}
          <RetireUser
            key={`retire ${user.data.hid} ${user.data.row_version}`}
            user={user.data}
            onRetired={(text) => {
              // An Admin who retires their own account is signed out by it.
              if (auth.user.hid === hid) {
                auth.signOut();
                return;
              }
              setBack(null);
              setDone(text);
              user.reload();
            }}
            onBroughtBack={(answer) => {
              setDone("");
              setBack(answer);
              user.reload();
            }}
          />
        </>
      )}
    </>
  );
}

/** The account brought back: its new access code, shown once, and what it is without. */
function BroughtBackUser({ back, onDone }: { back: BroughtBack; onDone: () => void }) {
  const { user, access_code } = back;
  // 0.9.15: with the role chosen in the confirmation (P-299).
  const holding = user.role ? `the role ${roleLabel(user.role)}` : "no role";
  if (access_code === null) {
    const what = user.kind === "agent" ? "agent" : "service account";
    const whose = user.answerable ? `, answerable to ${user.answerable.username},` : "";
    return (
      <Notice
        text={`The ${what} ${user.username} is active again${whose} with ${holding}. It has no group and no token: give them below.`}
      />
    );
  }
  return (
    <SecretBox
      title={`New access code for ${user.username}`}
      secret={access_code}
      note={`${user.username} is active again, with ${holding} and no group: give groups below.`}
      onDone={onDone}
    />
  );
}

interface RetireUserProps {
  user: User;
  onRetired: (text: string) => void;
  onBroughtBack: (answer: BroughtBack) => void;
}

/**
 * 0.9.14: retire an account, which is other than disabling it, or bring a retired one
 * back (P-292, P-296). The contact and the labels of the person are retired with it, or
 * parted from it, in the one confirmation (P-291).
 */
function RetireUser({ user, onRetired, onBroughtBack }: RetireUserProps) {
  const auth = useAuth();
  const own = auth.user.hid === user.hid;
  const retired = userState(user) === "Retired";
  return (
    <section aria-labelledby="retire">
      <h2 id="retire">{retired ? "Retired" : "Retire"}</h2>
      {retired ? (
        <>
          <p>
            Brought back, the account is active again with a new access code, shown once, the role
            chosen in the confirmation and no group. Where its contact is retired, the two are
            brought back together.
          </p>
          <div className="actions">
            <BringBackUser user={user} onBroughtBack={onBroughtBack} />
          </div>
        </>
      ) : (
        <>
          <p>
            For somebody who has left. A retired account signs in with nothing, leaves its groups
            and its role, and keeps its username. The list of users, every picker and the
            users&apos; file leave it out until the retired are asked for. To keep somebody out for
            now, disable the account instead.
          </p>
          <div className="actions">
            <RetirePerson
              on={{ kind: "user", hid: user.hid }}
              rowVersion={user.row_version}
              label="Retire account"
              title={`Retire ${user.username}?`}
              note={
                own
                  ? "This is your own account: you are signed out at once, and cannot sign in again."
                  : undefined
              }
              onRetired={onRetired}
            >
              <p>
                {user.username} signs in no longer, and leaves its groups and its role. An Admin can
                bring the account back, with a new access code.
              </p>
            </RetirePerson>
          </div>
        </>
      )}
    </section>
  );
}

function Facts({ user, onRoleChanged }: { user: User; onRoleChanged: () => void }) {
  const capped = cappedWords(user);
  return (
    <dl className="facts" data-testid="user-facts">
      <dt>Username</dt>
      <dd className="mono">{user.username}</dd>
      <dt>Kind</dt>
      <dd data-testid="user-kind">{kindName(user.kind)}</dd>
      {/* 0.9.17: the person an agent is answerable to, a link (P-316). */}
      {user.kind === "agent" && (
        <>
          <dt>Answerable to</dt>
          <dd data-testid="user-answerable">
            {user.answerable ? (
              <>
                <Link to={`/admin/users/${encodeURIComponent(user.answerable.hid)}`}>
                  {user.answerable.name}
                </Link>
                {user.answerable.name !== user.answerable.username && (
                  <span className="muted"> ({user.answerable.username})</span>
                )}
                {user.answerable.record_status === "retired" && (
                  <span className="badge">Retired</span>
                )}
              </>
            ) : (
              <span className="muted">—</span>
            )}
          </dd>
        </>
      )}
      <dt>State</dt>
      <dd data-testid="user-state">{userState(user)}</dd>
      <dt>Role</dt>
      <dd data-testid="user-role">
        {roleLabel(user.role)}
        {/* 0.9.17: of an agent, the role it is held to and why (P-316). */}
        {capped && <span data-testid="user-role-capped"> · {capped}</span>}{" "}
        <Link to="/admin/roles">(role grants)</Link>
        {/* 0.9.17: each role it holds and where it comes from (P-307). */}
        <RoleSources user={user} onChanged={onRoleChanged} />
      </dd>
      {/* 0.9.17: the agents answerable to a person, each a link (P-316). */}
      {user.kind === "person" && (
        <>
          <dt>Agents</dt>
          <dd data-testid="user-agents">
            {user.agents.length === 0 && <span className="muted">—</span>}
            {user.agents.map((agent, index) => (
              <span key={agent.hid}>
                {index > 0 && ", "}
                <Link to={`/admin/users/${encodeURIComponent(agent.hid)}`}>{agent.username}</Link>
                {agent.record_status === "retired" && <span className="badge">Retired</span>}
              </span>
            ))}
          </dd>
        </>
      )}
      <dt>Groups</dt>
      <dd data-testid="user-groups-fact">
        {user.groups.length === 0 && <span className="muted">—</span>}
        {user.groups.map((group, index) => (
          <span key={group.hid}>
            {index > 0 && ", "}
            <Link to={`/admin/groups/${encodeURIComponent(group.hid)}`}>{group.name}</Link>
          </span>
        ))}
      </dd>
      {/* 0.9.13: the operators it works as, as links, and one made in one press where it
          has a contact and is behind none (P-280, P-284). */}
      {user.kind === "person" && (
        <>
          <dt>Operators</dt>
          <dd data-testid="user-operators">
            {user.operators.length > 0 && (
              <span className="people-marks">
                {user.operators.map((operator) => (
                  <OperatorMark key={operator.hid} mark={briefMark(operator, user.contact)} />
                ))}
              </span>
            )}
            {user.operators.length === 0 && <span className="people-gap">no operator</span>}
            {/* A retired contact stands behind no operator: none is offered for it. */}
            {user.contact?.record_status === "retired" && userState(user) !== "Retired" && (
              <span className="muted" data-testid="contact-retired">
                {" "}
                · its contact,{" "}
                <Link to={`/contacts/${encodeURIComponent(user.contact.hid)}`}>
                  {user.contact.name}
                </Link>
                , is retired: an operator is made once the contact is brought back, or the user is
                given another
              </span>
            )}
            {/* 0.9.14: nor is one made for an account that is retired (P-296). */}
            {user.contact &&
              user.contact.record_status !== "retired" &&
              userState(user) !== "Retired" &&
              !behindOperator(user.operators) && (
                <MakeOperator
                  contactHid={user.contact.hid}
                  label={user.username}
                  who={user.username}
                />
              )}
            {!user.contact && userState(user) !== "Retired" && (
              <span className="muted"> · an operator stands for a contact: give it one first</span>
            )}
          </dd>
        </>
      )}
      <dt>Notes</dt>
      <dd data-testid="user-notes">{user.notes || <span className="muted">—</span>}</dd>
      <dt>Last sign-in</dt>
      <dd>
        <Time at={user.last_sign_in_at} />
      </dd>
      <dt>Created</dt>
      <dd>
        <Time at={user.created_at} />
      </dd>
      <dt>Changed</dt>
      <dd>
        <Time at={user.updated_at} />
      </dd>
    </dl>
  );
}

/**
 * 0.9.17: each role an account holds and where it comes from, of its own or through a
 * group, the group a link (P-307). A grant of its own is revoked here; what the change
 * leaves the account is said before it is made, from where its roles come (P-314).
 */
function RoleSources({ user, onChanged }: { user: User; onChanged: () => void }) {
  const action = useAction();
  if (user.grants.length === 0) return null;

  async function revoke(grant: Schemas["UserGrant"]) {
    const result = await action.run(() =>
      api.request("delete", "/api/v1/role-grants/{hid}", { path: { hid: grant.hid } }),
    );
    if (result.ok) onChanged();
  }

  return (
    <>
      <ul className="role-sources" data-testid="role-sources">
        {user.grants.map((grant) => {
          const leaves = noRoleWords([user], { kind: "revoke", grantHid: grant.hid });
          return (
            <li key={grant.hid} className="role-source" data-grant={grant.hid}>
              {roleLabel(grant.role)},{" "}
              {grant.group ? (
                <>
                  through{" "}
                  <Link to={`/admin/groups/${encodeURIComponent(grant.group.hid)}`}>
                    {grant.group.name}
                  </Link>
                </>
              ) : (
                sourceWords(grant)
              )}
              {!grant.group && (
                <>
                  {" "}
                  <ConfirmButton
                    label={`Revoke ${roleLabel(grant.role)}`}
                    title={`Take ${roleLabel(grant.role)} back from ${user.username}?`}
                    confirmLabel="Revoke role"
                    onConfirm={() => revoke(grant)}
                    disabled={action.busy}
                  >
                    <p>{`${user.username} loses this role at once, unless a group gives it to them.`}</p>
                    {leaves && (
                      <p data-testid="no-role-left">
                        <strong>{leaves}</strong>
                      </p>
                    )}
                  </ConfirmButton>
                </>
              )}
            </li>
          );
        })}
      </ul>
      <Problem error={action.error} />
    </>
  );
}

/**
 * 0.9.17: the person an agent is answerable to, and the agent handed to another person
 * by an Admin (P-316): from then on the agent holds no more than their role.
 */
function Answerable({ user, reload }: { user: User; reload: () => void }) {
  const [chosen, setChosen] = useState("");
  const [name, setName] = useState("");
  const [done, setDone] = useState("");
  const action = useAction();
  const fields = action.error?.fields ?? {};

  async function hand(event: FormEvent) {
    event.preventDefault();
    if (chosen === "") return;
    setDone("");
    const result = await action.run(() =>
      api.request("patch", "/api/v1/users/{hid}", {
        path: { hid: user.hid },
        body: { row_version: user.row_version, answerable_hid: chosen },
      }),
    );
    if (!result.ok) return;
    setDone(`${user.username} is answerable to ${name} from now on.`);
    setChosen("");
    setName("");
    reload();
  }

  return (
    <section aria-labelledby="answerable">
      <h2 id="answerable">Answerable to</h2>
      <p>
        An agent is answerable to a person: it holds no more than their role, read at each of its
        requests, and its tokens are refused while they hold none, are disabled or are retired.
        Handed to another person, it holds no more than theirs from then on.
      </p>
      <Notice text={done} />
      <form onSubmit={hand} className="stack" noValidate>
        <Problem error={action.error} shown={["answerable_hid"]} onReload={reload} />
        <PersonUserField
          label={`Person to hand ${user.username} to`}
          name="answerable_hid"
          value={chosen}
          onChange={setChosen}
          onPicked={(picked) => setName(picked?.name ?? "")}
          blank="Nobody chosen"
          leaveOut={user.answerable ? [user.answerable.hid] : []}
          error={fields.answerable_hid}
          disabled={action.busy}
        />
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || chosen === ""}>
            {chosen && name ? `Hand ${user.username} to ${name}` : "Hand over"}
          </button>
        </p>
      </form>
    </section>
  );
}

/**
 * The username and whether the user may sign in. 0.9.3: an Admin gives a user another
 * username, which the person signs in with from then on; the user is the same record,
 * with its contact, its groups, its roles, its sessions and its tokens (P-173).
 */
function Details({ user, reload }: { user: User; reload: () => void }) {
  const auth = useAuth();
  // 0.9.14: of a retired account only the username and the notes are changed (P-296).
  const retired = userState(user) === "Retired";
  const [username, setUsername] = useState(user.username);
  const [disabled, setDisabled] = useState(user.disabled);
  const [notes, setNotes] = useState(user.notes ?? "");
  const action = useAction();
  const fields = action.error?.fields ?? {};
  const renamed = username.trim() !== user.username;
  const noted = notes.trim() !== (user.notes ?? "");
  const changed = renamed || disabled !== user.disabled || noted;

  async function submit(event: FormEvent) {
    event.preventDefault();
    // Only what changed is sent, with the version this form was filled from.
    const body: Schemas["UserPatch"] = { row_version: user.row_version };
    if (renamed) body.username = username.trim();
    if (disabled !== user.disabled) body.disabled = disabled;
    // 0.9.13: blank clears them (P-281).
    if (noted) body.notes = notes.trim() || null;
    const result = await action.run(() =>
      api.request("patch", "/api/v1/users/{hid}", { path: { hid: user.hid }, body }),
    );
    if (!result.ok) return;
    // An Admin who renames themselves keeps signing in: the header says the new name.
    if (renamed && auth.user.hid === user.hid) auth.refresh();
    reload();
  }

  return (
    <section aria-labelledby="details">
      <h2 id="details">Details</h2>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={["username", "disabled", "notes"]} onReload={reload} />
        <TextField
          label="Username"
          name="username"
          value={username}
          onChange={setUsername}
          required
          maxLength={64}
          autoComplete="off"
          hint={
            retired
              ? "A retired account keeps its username, which no other account takes. Give it another one here to free the name for somebody new."
              : "What the person signs in with: 1 to 64 letters, digits, dots, hyphens and underscores. Another one keeps the sessions; the old one signs nobody in."
          }
          error={fields.username}
        />
        {!retired && (
          <CheckField
            label="Disabled"
            name="disabled"
            checked={disabled}
            onChange={setDisabled}
            hint="A disabled user cannot sign in, and every session they have ends. For somebody who has left, retire the account, below."
            error={fields.disabled}
          />
        )}
        <TextAreaField
          label="Notes"
          name="notes"
          value={notes}
          onChange={setNotes}
          maxLength={10000}
          hint="The account's: what it is for, who asked for it, when it is to end. The person's own are on the contact."
          error={fields.notes}
        />
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || !changed}>
            Save
          </button>
        </p>
      </form>
    </section>
  );
}

/**
 * The person a user is: its contact, with the name, email and numbers the user shows,
 * changed here on the contact; and another contact, a new one, or none.
 */
function Person({ user, reload }: { user: User; reload: () => void }) {
  const contact = user.contact;
  const retired = userState(user) === "Retired";
  const [done, setDone] = useState("");
  return (
    <section aria-labelledby="person">
      <h2 id="person">The person</h2>
      <p className="hint">
        The name, the email and the numbers of a user are those of its contact.{" "}
        {retired
          ? "They are changed on the page of the contact."
          : "Changed here, they are changed on the contact, and so wherever that person is named."}
      </p>
      <Notice text={done} />
      {contact ? (
        <dl className="facts" data-testid="user-person">
          <dt>Contact</dt>
          <dd>
            <Link to={`/contacts/${encodeURIComponent(contact.hid)}`}>{contact.name}</Link>
            {contact.record_status === "retired" && <span className="badge">Retired</span>}
            <span className="muted"> · the user shows what follows from the contact</span>
          </dd>
          <dt>Email</dt>
          <dd data-testid="person-email">{contact.email || <span className="muted">—</span>}</dd>
          <dt>Phone</dt>
          <dd data-testid="person-phone">{contact.phone || <span className="muted">—</span>}</dd>
          <dt>Second phone</dt>
          <dd data-testid="person-phone2">{contact.phone2 || <span className="muted">—</span>}</dd>
        </dl>
      ) : (
        <p className="muted" data-testid="user-person">
          {user.username} has no contact: it is shown by its username until it is given one.
        </p>
      )}
      {contact && !retired && (
        <section aria-labelledby="person-details">
          <h3 id="person-details">Change the name, email and numbers</h3>
          <ContactChanges
            hid={contact.hid}
            fields={["name", "email", "phone", "phone2"]}
            submitLabel="Save on the contact"
            onSaved={() => {
              setDone(`The contact ${contact.name} was saved.`);
              reload();
            }}
          />
        </section>
      )}
      {retired ? (
        contact && <TakeContact user={user} reload={reload} />
      ) : (
        <GiveContact user={user} reload={reload} />
      )}
    </section>
  );
}

/**
 * 0.9.14: all that is changed of the contact of a retired account: it is taken away
 * (P-296), after which the account is brought back by itself, whatever its contact is.
 */
function TakeContact({ user, reload }: { user: User; reload: () => void }) {
  const action = useAction();

  async function take() {
    const result = await action.run(() =>
      api.request("patch", "/api/v1/users/{hid}", {
        path: { hid: user.hid },
        body: { row_version: user.row_version, contact_hid: null },
      }),
    );
    if (result.ok) reload();
  }

  return (
    <section aria-labelledby="take-contact">
      <h3 id="take-contact">Take its contact away</h3>
      <p className="hint">
        A retired account is given no other contact. With its contact taken away, the account is
        brought back by itself, and the contact stays as it is.
      </p>
      <Problem error={action.error} onReload={reload} />
      {/* It asks first (review 8): a retired account is given no contact again. */}
      <div className="actions">
        <ConfirmButton
          label="Take its contact away"
          title={`Take the contact of ${user.username} away?`}
          confirmLabel="Take its contact away"
          onConfirm={take}
          disabled={action.busy}
        >
          <p>
            {user.username} is given no contact again until it is brought back: a retired account is
            given none.{" "}
            {user.contact
              ? `The contact ${user.contact.name} stays as it is, and is no longer this account's.`
              : ""}
          </p>
        </ConfirmButton>
      </div>
    </section>
  );
}

/**
 * Give a user another contact, one there is that is no other user's or a new one made
 * from what is typed, or take its contact away. A new contact is made first, and then
 * given: where the user is not changed, the contact made is kept as the one chosen, so
 * that it is not made twice.
 */
function GiveContact({ user, reload }: { user: User; reload: () => void }) {
  const [choice, setChoice] = useState<PersonChoice>(() => personChoice("contact"));
  const [found, setFound] = useState<Record<string, string>>({});
  // The contact made here, by its name as a search offers it, where the change was not.
  const [made, setMade] = useState<Option | null>(null);
  const action = useAction();
  const fields: Readonly<Record<string, string | undefined>> = {
    ...action.error?.fields,
    ...found,
  };
  const ready = !(choice.way === "none" && user.contact === null);

  async function give(event: FormEvent) {
    event.preventDefault();
    const read = readPerson(choice);
    if (!read.ok) {
      action.clear();
      setFound({ [read.field]: read.error });
      return;
    }
    setFound({});
    setMade(null);
    const result = await action.run(async () => {
      let hid = read.contactHid;
      if (read.person !== null) {
        const contact = await api.request("post", "/api/v1/contacts", {
          body: { ...read.person, record_status: "active" },
        });
        hid = contact.hid;
        // Made: from here on it is the one chosen, whatever becomes of the change.
        setChoice(personChoice("contact", hid));
        setMade({ value: contact.hid, label: personLabel(contact) });
      }
      return api.request("patch", "/api/v1/users/{hid}", {
        path: { hid: user.hid },
        body: { row_version: user.row_version, contact_hid: hid },
      });
    });
    if (result.ok) reload();
  }

  return (
    <section aria-labelledby="give-contact">
      <h3 id="give-contact">{user.contact ? "Another contact, or none" : "Give it a contact"}</h3>
      <form onSubmit={give} className="stack" noValidate>
        <Problem
          error={action.error}
          shown={["contact_hid", "name", "email", "organization", "phone", "phone2"]}
          onReload={reload}
        />
        {made && action.error && (
          <p className="hint" data-testid="contact-made">
            The contact {made.label} was made, and is chosen below: give it again once the problem
            is put right.
          </p>
        )}
        <PersonChooser
          legend={`The contact ${user.username} is`}
          name="give"
          ways={user.contact ? ["contact", "new", "none"] : ["contact", "new"]}
          wayLabels={{ contact: "A contact there is", new: "A new contact", none: "None" }}
          choice={choice}
          onChange={(next) => {
            setFound({});
            setChoice(next);
          }}
          errors={fields}
          organization
          known={made ? [made] : []}
          hint="A contact is one user's at most, and a retired one is not given."
          disabled={action.busy}
        />
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || !ready}>
            {choice.way === "none" ? "Take its contact away" : "Give it this contact"}
          </button>
        </p>
      </form>
    </section>
  );
}

function AccessCode({ user, reload }: { user: User; reload: () => void }) {
  const auth = useAuth();
  const own = auth.user.hid === user.hid;
  const [wanted, setWanted] = useState("");
  const [code, setCode] = useState<string | null>(null);
  const action = useAction();
  // 0.9.14: the least length of a code that is typed, said under its field (P-295).
  const settings = useSettings();

  async function reset() {
    setCode(null);
    const body: Schemas["AccessCodeSet"] = wanted === "" ? {} : { access_code: wanted };
    const result = await action.run(() =>
      api.request("post", "/api/v1/users/{hid}/access-code", { path: { hid: user.hid }, body }),
    );
    if (!result.ok) return;
    setWanted("");
    setCode(result.value.access_code);
    // Resetting your own code ends this session too. Reading the user again would bring
    // the sign-in page up before the new code has been read.
    if (!own) reload();
  }

  return (
    <section aria-labelledby="access-code">
      <h2 id="access-code">Access code</h2>
      {code !== null && (
        <SecretBox
          title={`New access code for ${user.username}`}
          secret={code}
          {...(own
            ? { note: "This is your own account. You will be asked to sign in again." }
            : {})}
          onDone={() => setCode(null)}
        />
      )}
      <p>
        A new access code replaces the old one and ends every session {user.username} has. The new
        code is shown once.
      </p>
      <div className="stack">
        <Problem error={action.error} shown={["access_code"]} />
        {/* 0.9.15: Generate puts a code the server made in the box (P-300). */}
        <GenerateCode onMade={setWanted} disabled={action.busy}>
          <TextField
            label="New access code"
            name="access_code"
            value={wanted}
            onChange={setWanted}
            maxLength={200}
            autoComplete="off"
            hint={accessCodeHint(leastCodeLength(settings.data))}
            error={action.error?.fields.access_code}
          />
        </GenerateCode>
        <p className="actions">
          <ConfirmButton
            label="Reset access code"
            title={`Reset the access code of ${user.username}?`}
            confirmLabel="Reset access code"
            onConfirm={reset}
            disabled={action.busy}
          >
            <p>
              The old access code stops working at once and every session {user.username} has ends.
            </p>
          </ConfirmButton>
        </p>
      </div>
    </section>
  );
}

function Sessions({ user, reload }: { user: User; reload: () => void }) {
  const auth = useAuth();
  const own = auth.user.hid === user.hid;
  const [done, setDone] = useState("");
  const action = useAction();

  async function end() {
    setDone("");
    const result = await action.run(() =>
      api.request("post", "/api/v1/users/{hid}/sign-out-everywhere", { path: { hid: user.hid } }),
    );
    if (!result.ok) return;
    if (own) {
      auth.signOut();
      return;
    }
    setDone(`Every session of ${user.username} has ended.`);
    reload();
  }

  return (
    <section aria-labelledby="sessions">
      <h2 id="sessions">Sessions</h2>
      <Problem error={action.error} />
      <Notice text={done} />
      <p className="actions">
        <ConfirmButton
          label="Sign out everywhere"
          title={`Sign ${user.username} out everywhere?`}
          confirmLabel="Sign out everywhere"
          onConfirm={end}
          disabled={action.busy}
        >
          <p>
            This ends every session {user.username} has, in every browser and on every machine.
            {own && " This is your own account: you will have to sign in again."}
          </p>
        </ConfirmButton>
      </p>
    </section>
  );
}

function tokenState(token: Token, now: number): string {
  if (token.revoked_at) return "Revoked";
  if (token.expires_at && Date.parse(token.expires_at) <= now) return "Expired";
  return "Active";
}

/**
 * The tokens of a service account or an agent. 0.9.17: the account is read again when a
 * token is made, so that what the new one says of its being refused is said of the
 * account as it is now, its person changed elsewhere too (review 9).
 */
function Tokens({ user, refresh }: { user: User; refresh: () => void }) {
  // 0.9.14: a retired account is given no token, and those it had are revoked (P-296).
  const retired = userState(user) === "Retired";
  const tokens = useLoad(`tokens ${user.hid}`, (signal) =>
    api.request("get", "/api/v1/users/{hid}/service-tokens", { path: { hid: user.hid }, signal }),
  );
  // A retirement revokes them and a bringing back leaves them so: they are read again
  // when the account changes, so that the list says what the server did (review 2).
  useReloadOn(user.row_version, tokens.reload);
  const [name, setName] = useState("");
  const [expires, setExpires] = useState("");
  const [secret, setSecret] = useState<Schemas["ServiceTokenCreated"] | null>(null);
  const create = useAction();
  const revoke = useAction();
  const fields = create.error?.fields ?? {};
  const now = Date.now();
  const sorting = useSorting(tokens.data, {
    name: (token) => token.name,
    state: (token) => tokenState(token, now),
    created: (token) => dateValue(token.created_at),
    expires: (token) => dateValue(token.expires_at),
    last_used: (token) => dateValue(token.last_used_at),
  });

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSecret(null);
    const body: Schemas["ServiceTokenCreate"] = { name: name.trim() };
    if (expires !== "") {
      // The field holds a time in the application's zone. The server is sent that moment.
      const [year = 0, month = 1, day = 1, hour = 0, minute = 0] = expires
        .split(/[-T:]/)
        .map(Number);
      const at = momentIn(appZone(), year, month, day, hour, minute);
      body.expires_at = Number.isNaN(at.getTime()) ? expires : at.toISOString();
    }
    const result = await create.run(() =>
      api.request("post", "/api/v1/users/{hid}/service-tokens", { path: { hid: user.hid }, body }),
    );
    if (!result.ok) return;
    setName("");
    setExpires("");
    setSecret(result.value);
    tokens.reload();
    refresh();
  }

  async function revokeToken(token: Token) {
    const result = await revoke.run(() =>
      api.request("post", "/api/v1/service-tokens/{hid}/revoke", { path: { hid: token.hid } }),
    );
    if (result.ok) tokens.reload();
  }

  return (
    <section aria-labelledby="tokens">
      <h2 id="tokens">{user.kind === "agent" ? "Tokens" : "Service tokens"}</h2>
      {secret && (
        <SecretBox
          title={`Token ${secret.token.name} for ${user.username}`}
          secret={secret.secret}
          // 0.9.17: an account that holds no role has its tokens refused (P-299, P-314),
          // and an agent's while its person cannot answer for it (P-316), as the account
          // now stands: a role given since, on this page, says nothing.
          {...(tokenRefused(user) ? { note: tokenRefused(user) ?? "" } : {})}
          onDone={() => setSecret(null)}
        />
      )}
      <Problem error={tokens.error} />
      <Problem error={revoke.error} />
      {tokens.loading && !tokens.data && <p role="status">Loading…</p>}
      {tokens.data && (
        <div className="scroll">
          <table>
            <caption className="visually-hidden">Tokens of {user.username}</caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="name">
                  Name
                </SortTh>
                <SortTh sort={sorting} column="state">
                  State
                </SortTh>
                <SortTh sort={sorting} column="created">
                  Created
                </SortTh>
                <SortTh sort={sorting} column="expires">
                  Expires
                </SortTh>
                <SortTh sort={sorting} column="last_used">
                  Last used
                </SortTh>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((token) => (
                <tr
                  key={token.hid}
                  className={tokenState(token, now) === "Active" ? undefined : "dim"}
                >
                  <th scope="row">{token.name}</th>
                  <td>{tokenState(token, now)}</td>
                  <td>
                    <Time at={token.created_at} />
                  </td>
                  <td>
                    <Time at={token.expires_at} />
                  </td>
                  <td>
                    <Time at={token.last_used_at} />
                  </td>
                  <td>
                    {!token.revoked_at && (
                      <ConfirmButton
                        label="Revoke"
                        title={`Revoke the token ${token.name}?`}
                        confirmLabel="Revoke token"
                        onConfirm={() => revokeToken(token)}
                        disabled={revoke.busy}
                      >
                        <p>Whatever uses this token will be refused from now on.</p>
                      </ConfirmButton>
                    )}
                  </td>
                </tr>
              ))}
              {tokens.data.length === 0 && (
                <tr>
                  <td colSpan={6} className="muted">
                    {user.kind === "agent"
                      ? "This agent has no tokens."
                      : "This service account has no tokens."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {retired && (
        <p className="muted" data-testid="tokens-retired">
          A retired account is given no token: bring it back first.
        </p>
      )}
      {/* Not drawn at all for a retired account: a form that is only hidden is still
          on show where a style says how it is laid out (review 2). */}
      {!retired && (
        <>
          <h3>New token</h3>
          <form onSubmit={submit} className="stack">
            <Problem error={create.error} shown={["name", "expires_at"]} />
            <TextField
              label="Name"
              name="name"
              value={name}
              onChange={setName}
              required
              maxLength={100}
              autoComplete="off"
              hint="What will use the token"
              error={fields.name}
            />
            <TextField
              label="Expires"
              name="expires_at"
              type="datetime-local"
              value={expires}
              onChange={setExpires}
              hint={`In ${appZone()} time. Leave empty for a token that does not expire.`}
              error={fields.expires_at}
            />
            <p className="actions">
              <button type="submit" className="primary" disabled={create.busy}>
                Create token
              </button>
            </p>
          </form>
        </>
      )}
    </section>
  );
}
