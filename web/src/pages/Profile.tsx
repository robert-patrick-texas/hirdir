// 0.9.14: a person's own profile (P-289, P-294, P-295), reached from their name in the
// menu bar, for every role. Three parts, each a form of its own with a button of its
// own, named for the part (Save details, Save KL, Change access code): the
// details of the contact the person is, the label and the colour of each operator they
// are behind, and their access code. Each is changed by a route of the person's own,
// which names no record: the server changes those of whoever is signed in. What the page
// does not change it shows as text: the username, the role and the groups.

import { type FormEvent, useEffect, useEffectEvent, useRef, useState } from "react";
import { Link } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { TextField } from "../components/Field";
import { Notice, Problem } from "../components/Problem";
import { EditForm } from "../components/RecordForm";
import { HelpList } from "../components/WhomToAsk";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { operatorPath, safeColour } from "../lib/operators";
import { helpOf } from "../lib/product";
import {
  type CodeBoxes,
  codeProblems,
  codeWords,
  DETAIL_SPECS,
  minLengthOf,
  NO_CODES,
  operatorSpecs,
} from "../lib/profile";
import { roleLabel } from "../lib/roles";

type Me = Schemas["MeOut"];
type Contact = NonNullable<Me["contact"]>;
type Operator = Me["operators"][number];

export function Profile() {
  useTitle("Profile");
  const { user, took } = useAuth();

  // The frame read who is signed in when it was loaded, which may be hours ago: the page
  // reads it again as it opens, shows what it has meanwhile, and hands the frame the
  // answer. It asks for that alone, which a person who holds no role reads as well.
  const read = useLoad("profile", (signal) => api.request("get", "/api/v1/auth/me", { signal }));
  const answered = read.data;
  useEffect(() => {
    if (answered) took(answered);
  }, [answered, took]);

  const contact = user.contact;
  const own = contact !== null && contact.record_status !== "retired" ? contact : null;
  return (
    <>
      <h1>Profile</h1>
      <Problem error={read.error} />
      <dl className="facts" data-testid="profile-facts">
        <dt>Username</dt>
        <dd className="mono">{user.username}</dd>
        <dt>Role</dt>
        <dd>{roleLabel(user.role)}</dd>
        <dt>Groups</dt>
        <dd>
          {user.groups.length > 0 ? (
            user.groups.map((group) => group.name).join(", ")
          ) : (
            <span className="muted">—</span>
          )}
        </dd>
      </dl>
      <p className="hint profile-fixed">An Admin changes your username, role and groups.</p>
      {own ? (
        <>
          <Details key={own.hid} contact={own} reload={read.reload} />
          <Operators operators={user.operators} role={user.role} reload={read.reload} />
        </>
      ) : (
        <NoContact retired={contact} />
      )}
      <AccessCode username={user.username} role={user.role} />
    </>
  );
}

/**
 * The name, email, numbers and organization of the contact the person is. Only what was
 * changed is sent, with the version the contact was read at; a refusal is shown at its
 * field, an email that another contact has with that contact as a link, and nothing
 * typed is lost.
 */
function Details({ contact, reload }: { contact: Contact; reload: () => void }) {
  const { took } = useAuth();
  const [done, setDone] = useState("");
  return (
    <section
      className="profile-part"
      aria-labelledby="profile-details"
      data-testid="profile-details"
    >
      <h2 id="profile-details">Details</h2>
      <p className="hint">They are your contact's, and are shown wherever you are named.</p>
      <Notice text={done} />
      <EditForm<Contact, Schemas["OwnContactPatch"]>
        specs={DETAIL_SPECS}
        record={contact}
        save={async (body) => {
          const me = await api.request("patch", "/api/v1/auth/me/contact", { body });
          // The frame takes the answer: the name shows on every page at once.
          took(me);
          return me.contact;
        }}
        onSaved={() => setDone("Your details were saved.")}
        onReload={reload}
        submitLabel="Save details"
      />
    </section>
  );
}

/**
 * The operators the person is behind, one after another, each with a form of its own.
 * Somebody behind none has no such part, and a line that says so.
 */
function Operators({
  operators,
  role,
  reload,
}: {
  operators: readonly Operator[];
  role: string | null;
  reload: () => void;
}) {
  if (operators.length === 0) {
    return (
      <p className="muted" data-testid="profile-no-operator">
        You are behind no operator.
      </p>
    );
  }
  return (
    <section
      className="profile-part"
      aria-labelledby="profile-operators"
      data-testid="profile-operators"
    >
      <h2 id="profile-operators">{operators.length === 1 ? "Operator" : "Operators"}</h2>
      <p className="hint">
        {operators.length === 1
          ? "The label that stands for you on items, groups and places, and its colour."
          : "The labels that stand for you on items, groups and places, each with its colour."}
      </p>
      {operators.map((operator) => (
        <OperatorPart key={operator.hid} operator={operator} role={role} reload={reload} />
      ))}
    </section>
  );
}

/**
 * One operator: its label as a link to its page, and the form of its label and colour.
 * A person who holds no role types the colour, the colours to press being read with a
 * role (`operatorSpecs`).
 */
function OperatorPart({
  operator,
  role,
  reload,
}: {
  operator: Operator;
  role: string | null;
  reload: () => void;
}) {
  const { took } = useAuth();
  const [done, setDone] = useState("");
  // The label as the server answered the save, for the page to say what was saved.
  const saved = useRef(operator.label);
  const heading = `profile-operator-${operator.hid.replace(/[^A-Za-z0-9_-]/g, "")}`;
  const colour = safeColour(operator.colour);
  return (
    <section
      className="profile-operator"
      aria-labelledby={heading}
      data-testid="profile-operator"
      data-operator={operator.hid}
    >
      <h3 id={heading}>
        {/* The mark of an operator, as the lists show it, its label free to break where
            the page ends: a label may be 40 characters long. */}
        <Link to={operatorPath(operator.hid)} className="profile-operator-name">
          <span
            className="swatch operator-dot"
            aria-hidden="true"
            {...(colour ? { style: { backgroundColor: colour } } : {})}
          />
          {operator.label}
        </Link>
      </h3>
      <Notice text={done} />
      <EditForm<Operator, Schemas["OwnOperatorPatch"]>
        specs={operatorSpecs(role)}
        record={operator}
        save={async (body) => {
          const me = await api.request("patch", "/api/v1/auth/me/operators/{hid}", {
            path: { hid: operator.hid },
            body,
          });
          took(me);
          const now = me.operators.find((one) => one.hid === operator.hid);
          saved.current = now?.label ?? operator.label;
          return now;
        }}
        onSaved={() => setDone(`The operator ${saved.current} was saved.`)}
        onReload={reload}
        // Named for its operator: somebody behind two has no two buttons of one name.
        submitLabel={`Save ${operator.label}`}
      />
    </section>
  );
}

/**
 * An account with no contact, or one whose contact is retired: the page says so, and
 * whom to ask, as About names them, where the settings name anybody (P-169). An Admin
 * gives an account its contact.
 */
function NoContact({ retired }: { retired: Contact | null }) {
  const about = useLoad("profile whom to ask", (signal) =>
    api.request("get", "/api/v1/about", { signal }),
  );
  const help = about.data ? helpOf(about.data.help) : null;
  return (
    <section aria-label="Your contact" data-testid="profile-no-contact">
      {retired ? (
        <p>
          Your contact, {retired.name}, is retired. Ask an Admin to bring it back, or to give you
          another.
        </p>
      ) : (
        <p>You have no contact. Ask an Admin to give you one.</p>
      )}
      {help && <HelpList help={help} />}
    </section>
  );
}

/**
 * Hold a button until the moment the server said to try again, after too many attempts.
 * `over` is told when a wait that was held ends, for the page to take away the words
 * that said how long it was: they are no longer so.
 */
function useHeld(until: number, over: () => void): boolean {
  const [held, setHeld] = useState(false);
  const ended = useEffectEvent(over);
  useEffect(() => {
    const left = until - Date.now();
    if (left <= 0) {
      setHeld(false);
      return;
    }
    setHeld(true);
    const timer = window.setTimeout(() => {
      setHeld(false);
      ended();
    }, left);
    return () => window.clearTimeout(timer);
  }, [until]);
  return held;
}

/**
 * The person's own access code: the code in hand, the new one, and the new one again,
 * all three masked and each named for a password manager. Two new codes that differ are
 * said at the second before anything is sent; a wrong code in hand and a new one that is
 * too short are the server's to say, each at its box. Changed, the page keeps the new
 * session in place of the old, says so, and empties the boxes.
 */
function AccessCode({ username, role }: { username: string; role: string | null }) {
  const { adopt } = useAuth();
  // The settings are read with a role. A person who holds none is not told the least
  // length before they type: the server says it at the box.
  const settings = useLoad(`profile settings ${role !== null}`, async (signal) =>
    role === null ? [] : api.request("get", "/api/v1/settings", { signal }),
  );
  const [boxes, setBoxes] = useState<CodeBoxes>(NO_CODES);
  const [found, setFound] = useState<Record<string, string>>({});
  const [done, setDone] = useState("");
  const [waitUntil, setWaitUntil] = useState(0);
  const action = useAction();
  // The wait over, its words go: "Try again in 2 seconds" is not so once they have passed.
  const waiting = useHeld(waitUntil, () => {
    if (action.error?.status === 429) action.clear();
  });
  const form = useRef<HTMLFormElement>(null);
  // Where the page says what became of a change: that it was made, or why it was not.
  const said = useRef<HTMLDivElement>(null);
  const [refusals, setRefusals] = useState(0);
  const [changes, setChanges] = useState(0);
  const refused = { ...action.error?.fields, ...found };

  // After too many wrong codes the server says how long to wait: the button is held until then.
  const refusal = action.error;
  useEffect(() => {
    if (refusal?.status === 429 && refusal.retryAfter !== null) {
      setWaitUntil(Date.now() + refusal.retryAfter * 1000);
    }
  }, [refusal]);

  // The boxes and the button are held while a change is sent, so the keyboard is on
  // none of them when the answer comes. A refusal puts it in the first box it is about,
  // and one that is about no box, as a wait, on its words.
  useEffect(() => {
    if (refusals === 0) return;
    const box = form.current?.querySelector<HTMLElement>('[aria-invalid="true"]');
    (box ?? said.current)?.focus();
  }, [refusals]);

  // A change that was made puts it on the words that say so.
  useEffect(() => {
    if (changes > 0) said.current?.focus();
  }, [changes]);

  function type(box: keyof CodeBoxes, field: string) {
    return (value: string) => {
      setBoxes((was) => ({ ...was, [box]: value }));
      setFound(({ [field]: _, ...rest }) => rest);
    };
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const problems = codeProblems(boxes);
    setFound(problems);
    if (Object.keys(problems).length > 0) {
      action.clear();
      setRefusals((count) => count + 1);
      return;
    }
    setDone("");
    const result = await action.run(() =>
      api.request("post", "/api/v1/auth/me/access-code", {
        body: { current_access_code: boxes.current, access_code: boxes.wanted },
      }),
    );
    if (!result.ok) {
      setRefusals((count) => count + 1);
      return;
    }
    // The answer is a session, as signing in answers one: it is kept in place of the one
    // this page had, which the change ended with every other.
    adopt(result.value);
    setBoxes(NO_CODES);
    setDone("Your access code is changed. Your other sessions have ended.");
    setChanges((count) => count + 1);
  }

  return (
    <section
      className="profile-part"
      aria-labelledby="profile-access-code"
      data-testid="profile-access-code"
    >
      <h2 id="profile-access-code">Access code</h2>
      <p className="hint" data-testid="profile-code-words">
        {codeWords(minLengthOf(settings.data))}
      </p>
      {/* What became of a change, which takes the keyboard when it is said. */}
      <div className="profile-said" data-testid="profile-said" tabIndex={-1} ref={said}>
        <Notice text={done} />
        <Problem error={action.error} shown={["current_access_code", "access_code"]} />
      </div>
      <form onSubmit={submit} className="stack" noValidate ref={form}>
        {/* Not shown: it tells a password manager whose code the three boxes are. */}
        <input
          type="text"
          name="username"
          autoComplete="username"
          value={username}
          readOnly
          hidden
        />
        <TextField
          label="Access code you have"
          name="current_access_code"
          type="password"
          value={boxes.current}
          onChange={type("current", "current_access_code")}
          required
          maxLength={200}
          autoComplete="current-password"
          error={refused.current_access_code}
          disabled={action.busy}
        />
        <TextField
          label="New access code"
          name="access_code"
          type="password"
          value={boxes.wanted}
          onChange={type("wanted", "access_code")}
          required
          maxLength={200}
          autoComplete="new-password"
          error={refused.access_code}
          disabled={action.busy}
        />
        <TextField
          label="New access code again"
          name="access_code_again"
          type="password"
          value={boxes.again}
          onChange={type("again", "access_code_again")}
          required
          maxLength={200}
          autoComplete="new-password"
          error={refused.access_code_again}
          disabled={action.busy}
        />
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || waiting}>
            Change access code
          </button>
        </p>
      </form>
    </section>
  );
}
