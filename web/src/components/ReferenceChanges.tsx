// The changes made to one reference, for the Inventory role (P-160, P-162): its title,
// kind and notes, and the address of a link; a new edition of a file, which replaces it
// on every record it is on; more records to put it on; taking it off the record the page
// is of; and erasing it from every record at once. The server checks the role of each.

import { type FormEvent, type ReactNode, useRef, useState } from "react";
import { Link } from "react-router";
import { api, type Schemas } from "../api";
import { plural } from "../lib/format";
import { useAction } from "../lib/hooks";
import { Keys, withKey } from "../lib/idempotency";
import { choiceOptions } from "../lib/options";
import {
  erasureText,
  KIND_LIST,
  MAX_TITLE,
  type Reference,
  recordPage,
  refusalOf,
  refusedText,
  sizeText,
} from "../lib/references";
import { ConfirmButton } from "./ConfirmButton";
import { SelectField, TextAreaField, TextField } from "./Field";
import { Problem, StaleCause } from "./Problem";
import { findRecords } from "./referenceFiles";
import { type Offer, SearchPicker } from "./SearchPicker";

type Choice = Schemas["ChoiceOut"];

/** What a stale change of a reference says, where the server refuses it as stale. */
const STALE = "Someone changed this reference after the page read it, so your change was not made.";

/** A heading of the level a part of the page needs. */
export function Heading(props: { level: Level; id?: string; children: ReactNode }) {
  const Tag = `h${props.level}` as const;
  return <Tag id={props.id}>{props.children}</Tag>;
}

/** The level of a heading. */
export type Level = 2 | 3 | 4 | 5 | 6;
/** The level of the heading beneath one. */
export function beneath(level: Level): Level {
  return Math.min(level + 1, 6) as Level;
}

interface KindFieldProps {
  choices: readonly Choice[] | undefined;
  value: string;
  onChange: (value: string) => void;
  name: string;
  disabled?: boolean;
  error?: string | undefined;
  label?: string;
}

/** The kind of a reference, from the editable list `reference_kind`. It is required. */
export function KindField(props: KindFieldProps) {
  const { choices, value, onChange, name, disabled, error, label = "Kind" } = props;
  return (
    <SelectField
      label={label}
      name={name}
      value={value}
      onChange={onChange}
      required
      disabled={disabled}
      error={error}
    >
      <option value="">Choose a kind</option>
      {choiceOptions(choices, KIND_LIST, value || null).map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </SelectField>
  );
}

/** The records a reference is on, each leading to its page. */
export function RecordsOf({ reference }: { reference: Pick<Reference, "attachments"> }) {
  return (
    <ul className="reference-records">
      {reference.attachments.map((one) => (
        <li key={one.hid}>
          <Link to={recordPage(one.record_type, one.record_hid)}>{one.label}</Link>
        </li>
      ))}
    </ul>
  );
}

/** The record the page is of, where the reference is its own: what Take off removes. */
export interface Here {
  attachmentHid: string;
  /** What the record is called in a sentence: "location". */
  what: string;
}

interface ReferenceChangesProps {
  reference: Reference;
  here?: Here | null;
  choices: readonly Choice[] | undefined;
  /** The extensions `reference_file_types` takes, and those never taken: null until read. */
  taken: readonly string[] | null;
  refused: readonly string[];
  /** The level of the panel's heading. */
  level: Level;
  /** Something was changed: what to say of it, and whether the reference is gone from here. */
  onChanged: (text: string, gone?: boolean) => void;
  onClose: () => void;
  onReload: () => void;
}

/** Every change of one reference, in a panel of its own beneath the list it is in. */
export function ReferenceChanges(props: ReferenceChangesProps) {
  const { reference, here = null, level, onClose } = props;
  const sub = beneath(level);
  return (
    <StaleCause.Provider value={STALE}>
      <section
        className="panel reference-changes"
        aria-label={`Change ${reference.title}`}
        data-testid="reference-changes"
        data-reference={reference.hid}
      >
        <Heading level={level}>Change {reference.title}</Heading>
        <EditReference {...props} level={sub} />
        {reference.form === "file" && <NewEdition {...props} level={sub} />}
        <PutOn {...props} level={sub} />
        <section aria-label="Take off or erase">
          <Heading level={sub}>Take off or erase</Heading>
          {here && <TakeOff {...props} here={here} />}
          <Erase {...props} />
        </section>
        <p className="actions">
          <button type="button" onClick={onClose}>
            Close
          </button>
        </p>
      </section>
    </StaleCause.Provider>
  );
}

type PartProps = ReferenceChangesProps;

/** Its title, kind and notes, and a link's address. Only what was changed is sent. */
function EditReference({ reference, choices, level, onChanged, onReload }: PartProps) {
  const [title, setTitle] = useState(reference.title);
  const [kind, setKind] = useState(reference.kind);
  const [notes, setNotes] = useState(reference.notes ?? "");
  const [url, setUrl] = useState(reference.url ?? "");
  const action = useAction();
  const body: Schemas["ReferencePatch"] = { row_version: reference.row_version };
  if (title.trim() !== reference.title) body.title = title.trim();
  if (kind !== reference.kind) body.kind = kind;
  if (notes.trim() !== (reference.notes ?? ""))
    body.notes = notes.trim() === "" ? null : notes.trim();
  if (reference.form === "link" && url.trim() !== (reference.url ?? "")) body.url = url.trim();
  const unchanged = Object.keys(body).length === 1;
  const shown = ["title", "kind", "notes", "url"];

  async function submit(event: FormEvent) {
    event.preventDefault();
    const result = await action.run(() =>
      api.request("patch", "/api/v1/reference-files/{hid}", {
        path: { hid: reference.hid },
        body,
      }),
    );
    if (result.ok) onChanged(`${result.value.title} was saved.`);
  }

  return (
    <section aria-label="Edit">
      <Heading level={level}>Edit</Heading>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={shown} onReload={onReload} />
        <div className="fields">
          <TextField
            label="Title"
            name="reference-title"
            value={title}
            onChange={setTitle}
            required
            maxLength={MAX_TITLE}
            autoComplete="off"
            disabled={action.busy}
            error={action.error?.fields.title}
          />
          <KindField
            choices={choices}
            name="reference-kind"
            value={kind}
            onChange={setKind}
            disabled={action.busy}
            error={action.error?.fields.kind}
          />
          {reference.form === "link" && (
            <TextField
              label="Address"
              name="reference-url"
              value={url}
              onChange={setUrl}
              required
              maxLength={2000}
              autoComplete="off"
              placeholder="https://"
              disabled={action.busy}
              error={action.error?.fields.url}
            />
          )}
          <TextAreaField
            label="Notes"
            name="reference-notes"
            value={notes}
            onChange={setNotes}
            maxLength={10_000}
            disabled={action.busy}
            error={action.error?.fields.notes}
          />
        </div>
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || unchanged}>
            Save
          </button>
        </p>
      </form>
    </section>
  );
}

/**
 * A new edition of a file: it replaces the file on every record it is on, which it
 * names first, and keeps its title, kind and records. The content it had is erased.
 */
function NewEdition(props: PartProps) {
  const { reference, taken, refused, level, onChanged, onReload } = props;
  const [file, setFile] = useState<File | null>(null);
  const [refusal, setRefusal] = useState("");
  const [sent, setSent] = useState<{ sent: number; total: number } | null>(null);
  const action = useAction();
  const input = useRef<HTMLInputElement>(null);
  const records = reference.attachment_count;

  function chosen(files: FileList | null) {
    const one = files?.[0] ?? null;
    setFile(one);
    action.clear();
    setRefusal(one ? (refusalOf(one.name, taken, refused) ?? "") : "");
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || refusal) return;
    setSent({ sent: 0, total: file.size });
    const result = await action.run(() =>
      api.sendFile("put", "/api/v1/reference-files/{hid}/content", {
        path: { hid: reference.hid },
        query: { file_name: file.name, row_version: reference.row_version },
        file,
        onProgress: setSent,
      }),
    );
    setSent(null);
    if (!result.ok) return;
    if (input.current) input.current.value = "";
    setFile(null);
    onChanged(
      `A new edition of ${result.value.title} is in place on ${plural(records, "record")}.`,
    );
  }

  const failed = action.error && !action.error.stale ? refusedText(action.error) : "";
  const now = `${reference.file_name ?? "the file"} (${sizeText(reference.size_bytes)})`;
  const where = records === 1 ? "the record it is on" : `all ${records} records it is on`;
  return (
    <section aria-label="New edition">
      <Heading level={level}>New edition</Heading>
      <p>
        A new edition replaces {now} on {where}, at once, and keeps its title and kind. The content
        it has now is erased.
      </p>
      <RecordsOf reference={reference} />
      <form onSubmit={submit} className="stack" noValidate>
        {action.error?.stale && <Problem error={action.error} onReload={onReload} />}
        <div className="field">
          <label htmlFor={`edition-${reference.hid}`}>The new edition</label>
          <input
            id={`edition-${reference.hid}`}
            ref={input}
            type="file"
            disabled={action.busy}
            aria-invalid={refusal || failed ? true : undefined}
            onChange={(event) => chosen(event.target.files)}
          />
          {(refusal || failed) && (
            <p className="field-error" data-testid="edition-refused">
              {refusal || failed}
            </p>
          )}
        </div>
        {sent && <UploadBar sent={sent.sent} total={sent.total} name={file?.name ?? ""} />}
        <p className="actions">
          <button
            type="submit"
            className="primary"
            disabled={action.busy || file === null || refusal !== ""}
          >
            Put the new edition in place
          </button>
        </p>
      </form>
    </section>
  );
}

/** How far a file has got on its way to the server. */
export function UploadBar({ sent, total, name }: { sent: number; total: number; name: string }) {
  const share = total > 0 ? Math.min(100, Math.round((sent / total) * 100)) : 0;
  return (
    <p className="upload-bar">
      <progress
        max={Math.max(total, 1)}
        value={Math.min(sent, total)}
        aria-label={`Sending ${name}`}
      />
      <span className="muted"> {share}%</span>
    </p>
  );
}

/** Put the reference on more records, found by searching: one request for all of them. */
function PutOn({ reference, level, onChanged }: PartProps) {
  const [picked, setPicked] = useState<Offer[]>([]);
  const action = useAction();
  const keys = useRef(new Keys());
  const on = reference.attachments.map((one) => one.record_hid);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const records = picked.map((offer) => offer.hid);
    const result = await action.run(() =>
      withKey(keys.current, `attach ${reference.hid} ${records.join(" ")}`, (idempotencyKey) =>
        api.request("post", "/api/v1/reference-files/{hid}/attachments", {
          path: { hid: reference.hid },
          body: { records },
          idempotencyKey,
        }),
      ),
    );
    if (!result.ok) return;
    setPicked([]);
    onChanged(
      `${result.value.title} is on ${plural(records.length, "more record", "more records")}: ${plural(result.value.attachment_count, "record")} in all.`,
    );
  }

  return (
    <section aria-label="Put on other records">
      <Heading level={level}>Put on other records</Heading>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} />
        <SearchPicker
          label="Find a record"
          hint="A catalog entry by vendor and PID, a region, a site or a location by its path, a circuit or an item by its name."
          noun={["record", "records"]}
          find={findRecords}
          taken={[...on, ...picked.map((offer) => offer.hid)]}
          onPick={(offer) => setPicked((was) => [...was, offer])}
          disabled={action.busy}
        />
        {picked.length > 0 && (
          <ul className="picked" aria-label="Records to put it on">
            {picked.map((offer) => (
              <li key={offer.hid}>
                {offer.label}
                {offer.note && <span className="muted"> {offer.note}</span>}{" "}
                <button
                  type="button"
                  aria-label={`Leave out ${offer.label}`}
                  disabled={action.busy}
                  onClick={() => setPicked((was) => was.filter((one) => one.hid !== offer.hid))}
                >
                  Leave out
                </button>
              </li>
            ))}
          </ul>
        )}
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || picked.length === 0}>
            {picked.length === 0
              ? "Put it on these records"
              : `Put it on ${plural(picked.length, "record")}`}
          </button>
        </p>
      </form>
    </section>
  );
}

/**
 * Take it off the record the page is of. Off the last record it is on, it is erased with
 * its content, which is asked first.
 */
function TakeOff({ reference, here, onChanged, onReload }: ReferenceChangesProps & { here: Here }) {
  const action = useAction();
  const label = `Take off this ${here.what}`;

  async function takeOff() {
    const result = await action.run(() =>
      api.request("delete", "/api/v1/reference-files/{hid}/attachments/{attachment_hid}", {
        path: { hid: reference.hid, attachment_hid: here.attachmentHid },
      }),
    );
    if (!result.ok) return;
    onChanged(
      result.value.erased
        ? `${reference.title} was taken off this ${here.what}, the last record it was on, and erased.`
        : `${reference.title} was taken off this ${here.what}.`,
      true,
    );
  }

  return (
    <div className="stack">
      <Problem error={action.error} onReload={onReload} />
      <p className="hint">
        {reference.attachment_count <= 1
          ? `This ${here.what} is the only record it is on.`
          : `It stays on the ${plural(reference.attachment_count - 1, "other record")} it is on.`}
      </p>
      <div className="actions">
        {reference.attachment_count <= 1 ? (
          <ConfirmButton
            label={label}
            title={`Take ${reference.title} off the last record it is on?`}
            confirmLabel="Take it off and erase it"
            onConfirm={takeOff}
            disabled={action.busy}
          >
            <p>This {here.what} is the only record it is on: taken off, it is erased.</p>
            <p>{erasureText(reference.form, 1)}</p>
          </ConfirmButton>
        ) : (
          <button type="button" onClick={takeOff} disabled={action.busy}>
            {label}
          </button>
        )}
      </div>
    </div>
  );
}

/** Erase it from every record it is on, after saying what that does. */
function Erase({ reference, onChanged, onReload }: ReferenceChangesProps) {
  const action = useAction();

  async function erase() {
    const result = await action.run(() =>
      api.request("delete", "/api/v1/reference-files/{hid}", { path: { hid: reference.hid } }),
    );
    if (result.ok) onChanged(`${reference.title} was erased from every record it was on.`, true);
  }

  return (
    <div className="stack">
      <Problem error={action.error} onReload={onReload} />
      <p className="hint">
        Erased, it goes from {plural(reference.attachment_count, "record")} at once.
      </p>
      <div className="actions">
        <ConfirmButton
          label="Erase"
          title={`Erase ${reference.title}?`}
          confirmLabel="Erase it"
          onConfirm={erase}
          disabled={action.busy}
        >
          <p>{erasureText(reference.form, reference.attachment_count)}</p>
          <RecordsOf reference={reference} />
        </ConfirmButton>
      </div>
    </div>
  );
}
