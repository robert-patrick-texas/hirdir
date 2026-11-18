// 0.9.6: what becomes of a member that leaves a stack, in the form that ends its
// membership (P-218). A person chooses; each choice fills the fields, which the person may
// change; the lifecycle rules and the choices the server publishes say what is offered,
// and the server decides. Nothing follows from the end by a rule. 0.9.8: the same form says
// what becomes of the item that leaves by a replacement (P-242), and either may give the
// item its condition, which To be returned to the manufacturer starts at Failed (P-245).

import { useId, useState } from "react";
import { api } from "../api";
import { CONDITION_LIST } from "../lib/health";
import { useLoad } from "../lib/hooks";
import { dispositionsIn, intentChoices, nextStates } from "../lib/lifecycle";
import { useChoices, useRules } from "../lib/lists";
import { choiceOptions } from "../lib/options";
import {
  LEAVING,
  LEAVING_LABELS,
  type Leaving,
  type LeavingBody,
  type LeavingValues,
  leavingBody,
  leavingPreset,
} from "../lib/stacks";
import { SelectField, TextField } from "./Field";
import { LocationField } from "./LocationField";
import { Problem } from "./Problem";

const LEAVING_NAMES = [
  "hostname",
  "fqdn",
  "location_hid",
  "lifecycle_state",
  "state_reason",
  "disposition",
  "expected_online",
  "condition",
];

/**
 * The fields of what the item is to have that a refusal names: `item.hostname` with the
 * end of a membership, `old_item.hostname` with a replacement.
 */
export function leavingFields(prefix: string): string[] {
  return LEAVING_NAMES.map((name) => `${prefix}.${name}`);
}

/** The fields of `item` that a refusal names, as `item.hostname`. */
export const LEAVING_FIELDS = leavingFields("item");

interface WhatBecomesOfItProps {
  itemHid: string;
  /** What the server refused, by the names of `leavingFields(prefix)`. */
  errors: Readonly<Record<string, string>>;
  /** What the server calls the fields: `item` with an end, `old_item` with a replacement. */
  prefix?: string;
  /** 0.9.8: the Condition field, of the item_condition list (P-245). */
  condition?: boolean;
  /** What is to be sent as `item`, or null for nothing. */
  onChange: (body: LeavingBody | null) => void;
  disabled?: boolean;
}

/**
 * What becomes of it: to the spare pool, to be returned to the manufacturer, excess, or
 * nothing now, which is where it starts. The item is read when the form opens, for its
 * state and disposition.
 */
export function WhatBecomesOfIt(props: WhatBecomesOfItProps) {
  const { itemHid, errors, onChange, disabled, prefix = "item", condition = false } = props;
  const id = useId();
  const item = useLoad(`leaving ${itemHid}`, (signal) =>
    api.request("get", "/api/v1/items/{hid}", { path: { hid: itemHid }, signal }),
  );
  const rules = useRules();
  const choices = useChoices();
  const [choice, setChoice] = useState<Leaving>("nothing");
  const [values, setValues] = useState<LeavingValues | null>(null);
  const ruled = rules.data ?? [];
  const record = item.data;
  const state = record?.lifecycle_state ?? null;
  const kept = record?.disposition ?? null;
  const reasons = choiceOptions(choices.data, "state_reason");
  const conditions = choiceOptions(choices.data, CONDITION_LIST, record?.condition);
  const said = (field: string) => errors[`${prefix}.${field}`];
  const ready = record !== undefined && rules.data !== undefined && choices.data !== undefined;

  function update(next: LeavingValues | null) {
    setValues(next);
    onChange(next ? leavingBody(next) : null);
  }

  function choose(chosen: Leaving) {
    setChoice(chosen);
    update(
      leavingPreset(chosen, state, {
        next: nextStates(ruled, state),
        dispositions: (inState) => dispositionsIn(ruled, inState, kept),
        reasons: reasons.map((reason) => reason.value),
        ...(condition ? { conditions: conditions.map((one) => one.value) } : {}),
      }),
    );
  }

  function set(field: keyof LeavingValues, value: string) {
    if (!values) return;
    const next = { ...values, [field]: value };
    // A reason is for a move: none is kept once the state is left as it is.
    if (field === "lifecycle_state" && value === "") next.state_reason = "";
    // What the form shows is what is sent: a disposition or an intent that the state now
    // aimed at does not offer is shown as "As it is", so it is not kept to be sent.
    const aimed = next.lifecycle_state || state;
    if (next.disposition !== "" && !dispositionsIn(ruled, aimed, kept).includes(next.disposition)) {
      next.disposition = "";
    }
    const offered = intentChoices(ruled, aimed, next.disposition || kept).map(String);
    if (next.online !== "" && !offered.includes(next.online)) next.online = "";
    update(next);
  }

  const target = values?.lifecycle_state || state;
  const dispositions = dispositionsIn(ruled, target, kept);
  const intents = intentChoices(ruled, target, values?.disposition || kept);
  return (
    <fieldset className="plain leaving" data-testid="what-becomes-of-it">
      <legend>What becomes of it</legend>
      <Problem error={item.error ?? rules.error ?? choices.error} />
      <div className="leaving-choices">
        {LEAVING.map((one) => (
          <div className="field field-check" key={one}>
            <input
              type="radio"
              id={`${id}-${one}`}
              name={`${id}-leaving`}
              value={one}
              checked={choice === one}
              disabled={disabled || !ready}
              onChange={() => choose(one)}
            />
            <label htmlFor={`${id}-${one}`}>{LEAVING_LABELS[one]}</label>
          </div>
        ))}
      </div>
      {!ready && !item.error && (
        <p className="muted loading-late" role="status">
          Reading the item…
        </p>
      )}
      {values && (
        <div className="fields">
          <TextField
            label="Hostname"
            name="leaving-hostname"
            value={values.hostname}
            onChange={(value) => set("hostname", value)}
            disabled={disabled}
            error={said("hostname")}
            hint={
              values.hostname === "" && !record?.hostname
                ? "Its own name from now. Left blank, it has no name: it was known by the stack's."
                : "Its own name from now. Blank, left as it is."
            }
          />
          <TextField
            label="FQDN"
            name="leaving-fqdn"
            value={values.fqdn}
            onChange={(value) => set("fqdn", value)}
            disabled={disabled}
            error={said("fqdn")}
            hint="Blank, left as it is."
          />
          <LocationField
            label="Location"
            name="leaving-location"
            value={values.location_hid}
            onChange={(value) => set("location_hid", value)}
            blank="Left as it is"
            disabled={disabled}
            error={said("location_hid")}
            hint={
              values.location_hid === "" && !record?.location_hid
                ? "Where it goes. Left as it is, it is nowhere: it has the stack's place no more."
                : "Where it goes: it has the stack's place no more."
            }
          />
          <SelectField
            label="Lifecycle state"
            name="leaving-state"
            value={values.lifecycle_state}
            onChange={(value) => set("lifecycle_state", value)}
            disabled={disabled}
            error={said("lifecycle_state")}
          >
            <option value="">As it is{state ? ` (${state})` : ""}</option>
            {nextStates(ruled, state).map((one) => (
              <option key={one} value={one}>
                {one}
              </option>
            ))}
          </SelectField>
          {values.lifecycle_state !== "" && (
            <SelectField
              label="Reason"
              name="leaving-reason"
              value={values.state_reason}
              onChange={(value) => set("state_reason", value)}
              disabled={disabled}
              error={said("state_reason")}
            >
              <option value="">None</option>
              {reasons.map((reason) => (
                <option key={reason.value} value={reason.value}>
                  {reason.label}
                </option>
              ))}
            </SelectField>
          )}
          <SelectField
            label="Disposition"
            name="leaving-disposition"
            value={values.disposition}
            onChange={(value) => set("disposition", value)}
            disabled={disabled}
            error={said("disposition")}
          >
            <option value="">As it is{kept ? ` (${kept})` : ""}</option>
            {dispositions.map((one) => (
              <option key={one} value={one}>
                {one}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="Expected online"
            name="leaving-online"
            value={values.online}
            onChange={(value) => set("online", value)}
            disabled={disabled}
            error={said("expected_online")}
          >
            <option value="">As it is</option>
            {intents.map((one) => (
              <option key={String(one)} value={String(one)}>
                {one ? "Yes" : "No"}
              </option>
            ))}
          </SelectField>
          {condition && (
            <SelectField
              label="Condition"
              name="leaving-condition"
              value={values.condition}
              onChange={(value) => set("condition", value)}
              disabled={disabled}
              error={said("condition")}
              hint="The state of the hardware as a person knows it."
            >
              <option value="">
                As it is
                {record?.condition
                  ? ` (${conditions.find((one) => one.value === record.condition)?.label ?? record.condition})`
                  : ""}
              </option>
              {conditions.map((one) => (
                <option key={one.value} value={one.value}>
                  {one.label}
                </option>
              ))}
            </SelectField>
          )}
        </div>
      )}
    </fieldset>
  );
}
