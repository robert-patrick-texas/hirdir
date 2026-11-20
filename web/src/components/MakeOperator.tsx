// 0.9.13: an operator made of a person in one press (P-284), on the page of a user and
// on the page of a contact who is behind none. The operator's contact is that person,
// its label the username where the person is a user and the contact's name where not,
// and its colour the next that no operator has (`next_for_operators` of GET /colours).
// The page of the operator made is opened. A name that is no label, as a contact's name
// over 40 characters, opens the label and the colour here at once, said in plain words,
// rather than offering a press that must fail; and a label the server does not take,
// another operator's, opens them too, with the refusal at the field and nothing lost.

import { type FormEvent, useId, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { api } from "../api";
import { ApiError } from "../api/client";
import { useAction } from "../lib/hooks";
import { labelProblem, refusedField } from "../lib/onboarding";
import { operatorPath } from "../lib/operators";
import { ColourField, readColours, useNextColour } from "./ColourPicker";
import { createdState } from "./Created";
import { TextField } from "./Field";
import { Problem } from "./Problem";

interface MakeOperatorProps {
  /** The contact the operator is to stand for. */
  contactHid: string;
  /** The label it is given at first. */
  label: string;
  /** The person, as the button's words name them. */
  who: string;
}

export function MakeOperator({ contactHid, label: proposed, who }: MakeOperatorProps) {
  const navigate = useNavigate();
  const action = useAction();
  // Open where the name is no label, or once the server refused the label or the colour:
  // then they are typed here, until Cancel.
  const [open, setOpen] = useState(() => labelProblem(proposed) !== null);
  const [label, setLabel] = useState(proposed);
  // The colour as chosen, or as read at the press; null until either.
  const [colour, setColour] = useState<string | null>(null);
  // Held at once, before the page draws the button as busy: a second press sends nothing.
  const out = useRef(false);

  async function make(sent: { label: string; colour: () => Promise<string | null> }) {
    if (out.current) return;
    out.current = true;
    const result = await action.run(async () => {
      const chosen = await sent.colour();
      try {
        return await api.request("post", "/api/v1/operators", {
          body: {
            label: sent.label,
            contact_hid: contactHid,
            record_status: "active",
            ...(chosen ? { colour: chosen } : {}),
          },
        });
      } catch (thrown) {
        // Refused for what can be typed here: the label and the colour are opened.
        if (thrown instanceof ApiError && refusedField(thrown.fields)) setOpen(true);
        throw thrown;
      }
    });
    out.current = false;
    if (!result.ok) return;
    const to = operatorPath(result.value.hid);
    navigate(to, { state: createdState({ kind: "Operator", name: result.value.label, to }) });
  }

  function press() {
    void make({
      label: proposed.trim(),
      // The next colour is asked for at the press: another operator may have taken the
      // one there was when the page was read.
      colour: async () => {
        const next = (await readColours(performance.now())).next_for_operators;
        setColour(next);
        return next;
      },
    });
  }

  return (
    <div className="make-operator" data-testid="make-operator">
      <Problem error={action.error} shown={open ? ["label", "colour"] : []} />
      {open ? (
        <MakeOperatorForm
          who={who}
          label={label}
          onLabel={setLabel}
          colour={colour}
          onColour={setColour}
          refused={action.error?.fields ?? {}}
          busy={action.busy}
          onMake={(sent) => void make(sent)}
          onCancel={() => {
            setOpen(false);
            setLabel(proposed);
            action.clear();
          }}
          cancel={labelProblem(proposed) === null}
        />
      ) : (
        <p className="actions">
          <button type="button" onClick={press} disabled={action.busy}>
            Make an operator
          </button>{" "}
          <span className="muted">
            labelled <span className="mono">{proposed}</span>, in the next colour no operator has
          </span>
        </p>
      )}
    </div>
  );
}

interface MakeOperatorFormProps {
  who: string;
  label: string;
  onLabel: (label: string) => void;
  colour: string | null;
  onColour: (colour: string) => void;
  /** What the server refused, by field. */
  refused: Readonly<Record<string, string>>;
  busy: boolean;
  onMake: (sent: { label: string; colour: () => Promise<string | null> }) => void;
  onCancel: () => void;
  /** Whether Cancel is offered: not where the proposed label is itself no label. */
  cancel: boolean;
}

/**
 * The label and the colour of the operator, opened in place. The colour on show is the
 * one sent: the one chosen, or the next that no operator has, read as the form opened.
 * What is wrong with the label is said before anything is sent.
 */
function MakeOperatorForm(props: MakeOperatorFormProps) {
  const { who, label, onLabel, colour, onColour, refused, busy, onMake, onCancel } = props;
  const id = useId();
  const next = useNextColour();
  const shown = colour ?? next.next ?? "";
  // What is wrong with the label is said as it stands, the person's name at first.
  const fault = labelProblem(label);
  const labelError = refused.label ?? fault ?? undefined;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (fault !== null) return;
    onMake({
      label: label.trim(),
      colour: async () => (colour !== null ? colour.trim() || null : await next.wait()),
    });
  }

  return (
    <form onSubmit={submit} className="stack make-operator-form" noValidate>
      <p className="hint" id={`${id}-why`}>
        The operator of {who} is made with this label and colour once they are put right.
      </p>
      <TextField
        label="Label"
        name="label"
        value={label}
        onChange={onLabel}
        required
        autoComplete="off"
        hint="Short, and of your choosing: at most 40 characters, with no semicolon. It is what lists and reports show."
        error={labelError}
        disabled={busy}
      />
      <ColourField
        label="Colour"
        name="colour"
        value={shown}
        onChange={onColour}
        sample={label}
        hint="The next colour that no operator has, unless another is chosen. Blank is no colour."
        error={refused.colour}
        disabled={busy}
      />
      <p className="actions">
        <button type="submit" className="primary" disabled={busy}>
          Make the operator
        </button>
        {props.cancel && (
          <button type="button" disabled={busy} onClick={onCancel}>
            Cancel
          </button>
        )}
      </p>
    </form>
  );
}
