import type { ReactNode } from "react";
import type { FieldSpec, FormValue, FormValues, Option } from "../lib/patch";
import { CheckField, CheckGroupField, SelectField, TextAreaField, TextField } from "./Field";

interface FormFieldsProps {
  specs: readonly FieldSpec[];
  values: FormValues;
  onChange: (name: string, value: FormValue) => void;
  /** What is wrong with a field, by its name: the server's word, or the form's own. */
  errors?: Readonly<Record<string, string>>;
  /** A hint for a field that depends on the record, in place of the field's own. */
  hints?: Readonly<Record<string, string>>;
  disabled?: boolean;
}

function grouped(options: readonly Option[]): ReactNode {
  const groups = new Map<string, Option[]>();
  for (const option of options) {
    const members = groups.get(option.group ?? "") ?? [];
    members.push(option);
    groups.set(option.group ?? "", members);
  }
  return [...groups].map(([group, members]) => {
    const choices = members.map((option) => (
      <option key={option.value} value={option.value}>
        {option.label}
      </option>
    ));
    return group === "" ? (
      choices
    ) : (
      <optgroup key={group} label={group}>
        {choices}
      </optgroup>
    );
  });
}

/**
 * The inputs of a form, one for each field it is given, each labelled. A field with a
 * heading starts a new group under that heading.
 */
export function FormFields(props: FormFieldsProps) {
  const groups: Array<{ heading: string; specs: FieldSpec[] }> = [];
  for (const spec of props.specs) {
    const last = groups.at(-1);
    if (!last || spec.heading !== undefined)
      groups.push({ heading: spec.heading ?? "", specs: [spec] });
    else last.specs.push(spec);
  }
  return groups.map((group) => (
    <div className="field-group" key={group.specs[0]?.name ?? group.heading}>
      {group.heading && <h3>{group.heading}</h3>}
      <div className="fields">{inputs({ ...props, specs: group.specs })}</div>
    </div>
  ));
}

function inputs({ specs, values, onChange, errors, hints, disabled }: FormFieldsProps): ReactNode {
  return specs.map((spec) => {
    const { name, label, kind } = spec;
    const value = values[name];
    const hint = hints?.[name] ?? spec.hint;
    const shared = {
      label,
      name,
      error: errors?.[name],
      ...(hint === undefined ? {} : { hint }),
      ...(disabled === undefined ? {} : { disabled }),
    };
    const text = typeof value === "string" ? value : "";
    const more = {
      ...(spec.required === undefined ? {} : { required: spec.required }),
      ...(spec.maxLength === undefined ? {} : { maxLength: spec.maxLength }),
    };
    switch (kind) {
      case "boolean":
        return (
          <CheckField
            key={name}
            {...shared}
            checked={value === true}
            onChange={(checked) => onChange(name, checked)}
          />
        );
      case "tristate":
        return (
          <SelectField
            key={name}
            {...shared}
            value={text}
            onChange={(next) => onChange(name, next)}
          >
            {(spec.blank !== undefined || text === "") && (
              <option value="">{spec.blank ?? "—"}</option>
            )}
            <option value="true">Yes</option>
            <option value="false">No</option>
          </SelectField>
        );
      case "choice":
        return (
          <SelectField
            key={name}
            {...shared}
            {...(spec.required === undefined ? {} : { required: spec.required })}
            value={text}
            onChange={(next) => onChange(name, next)}
          >
            {spec.blank !== undefined && <option value="">{spec.blank}</option>}
            {grouped(spec.options ?? [])}
          </SelectField>
        );
      case "set":
        return (
          <CheckGroupField
            key={name}
            {...shared}
            options={spec.options ?? []}
            value={Array.isArray(value) ? value : []}
            onChange={(next) => onChange(name, next)}
          />
        );
      case "longtext":
      case "lines":
        return (
          <TextAreaField
            key={name}
            {...shared}
            {...more}
            value={text}
            onChange={(next) => onChange(name, next)}
          />
        );
      default:
        return (
          <TextField
            key={name}
            {...shared}
            {...more}
            type={kind === "date" ? "date" : "text"}
            {...(kind === "integer" ? { inputMode: "numeric" as const } : {})}
            {...(kind === "decimal" ? { inputMode: "decimal" as const } : {})}
            autoComplete="off"
            value={text}
            onChange={(next) => onChange(name, next)}
          />
        );
    }
  });
}
