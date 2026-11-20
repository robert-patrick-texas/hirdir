// 0.9.13: an operator made of a person in one press (P-284), on the page of a user and
// on the page of a contact who is behind none. The operator's contact is that person,
// its label the username where the person is a user and the contact's name where not,
// and its colour the next that no operator has (`next_for_operators` of GET /colours).
// The page of the operator made is opened. A label the server does not take, too long,
// or another operator's, opens the label and the colour here, with the refusal at the
// field and nothing lost, rather than failing where it cannot be put right.

import { type FormEvent, useId, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { api } from "../api";
import { ApiError } from "../api/client";
import { useAction } from "../lib/hooks";
import { refusedField } from "../lib/onboarding";
import { operatorPath } from "../lib/operators";
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
  const id = useId();
  const action = useAction();
  // Open once the server refused the label or the colour: then they are typed here, until
  // Cancel.
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState(proposed);
  const [colour, setColour] = useState<string | null>(null);
  // Held at once, before the page draws the button as busy: a second press sends nothing.
  const out = useRef(false);
  const fields = action.error?.fields ?? {};

  async function make(event?: FormEvent) {
    event?.preventDefault();
    if (out.current) return;
    out.current = true;
    const result = await action.run(async () => {
      // The next colour is asked for at the press: another operator may have taken the
      // one there was when the page was read.
      let chosen = colour;
      if (chosen === null) {
        chosen = (await api.request("get", "/api/v1/colours", {})).next_for_operators;
        setColour(chosen);
      }
      try {
        return await api.request("post", "/api/v1/operators", {
          body: {
            label: label.trim(),
            contact_hid: contactHid,
            record_status: "active",
            ...(chosen.trim() ? { colour: chosen.trim() } : {}),
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

  return (
    <div className="make-operator" data-testid="make-operator">
      <Problem error={action.error} shown={open ? ["label", "colour"] : []} />
      {open ? (
        <form onSubmit={make} className="stack make-operator-form" noValidate>
          <p className="hint" id={`${id}-why`}>
            The operator of {who} is made with this label and colour once they are put right.
          </p>
          <TextField
            label="Label"
            name="label"
            value={label}
            onChange={setLabel}
            required
            maxLength={40}
            autoComplete="off"
            hint="Short, and of your choosing: at most 40 characters, with no semicolon. It is what lists and reports show."
            error={fields.label}
            disabled={action.busy}
          />
          <TextField
            label="Colour"
            name="colour"
            value={colour ?? ""}
            onChange={setColour}
            maxLength={7}
            autoComplete="off"
            hint="In the form #1f6feb. Blank is no colour."
            error={fields.colour}
            disabled={action.busy}
          />
          <p className="actions">
            <button type="submit" className="primary" disabled={action.busy}>
              Make the operator
            </button>
            <button
              type="button"
              disabled={action.busy}
              onClick={() => {
                setOpen(false);
                action.clear();
              }}
            >
              Cancel
            </button>
          </p>
        </form>
      ) : (
        <p className="actions">
          <button type="button" onClick={() => void make()} disabled={action.busy}>
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
