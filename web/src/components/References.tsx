// Files and links: the section of the page of a catalog entry, an item, a region, a
// site, a location and a circuit (P-158 to P-163). The record's own links of 0.7.0 come
// first, where it has them; then its references, grouped by where each comes from: its
// own, then for an item its model's, then each place it is in or at, nearest first. A
// picture is opened in a viewer within the page; every other file is downloaded; a link
// opens in a new tab. With the Inventory role, files are added, chosen or dropped on the
// section, and links; and each reference is changed in a panel of its own.

import {
  type DragEvent,
  type FormEvent,
  Fragment,
  type ReactNode,
  useId,
  useRef,
  useState,
} from "react";
import { Link } from "react-router";
import { api, type Schemas } from "../api";
import { plural } from "../lib/format";
import { toApiError, useAction, useLoad } from "../lib/hooks";
import { Keys, withKey } from "../lib/idempotency";
import { isWebAddress } from "../lib/links";
import { useChoices } from "../lib/lists";
import { choiceLabel } from "../lib/options";
import {
  type FileTypes,
  fileTypesOf,
  firstKind,
  type Group,
  groupsOf,
  type Holder,
  KIND_LIST,
  type Listed,
  limitOf,
  MAX_TITLE,
  picturesOf,
  recordNoun,
  recordPage,
  refusalOf,
  refusedText,
  sizeText,
  sourceKind,
  titleOf,
  tooLarge,
} from "../lib/references";
import { TextAreaField, TextField } from "./Field";
import { PictureViewer } from "./PictureViewer";
import { Notice, Problem } from "./Problem";
import {
  beneath,
  Heading,
  KindField,
  type Level,
  ReferenceChanges,
  UploadBar,
} from "./ReferenceChanges";
import { FormRow, type Openers, useOpeners } from "./RowForm";
import { downloadReference, listReferences } from "./referenceFiles";
import { Time } from "./Time";

type Choice = Schemas["ChoiceOut"];

interface ReferencesProps {
  holder: Holder;
  /** Whether the reader holds the Inventory role. The server checks every change again. */
  mayEdit: boolean;
  /** The level of the section's heading among those of the page. */
  level?: 2 | 3;
  /** The record's own links of 0.7.0, which come first. */
  children?: ReactNode;
}

/** A file chosen to upload, with what it is to be called and how far it has got. */
interface Chosen {
  key: string;
  file: File;
  title: string;
  kind: string;
  /** Ready to send, refused before it was sent, on its way, sent, or refused by the server. */
  state: "ready" | "refused" | "sending" | "done" | "failed";
  reason: string;
  sent: number;
}

let chosenCount = 0;

/** A file as it is chosen: titled, of a first kind, and refused at once where the page can tell. */
function chosenOf(
  file: File,
  holder: Holder,
  kinds: readonly string[],
  types: FileTypes | null,
  limit: number | null,
): Chosen {
  chosenCount += 1;
  const refusal =
    refusalOf(file.name, types?.taken ?? null, types?.refused ?? []) ??
    (limit !== null && file.size > limit ? tooLarge(limit) : null);
  return {
    key: `chosen-${chosenCount}`,
    file,
    title: titleOf(file.name),
    kind: firstKind(holder.kind, file.name, kinds),
    state: refusal ? "refused" : "ready",
    reason: refusal ?? "",
    sent: 0,
  };
}

/** The section Files and links of a record's page. */
export function References({ holder, mayEdit, level = 2, children }: ReferencesProps) {
  const id = useId();
  const sub = beneath(level);
  const what = recordNoun(holder.kind);
  const listed = useLoad(`references ${holder.kind} ${holder.hid}`, (signal) =>
    listReferences(holder, signal),
  );
  const choices = useChoices();
  // The kinds of file taken, for refusing in the page what the server would refuse.
  const types = useLoad(`reference-file-types ${mayEdit}`, async (signal) =>
    mayEdit ? fileTypesOf(await api.request("get", "/api/v1/settings", { signal })) : null,
  );
  const [done, setDone] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [viewing, setViewing] = useState<number | null>(null);
  const [chosen, setChosen] = useState<Chosen[]>([]);
  // The largest file the server takes, once it has said so by refusing a larger one.
  const [limit, setLimit] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const fetching = useAction();
  // 0.9.3: a reference is changed in a form beneath its row, and the focus goes back to
  // its Change button when the form closes (P-171).
  const openers = useOpeners(listed);

  const all = listed.data ?? [];
  const groups = groupsOf(all);
  const own = groups.find((group) => group.source === "own");
  const others = groups.filter((group) => group.source !== "own");
  const pictures = picturesOf(all);
  const kinds = (choices.data ?? [])
    .filter((choice) => choice.list === KIND_LIST && choice.active)
    .map((choice) => choice.value);

  function changed(text: string, gone = false) {
    setDone(text);
    if (gone && open !== null) {
      setOpen(null);
      openers.closed(open, true);
    }
    listed.reload();
  }

  function add(files: readonly File[]) {
    if (files.length === 0) return;
    setDone("");
    const made = files.map((file) => chosenOf(file, holder, kinds, types.data ?? null, limit));
    setChosen((was) => [...was.filter((one) => one.state !== "done"), ...made]);
  }

  function dragOver(event: DragEvent<HTMLElement>) {
    if (!mayEdit || !event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setDragging(true);
  }

  function dragLeave(event: DragEvent<HTMLElement>) {
    const into = event.relatedTarget;
    if (into instanceof Node && event.currentTarget.contains(into)) return;
    setDragging(false);
  }

  function drop(event: DragEvent<HTMLElement>) {
    if (!mayEdit) return;
    event.preventDefault();
    setDragging(false);
    add(Array.from(event.dataTransfer.files));
  }

  async function download(reference: Listed) {
    setDone("");
    await fetching.run(() => downloadReference(reference));
  }

  function rows(group: Group) {
    return (
      <ReferenceTable
        references={group.references}
        choices={choices.data}
        mayEdit={mayEdit}
        open={open}
        opener={openers.opener}
        onOpen={(hid) => {
          setDone("");
          openers.forget();
          setOpen((was) => (was === hid ? null : hid));
        }}
        onView={(reference) => setViewing(pictures.findIndex((one) => one.hid === reference.hid))}
        onDownload={download}
        busy={fetching.busy}
        form={(opened) => (
          <ReferenceChanges
            key={`${opened.hid} ${opened.row_version}`}
            reference={opened}
            here={opened.source === "own" ? { attachmentHid: opened.attachment_hid, what } : null}
            choices={choices.data}
            taken={types.data?.taken ?? null}
            refused={types.data?.refused ?? []}
            level={beneath(sub)}
            onChanged={changed}
            onClose={() => {
              setOpen(null);
              openers.closed(opened.hid);
            }}
            onReload={listed.reload}
          />
        )}
      />
    );
  }

  return (
    <section
      aria-labelledby={id}
      className="references"
      data-testid="files-and-links"
      data-dragging={dragging ? "true" : undefined}
      onDragOver={mayEdit ? dragOver : undefined}
      onDragLeave={mayEdit ? dragLeave : undefined}
      onDrop={mayEdit ? drop : undefined}
    >
      <Heading level={level} id={id}>
        Files and links
      </Heading>
      {children}
      <Problem error={listed.error ?? choices.error ?? types.error} />
      <Problem error={fetching.error} />
      <Notice text={done} />
      {listed.loading && !listed.data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {listed.data && (
        <>
          <section aria-label="Its own" data-testid="references-own" data-source="own">
            <Heading level={sub}>Its own</Heading>
            {own ? (
              rows(own)
            ) : (
              <p className="muted">This {what} has no files or links of its own.</p>
            )}
            {mayEdit && (
              <>
                <AddFiles
                  holder={holder}
                  chosen={chosen}
                  setChosen={setChosen}
                  choices={choices.data}
                  limit={limit}
                  onLimit={setLimit}
                  onChoose={add}
                  onUploaded={(text) => changed(text)}
                  level={beneath(sub)}
                />
                <AddLink
                  holder={holder}
                  choices={choices.data}
                  onAdded={(text) => changed(text)}
                  level={beneath(sub)}
                />
              </>
            )}
          </section>
          {others.map((group) => (
            <section
              key={group.sourceHid}
              aria-label={group.label}
              data-testid="references-from"
              data-source={group.source}
              data-source-hid={group.sourceHid}
            >
              <Heading level={sub}>
                {group.source === "catalog" ? "Of its model, " : ""}
                <Link to={recordPage(sourceKind(group.source, holder.kind), group.sourceHid)}>
                  {group.label}
                </Link>
              </Heading>
              {rows(group)}
            </section>
          ))}
        </>
      )}
      <PictureViewer
        pictures={pictures}
        at={viewing !== null && viewing >= 0 ? viewing : null}
        onMove={setViewing}
        onClose={() => setViewing(null)}
      />
    </section>
  );
}

interface ReferenceTableProps {
  references: readonly Listed[];
  choices: readonly Choice[] | undefined;
  mayEdit: boolean;
  /** The reference whose form is open beneath its row, if any. */
  open: string | null;
  /** The ref of the Change button of a reference, which the focus goes back to. */
  opener: Openers["opener"];
  onOpen: (hid: string) => void;
  /** The form of a reference, shown beneath its row while it is open. */
  form: (reference: Listed) => ReactNode;
  onView: (reference: Listed) => void;
  onDownload: (reference: Listed) => void;
  busy: boolean;
}

/**
 * The references of one record, each with its title, kind, size or address, and who added
 * it. 0.9.3: the form of the one that is open is a row of its own beneath its row (P-171).
 */
function ReferenceTable(props: ReferenceTableProps) {
  const { references, choices, mayEdit, open, opener, onOpen, onView, onDownload, busy } = props;
  const { form } = props;
  return (
    <div className="scroll">
      <table className="references-table">
        <thead>
          <tr>
            <th scope="col">Title</th>
            <th scope="col">Kind</th>
            <th scope="col">Size or address</th>
            <th scope="col">Added</th>
            <th scope="col">
              <span className="visually-hidden">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {references.map((reference) => (
            <Fragment key={reference.hid}>
              <tr
                data-reference={reference.hid}
                data-title={reference.title}
                data-form={reference.form}
              >
                <th scope="row">
                  {reference.form === "link" && reference.url && isWebAddress(reference.url) ? (
                    <a href={reference.url} target="_blank" rel="noopener noreferrer">
                      {reference.title}
                    </a>
                  ) : (
                    reference.title
                  )}
                  {reference.content_missing && <span className="badge">Content missing</span>}
                  {reference.notes && (
                    <span className="reference-notes muted">{reference.notes}</span>
                  )}
                </th>
                <td data-testid="reference-kind">
                  {choiceLabel(choices, KIND_LIST, reference.kind)}
                </td>
                <td>
                  {reference.form === "file" ? (
                    <>
                      <span data-testid="reference-size">{sizeText(reference.size_bytes)}</span>
                      <span className="reference-file mono">{reference.file_name}</span>
                    </>
                  ) : (
                    <span className="mono reference-address">{reference.url}</span>
                  )}
                </td>
                <td className="nowrap">
                  {reference.created_by_name ?? <span className="muted">—</span>}
                  <span className="reference-added">
                    <Time at={reference.created_at} />
                  </span>
                </td>
                <td className="row-actions">
                  {reference.form === "file" && reference.content_missing && (
                    <span className="muted">
                      Not downloadable: its content was not restored with the backup it came from.
                    </span>
                  )}
                  {reference.form === "file" && !reference.content_missing && (
                    <>
                      {reference.shown_in_page && (
                        <button
                          type="button"
                          aria-label={`View ${reference.title}`}
                          onClick={() => onView(reference)}
                        >
                          View
                        </button>
                      )}
                      <button
                        type="button"
                        aria-label={`Download ${reference.title}`}
                        disabled={busy}
                        onClick={() => onDownload(reference)}
                      >
                        Download
                      </button>
                    </>
                  )}
                  {mayEdit && (
                    <button
                      type="button"
                      ref={opener(reference.hid)}
                      aria-label={`Change ${reference.title}`}
                      aria-expanded={open === reference.hid}
                      onClick={() => onOpen(reference.hid)}
                    >
                      Change
                    </button>
                  )}
                </td>
              </tr>
              {mayEdit && open === reference.hid && (
                <FormRow of={reference.hid} columns={5}>
                  {form(reference)}
                </FormRow>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface AddFilesProps {
  holder: Holder;
  chosen: readonly Chosen[];
  setChosen: (change: (was: Chosen[]) => Chosen[]) => void;
  choices: readonly Choice[] | undefined;
  limit: number | null;
  onLimit: (limit: number) => void;
  onChoose: (files: readonly File[]) => void;
  onUploaded: (text: string) => void;
  level: Level;
}

/**
 * Add files: one or several, chosen here or dropped on the section, each with its title
 * and kind. They are sent one after another, each with a bar of how far it has got; one
 * that is refused says why, and the others go on.
 */
function AddFiles(props: AddFilesProps) {
  const { holder, chosen, setChosen, choices, limit, onLimit, onChoose, onUploaded, level } = props;
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [missing, setMissing] = useState<Set<string>>(new Set());
  const ready = chosen.filter((one) => one.state === "ready");

  function change(key: string, next: Partial<Chosen>) {
    setChosen((was) => was.map((one) => (one.key === key ? { ...one, ...next } : one)));
  }

  async function upload(event: FormEvent) {
    event.preventDefault();
    const wanting = new Set(
      ready.filter((one) => one.title.trim() === "" || one.kind === "").map((one) => one.key),
    );
    setMissing(wanting);
    if (wanting.size > 0 || ready.length === 0) return;
    setBusy(true);
    let largest = limit;
    let sent = 0;
    let refused = 0;
    for (const one of ready) {
      if (largest !== null && one.file.size > largest) {
        change(one.key, { state: "refused", reason: tooLarge(largest) });
        refused += 1;
        continue;
      }
      change(one.key, { state: "sending", sent: 0 });
      try {
        await api.sendFile("post", "/api/v1/reference-files", {
          query: {
            title: one.title.trim(),
            kind: one.kind,
            file_name: one.file.name,
            attach_to: [holder.hid],
          },
          file: one.file,
          onProgress: (progress) => change(one.key, { sent: progress.sent }),
        });
        change(one.key, { state: "done", sent: one.file.size });
        sent += 1;
      } catch (thrown) {
        const error = toApiError(thrown);
        if (error.status === 413) {
          const named = limitOf(error.message);
          if (named !== null) {
            largest = named;
            onLimit(named);
          }
        }
        change(one.key, { state: "failed", reason: refusedText(error) });
        refused += 1;
        // Signed out, or the server gone: the rest would fare no better.
        if (error.status === 401 || error.status === 0) break;
      }
    }
    setBusy(false);
    setChosen((was) => was.filter((one) => one.state !== "done"));
    const parts = [
      sent > 0 ? `${plural(sent, "file was", "files were")} uploaded` : "",
      refused > 0
        ? `${plural(refused, "file was", "files were")} refused, and ${refused === 1 ? "says" : "say"} why`
        : "",
    ].filter(Boolean);
    if (parts.length > 0) onUploaded(`${parts.join("; ")}.`);
  }

  return (
    <section aria-label="Add files" className="add-files">
      <Heading level={level}>Add files</Heading>
      <form onSubmit={upload} className="stack" noValidate>
        <div className="field drop-hint">
          <label htmlFor={`${holder.hid}-files`}>Choose files</label>
          <input
            id={`${holder.hid}-files`}
            ref={input}
            type="file"
            multiple
            disabled={busy}
            onChange={(event) => {
              onChoose(Array.from(event.target.files ?? []));
              event.target.value = "";
            }}
          />
          <p className="hint">
            One or several, or drop them on this section. Each is given a title, which starts as its
            name, and a kind. A picture is shown in the page; every other file is downloaded.
          </p>
        </div>
        {chosen.length > 0 && (
          <ol className="chosen-files" aria-label="Files to upload">
            {chosen.map((one) => (
              <li key={one.key} data-file={one.file.name} data-state={one.state}>
                <fieldset className="chosen-file">
                  <legend>
                    <span className="mono">{one.file.name}</span>{" "}
                    <span className="muted">{sizeText(one.file.size)}</span>
                  </legend>
                  {(one.state === "ready" || one.state === "sending") && (
                    <div className="fields">
                      <TextField
                        label="Title"
                        name={`${one.key}-title`}
                        value={one.title}
                        onChange={(title) => change(one.key, { title })}
                        required
                        maxLength={MAX_TITLE}
                        autoComplete="off"
                        disabled={busy}
                        error={
                          missing.has(one.key) && one.title.trim() === ""
                            ? "Give it a title."
                            : undefined
                        }
                      />
                      <KindField
                        choices={choices}
                        name={`${one.key}-kind`}
                        value={one.kind}
                        onChange={(kind) => change(one.key, { kind })}
                        disabled={busy}
                        error={
                          missing.has(one.key) && one.kind === "" ? "Choose its kind." : undefined
                        }
                      />
                    </div>
                  )}
                  {one.state === "sending" && (
                    <UploadBar sent={one.sent} total={one.file.size} name={one.file.name} />
                  )}
                  {(one.state === "refused" || one.state === "failed") && (
                    <p className="field-error" data-testid="file-refused">
                      {one.reason}
                    </p>
                  )}
                  {one.state !== "sending" && (
                    <p className="actions">
                      <button
                        type="button"
                        aria-label={`Leave out ${one.file.name}`}
                        disabled={busy}
                        onClick={() =>
                          setChosen((was) => was.filter((other) => other.key !== one.key))
                        }
                      >
                        {one.state === "ready" ? "Leave out" : "Clear"}
                      </button>
                    </p>
                  )}
                </fieldset>
              </li>
            ))}
          </ol>
        )}
        {(ready.length > 0 || busy) && (
          <p className="actions">
            <button type="submit" className="primary" disabled={busy || ready.length === 0}>
              {busy ? "Uploading…" : `Upload ${plural(ready.length, "file")}`}
            </button>
          </p>
        )}
      </form>
    </section>
  );
}

interface AddLinkProps {
  holder: Holder;
  choices: readonly Choice[] | undefined;
  onAdded: (text: string) => void;
  level: Level;
}

/** Add a link to a file kept elsewhere: its title, its kind and its address. */
function AddLink({ holder, choices, onAdded, level }: AddLinkProps) {
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState("");
  const [url, setUrl] = useState("");
  const [notes, setNotes] = useState("");
  const action = useAction();
  const keys = useRef(new Keys());

  function reset() {
    setTitle("");
    setKind("");
    setUrl("");
    setNotes("");
    action.clear();
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const body: Schemas["ReferenceLinkNew"] = {
      title: title.trim(),
      kind,
      url: url.trim(),
      notes: notes.trim() === "" ? null : notes.trim(),
      attach_to: [holder.hid],
    };
    const result = await action.run(() =>
      withKey(keys.current, JSON.stringify(body), (idempotencyKey) =>
        api.request("post", "/api/v1/reference-files/links", { body, idempotencyKey }),
      ),
    );
    if (!result.ok) return;
    reset();
    setAdding(false);
    onAdded(`The link ${result.value.title} was added.`);
  }

  if (!adding) {
    return (
      <p className="actions">
        <button type="button" onClick={() => setAdding(true)}>
          Add a link
        </button>
      </p>
    );
  }
  const shown = ["title", "kind", "url", "notes"];
  return (
    <section aria-label="Add a link" className="panel">
      <Heading level={level}>Add a link</Heading>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={shown} />
        <p className="hint">
          A link to a file kept elsewhere, as on a vendor's site: it opens in a new tab.
        </p>
        <div className="fields">
          <TextField
            label="Title"
            name="link-title"
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
            name="link-kind"
            value={kind}
            onChange={setKind}
            disabled={action.busy}
            error={action.error?.fields.kind}
          />
          <TextField
            label="Address"
            name="link-url"
            value={url}
            onChange={setUrl}
            required
            maxLength={2000}
            autoComplete="off"
            placeholder="https://"
            disabled={action.busy}
            error={action.error?.fields.url}
          />
          <TextAreaField
            label="Notes"
            name="link-notes"
            value={notes}
            onChange={setNotes}
            maxLength={10_000}
            disabled={action.busy}
            error={action.error?.fields.notes}
          />
        </div>
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy}>
            Add the link
          </button>
          <button
            type="button"
            disabled={action.busy}
            onClick={() => {
              reset();
              setAdding(false);
            }}
          >
            Cancel
          </button>
        </p>
      </form>
    </section>
  );
}
