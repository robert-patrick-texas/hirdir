// 0.9.8: a switch that stands alone is made a stack from its page, in one request (P-243).
// The form shows the name the stack will have, the switch's own from the start, says what
// goes from the switch to the stack, and lets more switches be chosen, each with the box
// of a member that joins (P-217). The server makes the stack, moves what it holds for its
// members, and adds the others; the stack's page is shown afterwards, saying so.

import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router";
import { api, type Schemas } from "../api";
import { itemName } from "../lib/format";
import { buildMembers, type PendingMember } from "../lib/groups";
import { useAction } from "../lib/hooks";
import { useRules } from "../lib/lists";
import { fieldErrors } from "../lib/problems";
import { MEMBER_FIELDS, madeStackText, makeStackText, refusedRows } from "../lib/stacks";
import { TextField } from "./Field";
import { MemberPicker } from "./MemberPicker";
import { Problem } from "./Problem";

type Item = Schemas["ItemOut"];

/** The state the stack's page is reached with: what it says first. */
export function madeState(text: string): { made: string } {
  return { made: text };
}

interface MakeStackProps {
  item: Item;
  onCancel: () => void;
}

/** Make it a stack: the name, what goes to the stack, and more members, sent as one request. */
export function MakeStack({ item, onCancel }: MakeStackProps) {
  const navigate = useNavigate();
  const rules = useRules();
  const name = itemName(item);
  const [stackName, setStackName] = useState(item.name || item.hostname || "");
  const [pending, setPending] = useState<PendingMember[]>([]);
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  const [sent, setSent] = useState<ReadonlyArray<{ item_hid: string }>>([]);
  const action = useAction();
  const rowFields = sent.flatMap((_, index) =>
    ["item_hid", ...MEMBER_FIELDS].map((field) => `members.${index}.${field}`),
  );
  const known = ["name", "item_hid", ...rowFields];
  const refused = fieldErrors(action.error, known).shown;
  const answered = refusedRows(sent, refused, action.error?.existing ?? null);
  // A refusal of a member's item, as one in another stack, is said beside its row too.
  sent.forEach((member, index) => {
    const said = refused[`members.${index}.item_hid`];
    if (said) answered.errors[member.item_hid] = said;
  });

  async function submit(event: FormEvent) {
    event.preventDefault();
    const built = buildMembers("stack", pending);
    setRowErrors(built.errors);
    if (Object.keys(built.errors).length > 0) {
      action.clear();
      return;
    }
    setSent(built.members);
    const typed = stackName.trim();
    const body: Schemas["MakeStack"] = {
      row_version: item.row_version,
      ...(typed ? { name: typed } : {}),
      ...(built.members.length > 0 ? { members: built.members } : {}),
    };
    const result = await action.run(() =>
      api.request("post", "/api/v1/items/{hid}/make-stack", { path: { hid: item.hid }, body }),
    );
    if (!result.ok) return;
    const made = result.value;
    navigate(`/groups/${encodeURIComponent(made.hid)}`, {
      state: madeState(madeStackText(made.name, name, built.members.length)),
    });
  }

  return (
    <section className="panel make-stack" aria-labelledby="make-stack">
      <h3 id="make-stack">Make it a stack</h3>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={known} />
        <Problem error={rules.error} />
        <div className="fields">
          <TextField
            label="Name of the stack"
            name="stack-name"
            value={stackName}
            onChange={setStackName}
            maxLength={200}
            autoComplete="off"
            error={refused.name}
            hint={`Left blank, ${name}'s own.`}
          />
        </div>
        {refused.item_hid && <p className="field-error">{refused.item_hid}</p>}
        <p className="hint" data-testid="make-stack-goes">
          {makeStackText(name, item)}
        </p>
        <fieldset className="plain">
          <legend>More members</legend>
          <p className="hint">
            {name} is member 1. A second switch, or more, joins as Add members adds one.
          </p>
          <MemberPicker
            type="stack"
            pending={pending}
            onChange={setPending}
            taken={[item.hid]}
            positions={[1]}
            next={2}
            errors={{ ...answered.errors, ...rowErrors }}
            holders={answered.holders}
            joins
            rules={rules.data ?? []}
            disabled={action.busy}
          />
        </fieldset>
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy}>
            Make the stack
          </button>
          <button type="button" onClick={onCancel} disabled={action.busy}>
            Cancel
          </button>
        </p>
      </form>
    </section>
  );
}
