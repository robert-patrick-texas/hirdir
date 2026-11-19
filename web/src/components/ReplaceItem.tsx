// 0.9.8: Replace, one press (P-242). One form, on the row of a member of a group and on
// the page of an item (Replace this item): the item that takes the place, found by the
// picker of members that says where each candidate stands (P-221); the reason and a
// reference; in a stack, the box of the stack's name and place for the one that comes
// (P-217); and What becomes of it for the one that leaves (P-218), with its condition
// (P-245); and, 0.9.8, whether what runs on it goes to the one that comes (P-247). One
// request does all of it, `POST /items/{hid}/replace`, or nothing: a refusal
// is said beside its field, and nothing typed is lost.

import { type FormEvent, useMemo, useState } from "react";
import { Link } from "react-router";
import { api, type Schemas } from "../api";
import { itemName, today } from "../lib/format";
import type { PendingMember } from "../lib/groups";
import { CONDITION_LIST } from "../lib/health";
import { useAction, useLoad } from "../lib/hooks";
import {
  fewNames,
  handedOverText,
  handOverLabel,
  hostsNothingHint,
  mayHostKind,
} from "../lib/hostFollows";
import { useChoices, useRules } from "../lib/lists";
import { choiceLabel, choiceOptions } from "../lib/options";
import { buildCreate, type FieldSpec, type FormValue, type FormValues, formOf } from "../lib/patch";
import { MAJOR_ONLY, memberOffer, pickLabel, SPARES } from "../lib/pick";
import { fieldErrors } from "../lib/problems";
import { type LeavingBody, replacedText, type SaidPart, stackOf } from "../lib/stacks";
import { CheckField, SelectField, TextField } from "./Field";
import { FormFields } from "./FormFields";
import { ItemPicker } from "./ItemPicker";
import { leavingFields, WhatBecomesOfIt } from "./LeaveStack";
import { JoinBox, joining } from "./MemberPicker";
import { Problem } from "./Problem";

type Item = Schemas["ItemOut"];

const WITH_NEW = "new";
const WITH_EXISTING = "existing";

// What the server names of the item that comes, beside its own fields.
const COMING_FIELDS = ["drop_identity", "disposition", "expected_online"];
const LEAVING = leavingFields("old_item");

function itemPath(hid: string): string {
  return `/items/${encodeURIComponent(hid)}`;
}

const NEW_ITEM_SPECS: FieldSpec[] = [
  {
    name: "catalog_entry_hid",
    label: "Catalog entry",
    // 0.9.6: searched for, not a list of every model, as in New item (P-200).
    kind: "entry",
    blank: "No catalog entry",
    hint: "The vendor and PID. A serial number needs one.",
  },
  { name: "serial_number", label: "Serial number", kind: "text", maxLength: 100 },
  { name: "asset_tag", label: "Asset tag", kind: "text", maxLength: 100 },
  { name: "name", label: "Name", kind: "text", maxLength: 200 },
  { name: "hostname", label: "Hostname", kind: "text", maxLength: 255 },
];

interface ReplaceItemProps {
  /** The item that leaves, as it was read. */
  item: Item;
  /** Says what was done, both items as links, and the page reads again. */
  onReplaced: (parts: SaidPart[]) => void;
  onCancel: () => void;
  onReload: () => void;
}

/** The form of Replace, for an item that has been read. */
export function ReplaceItem({ item, onReplaced, onCancel, onReload }: ReplaceItemProps) {
  const choices = useChoices();
  const rules = useRules();
  const stack = stackOf(item.groups) ?? null;
  const [how, setHow] = useState(WITH_EXISTING);
  const [chosen, setChosen] = useState<Item | null>(null);
  // The box and the standing of the one that comes, as changed: null until they are.
  const [change, setChange] = useState<Partial<PendingMember> | null>(null);
  const [reason, setReason] = useState("");
  const [reference, setReference] = useState("");
  const [day, setDay] = useState("");
  const [leaving, setLeaving] = useState<LeavingBody | null>(null);
  const specs = useMemo(() => NEW_ITEM_SPECS, []);
  const [values, setValues] = useState<FormValues>(() => ({
    ...formOf(specs),
    // The same model, more often than not.
    catalog_entry_hid: item.catalog_entry_hid ?? "",
  }));
  const [found, setFound] = useState<Record<string, string>>({});
  // 0.9.8: what runs on the item that leaves goes to the one that comes, unless the box
  // is unticked (P-247). Ticked from the start; unticked when an item that hosts nothing,
  // by its kind, is chosen, which the person may tick again.
  const runsOnIt = item.hosted_count;
  const [handOver, setHandOver] = useState(true);
  const [handHint, setHandHint] = useState("");
  const action = useAction();
  const reasons = choiceOptions(choices.data, "replacement_reason");
  const names = specs.map((spec) => spec.name);
  const known = [
    "reason",
    "reference",
    "replaced_on",
    "new_item_hid",
    // Beside the box where it is shown; above the form where only retired items run on
    // it, which are handed over too and are not counted.
    ...(runsOnIt > 0 ? ["hand_over_hosted"] : []),
    ...COMING_FIELDS,
  ];
  const shown = [...known, ...names, ...LEAVING];
  const refused = fieldErrors(action.error, shown).shown;
  const name = itemName(item);
  const ruled = rules.data ?? [];

  // The one that comes, as the box of a member that joins a stack holds it.
  const typedHostname = typeof values.hostname === "string" ? values.hostname.trim() : "";
  const coming: PendingMember | null =
    how === WITH_EXISTING
      ? chosen && {
          item_hid: chosen.hid,
          name: itemName(chosen),
          role: "member",
          position: "",
          ...joining(chosen, ruled),
          ...change,
        }
      : {
          item_hid: "new",
          name: "The new item",
          role: "member",
          position: "",
          joining: typedHostname ? { hostname: typedHostname } : {},
          drop: true,
          ...change,
        };

  function changeNew(field: string, value: FormValue) {
    setValues((was) => ({ ...was, [field]: value }));
    setFound((was) => {
      const { [field]: _, ...rest } = was;
      return rest;
    });
  }

  function choose(next: Item | null) {
    setChosen(next);
    setChange(null);
    if (runsOnIt > 0 && next) {
      const kind = next.catalog?.kind ?? null;
      const hosts = mayHostKind(kind);
      setHandOver(hosts);
      setHandHint(hosts || kind === null ? "" : hostsNothingHint(itemName(next), kind));
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const body: Schemas["Replace"] = { row_version: item.row_version, reason };
    if (reference.trim()) body.reference = reference.trim();
    if (day) body.replaced_on = day;
    if (how === WITH_EXISTING) {
      if (!chosen) return;
      body.new_item_hid = chosen.hid;
    } else {
      const built = buildCreate<Schemas["ItemCreate"]>(specs, values);
      setFound(built.errors);
      if (Object.keys(built.errors).length > 0) return;
      body.new_item = built.body;
    }
    // In a stack, the one that comes takes the stack's name and place, as a member that
    // joins it does, and a spare is put in production (P-217).
    const drops = stack !== null && coming?.drop === true;
    if (drops) {
      body.drop_identity = true;
      if (coming?.disposition) body.disposition = coming.disposition;
      if (coming?.online === "true") body.expected_online = true;
      if (coming?.online === "false") body.expected_online = false;
    }
    const old = leaving && Object.keys(leaving).length > 0 ? leaving : null;
    if (old) body.old_item = old;
    // Said only where something runs on it: left out, the server hands it over.
    if (runsOnIt > 0) body.hand_over_hosted = handOver;
    const result = await action.run(() =>
      api.request("post", "/api/v1/items/{hid}/replace", { path: { hid: item.hid }, body }),
    );
    if (!result.ok) return;
    const made = result.value;
    const handed = handedOverText(runsOnIt, handOver, itemName(made.new_item));
    onReplaced([
      ...replacedText({
        old: { text: old?.hostname ?? itemName(made.old_item), to: itemPath(made.old_item_hid) },
        came: { text: itemName(made.new_item), to: itemPath(made.new_item_hid) },
        group: stack?.name ?? null,
        position: stack?.position ?? null,
        sent: body,
        joining: drops ? coming?.joining : undefined,
        leaving: old,
        conditionLabel: (value) => choiceLabel(choices.data, CONDITION_LIST, value) || value,
      }),
      ...(handed ? [handed] : []),
    ]);
  }

  const ready = reason !== "" && (how === WITH_NEW || chosen !== null);
  const comingRefused = COMING_FIELDS.map((field) => refused[field]).filter(Boolean);
  return (
    <section className="panel replace-item" aria-labelledby={`replace-${item.hid}`}>
      <h3 id={`replace-${item.hid}`}>Replace {name}</h3>
      <p className="hint">
        Both records stay, linked by the replacement. The item that takes the place takes over the
        current memberships of {name}, with the same role and position, and its circuits, from the
        day of the replacement. Nothing of either changes by a rule: each has what this form says,
        in the same change.
      </p>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={shown} onReload={onReload} />
        <Problem error={choices.error ?? rules.error} />
        <div className="fields">
          <SelectField
            label="What takes its place"
            name="how"
            value={how}
            onChange={(next) => {
              setHow(next === WITH_NEW ? WITH_NEW : WITH_EXISTING);
              setChange(null);
            }}
          >
            <option value={WITH_EXISTING}>An item that is in the inventory</option>
            <option value={WITH_NEW}>A new item, created now</option>
          </SelectField>
        </div>
        {how === WITH_EXISTING &&
          (chosen ? (
            <p data-testid="chosen-replacement">
              <strong>{pickLabel(chosen)}</strong> takes its place.{" "}
              <button type="button" onClick={() => choose(null)} disabled={action.busy}>
                Choose another
              </button>
            </p>
          ) : (
            <ItemPicker
              label="The item that takes its place"
              hint="Type a part of its name, serial number or asset tag. The spares come first."
              taken={[item.hid]}
              onPick={choose}
              // 0.9.6: the spares first, each with where it stands (P-221); in a stack, a
              // major item that is in no other stack.
              first={SPARES}
              only={stack ? MAJOR_ONLY : null}
              standing={(offer) =>
                stack ? memberOffer(offer, "stack") : { ...memberOffer(offer, ""), refused: "" }
              }
              // A switch picked before the lifecycle rules are read would not be offered
              // Production: in a stack the picker waits for them.
              disabled={action.busy || (stack !== null && rules.data === undefined)}
            />
          ))}
        {how === WITH_EXISTING && refused.new_item_hid && (
          <p className="field-error">{refused.new_item_hid}</p>
        )}
        {how === WITH_NEW && (
          <fieldset className="plain">
            <legend>The new item</legend>
            <FormFields
              specs={specs}
              values={values}
              onChange={changeNew}
              errors={{ ...refused, ...found }}
              disabled={action.busy}
            />
            <p className="hint">
              It needs something to know it by: a serial number with a catalog entry, an asset tag,
              a name or a hostname. The rest is filled in on its own page.
            </p>
          </fieldset>
        )}
        {stack && coming && (
          <>
            <JoinBox
              row={coming}
              rules={ruled}
              onChange={(changed) => setChange((was) => ({ ...was, ...changed }))}
              disabled={action.busy}
            />
            {comingRefused.length > 0 && (
              <p className="field-error" data-testid="coming-error">
                {comingRefused.join(" ")}
              </p>
            )}
          </>
        )}
        <div className="fields">
          <SelectField
            label="Reason"
            name="reason"
            value={reason}
            onChange={setReason}
            required
            error={refused.reason}
          >
            <option value="">Choose a reason</option>
            {reasons.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </SelectField>
          <TextField
            label="Reference"
            name="reference"
            value={reference}
            onChange={setReference}
            maxLength={200}
            autoComplete="off"
            error={refused.reference}
            hint="An RMA, service request or ticket number"
          />
          <TextField
            label="Replaced on"
            name="replaced_on"
            type="date"
            value={day}
            onChange={setDay}
            error={refused.replaced_on}
            hint={`Left blank, today: ${today()}. What becomes of ${name} is done with a day that has come.`}
          />
        </div>
        {runsOnIt > 0 && (
          <div className="hand-over" data-testid="hand-over">
            <CheckField
              label={handOverLabel(runsOnIt)}
              name="hand_over_hosted"
              checked={handOver}
              onChange={(next) => {
                setHandOver(next);
                setHandHint("");
              }}
              disabled={action.busy}
              error={refused.hand_over_hosted}
              hint={
                handHint ||
                (handOver
                  ? "Each names the item that takes the place as its host, from the replacement on. Unticked, each stays on this one."
                  : "Each stays on this one, which is no fault: it is given another host on its own page.")
              }
            />
            <HostedNames hid={item.hid} />
          </div>
        )}
        <WhatBecomesOfIt
          itemHid={item.hid}
          prefix="old_item"
          condition
          errors={refused}
          onChange={setLeaving}
          disabled={action.busy}
        />
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || !ready}>
            Replace
          </button>
          <button type="button" onClick={onCancel} disabled={action.busy}>
            Cancel
          </button>
        </p>
      </form>
    </section>
  );
}

/** The names of what runs on the item that leaves, beneath the box, where they are few. */
function HostedNames({ hid }: { hid: string }) {
  const hosted = useLoad(`hosted ${hid}`, (signal) =>
    api.request("get", "/api/v1/items/{hid}/hosted", { path: { hid }, signal }),
  );
  // What is handed over is what names it as its host; what runs on those stays on them.
  const rows = (hosted.data?.items ?? []).filter((row) => row.depth === 1);
  const few = fewNames(rows.map((row) => row.item.hid));
  if (few.length === 0) return <Problem error={hosted.error} />;
  return (
    <ul className="hand-over-names" data-testid="hand-over-names">
      {rows.map((row) => (
        <li key={row.item.hid}>
          <Link to={itemPath(row.item.hid)}>{itemName(row.item)}</Link>
        </li>
      ))}
    </ul>
  );
}

interface ReplaceMemberProps {
  /** The item that leaves, by its HID: it is read when the form opens. */
  itemHid: string;
  onReplaced: (parts: SaidPart[]) => void;
  onCancel: () => void;
}

/** Replace on a member's row: the item is read, for its version and its groups, then the form. */
export function ReplaceMember({ itemHid, onReplaced, onCancel }: ReplaceMemberProps) {
  const item = useLoad(`replace ${itemHid}`, (signal) =>
    api.request("get", "/api/v1/items/{hid}", { path: { hid: itemHid }, signal }),
  );
  if (!item.data) {
    return (
      <section className="panel replace-item">
        <Problem error={item.error} />
        {!item.error && (
          <p className="muted loading-late" role="status">
            Reading the item…
          </p>
        )}
        <p className="actions">
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
        </p>
      </section>
    );
  }
  return (
    <ReplaceItem
      item={item.data}
      onReplaced={onReplaced}
      onCancel={onCancel}
      onReload={item.reload}
    />
  );
}
