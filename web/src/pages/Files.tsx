// Admin › Files: every reference of the inventory, a file kept by hirdir or a link to
// one kept elsewhere (P-162), sorted and paged by the server and narrowed by kind, by
// form and by what the title holds. Each row leads to the records it is on and offers
// its download. Every role sees the page, as it sees the Admin area; the changes are for
// the Inventory role, and the server checks the role of each.

import { type FormEvent, useState } from "react";
import { useSearchParams } from "react-router";
import { api } from "../api";
import { useAuth } from "../auth";
import { SelectField, TextField } from "../components/Field";
import { Pager, toOffset } from "../components/Pager";
import { Notice, Problem } from "../components/Problem";
import { RecordsOf, ReferenceChanges } from "../components/ReferenceChanges";
import { downloadReference } from "../components/referenceFiles";
import { AdminNav } from "../components/Shell";
import { SortTh } from "../components/SortTh";
import { Time } from "../components/Time";
import { plural } from "../lib/format";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { isWebAddress } from "../lib/links";
import { useChoices } from "../lib/lists";
import { choiceFilterOptions, choiceLabel } from "../lib/options";
import { fileTypesOf, KIND_LIST, type Reference, sizeText } from "../lib/references";
import { allows } from "../lib/roles";
import { REFERENCES_SORT } from "../lib/tableSorts";
import { useServerSort } from "../lib/useServerSort";

const PAGE = 50;

type Form = "file" | "link";

function formOf(text: string | null): Form | "" {
  return text === "file" || text === "link" ? text : "";
}

interface Narrowed {
  kind: string;
  form: Form | "";
  title: string;
  offset: number;
}

/** Admin › Files. */
export function Files() {
  useTitle("Files");
  const { user } = useAuth();
  const mayEdit = allows(user.role, "inventory");
  const [params, setParams] = useSearchParams();
  const kind = params.get("kind") ?? "";
  const form = formOf(params.get("form"));
  const title = params.get("title") ?? "";
  const offset = toOffset(params.get("offset"));
  const [wantedKind, setWantedKind] = useState(kind);
  const [wantedForm, setWantedForm] = useState<string>(form);
  const [wantedTitle, setWantedTitle] = useState(title);
  const [open, setOpen] = useState<string | null>(null);
  const [done, setDone] = useState("");
  const fetching = useAction();
  const choices = useChoices();
  const types = useLoad(`reference-file-types ${mayEdit}`, async (signal) =>
    mayEdit ? fileTypesOf(await api.request("get", "/api/v1/settings", { signal })) : null,
  );
  const sort = useServerSort<Reference>({
    fields: REFERENCES_SORT,
    onChange: () => {
      if (offset > 0) show({ kind, form, title, offset: 0 });
    },
  });
  const list = sort.held(
    useLoad(`reference-files ${offset} ${kind} ${form} ${title} ${sort.param ?? ""}`, (signal) =>
      api.request("get", "/api/v1/reference-files", {
        query: {
          kind: kind || null,
          form: form || null,
          title: title || null,
          ...sort.query,
          limit: PAGE,
          offset,
        },
        signal,
      }),
    ),
  );
  const items = list.data?.items ?? [];
  const holdsAll = list.data ? list.data.total === items.length : false;
  const opened = items.find((one) => one.hid === open);
  const narrowed = kind !== "" || form !== "" || title !== "";

  function show(next: Narrowed) {
    const wanted = new URLSearchParams();
    if (next.kind) wanted.set("kind", next.kind);
    if (next.form) wanted.set("form", next.form);
    if (next.title) wanted.set("title", next.title);
    if (next.offset > 0) wanted.set("offset", String(next.offset));
    setParams(wanted);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    show({ kind: wantedKind, form: formOf(wantedForm), title: wantedTitle.trim(), offset: 0 });
  }

  function clear() {
    setWantedKind("");
    setWantedForm("");
    setWantedTitle("");
    show({ kind: "", form: "", title: "", offset: 0 });
  }

  function changed(text: string, gone = false) {
    setDone(text);
    if (gone) setOpen(null);
    list.reload();
  }

  async function download(reference: Reference) {
    setDone("");
    await fetching.run(() => downloadReference(reference));
  }

  return (
    <>
      <AdminNav />
      <h1>Files</h1>
      <p>
        Every reference of the inventory: a file that hirdir keeps, or a link to one kept elsewhere,
        each on the records it is listed with. A picture is shown on the page of a record it is on;
        every other file is downloaded.
      </p>
      <form onSubmit={submit} className="inline" aria-label="Narrow the files">
        <SelectField label="Kind" name="kind" value={wantedKind} onChange={setWantedKind}>
          <option value="">Any kind</option>
          {choiceFilterOptions(choices.data, KIND_LIST).map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </SelectField>
        <SelectField label="Form" name="form" value={wantedForm} onChange={setWantedForm}>
          <option value="">Files and links</option>
          <option value="file">Files</option>
          <option value="link">Links</option>
        </SelectField>
        <TextField
          label="Title holds"
          name="title"
          type="search"
          value={wantedTitle}
          onChange={setWantedTitle}
          maxLength={200}
          autoComplete="off"
        />
        <button type="submit">Filter</button>
        <button
          type="button"
          onClick={clear}
          disabled={!narrowed && !wantedKind && !wantedForm && !wantedTitle}
        >
          Clear
        </button>
      </form>
      <Problem error={list.error ?? choices.error ?? types.error} />
      <Problem error={fetching.error} />
      <Notice text={done} />
      {list.loading && !list.data && <p role="status">Loading…</p>}
      {list.data && (
        <>
          <div className="scroll">
            <table data-testid="reference-files">
              <caption className="visually-hidden">
                Every reference, by title until a header is clicked
              </caption>
              <thead>
                <tr>
                  <SortTh sort={sort.header("title", holdsAll)} column="title">
                    Title
                  </SortTh>
                  <SortTh sort={sort.header("kind", holdsAll)} column="kind">
                    Kind
                  </SortTh>
                  <SortTh sort={sort.header("form", holdsAll)} column="form">
                    Form
                  </SortTh>
                  <SortTh sort={sort.header("file_name", holdsAll)} column="file_name">
                    File name
                  </SortTh>
                  <SortTh sort={sort.header("size", holdsAll)} column="size">
                    Size
                  </SortTh>
                  <SortTh sort={sort.header("records", holdsAll)} column="records">
                    Records
                  </SortTh>
                  <SortTh sort={sort.header("added", holdsAll)} column="added">
                    Added
                  </SortTh>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {sort.arrange(items, holdsAll).map((reference) => (
                  <tr
                    key={reference.hid}
                    data-reference={reference.hid}
                    data-title={reference.title}
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
                    </th>
                    <td>{choiceLabel(choices.data, KIND_LIST, reference.kind)}</td>
                    <td>{reference.form === "file" ? "File" : "Link"}</td>
                    <td className="mono">
                      {reference.file_name ?? (
                        <span className="reference-address">{reference.url}</span>
                      )}
                    </td>
                    <td className="nowrap">{sizeText(reference.size_bytes)}</td>
                    <td>
                      <details>
                        <summary>{plural(reference.attachment_count, "record")}</summary>
                        <RecordsOf reference={reference} />
                      </details>
                    </td>
                    <td className="nowrap">
                      {reference.created_by_name ?? <span className="muted">—</span>}
                      <span className="reference-added">
                        <Time at={reference.created_at} />
                      </span>
                    </td>
                    <td className="row-actions">
                      {reference.form === "file" && !reference.content_missing && (
                        <button
                          type="button"
                          aria-label={`Download ${reference.title}`}
                          disabled={fetching.busy}
                          onClick={() => download(reference)}
                        >
                          Download
                        </button>
                      )}
                      {mayEdit && (
                        <button
                          type="button"
                          aria-label={`Change ${reference.title}`}
                          aria-expanded={open === reference.hid}
                          onClick={() => {
                            setDone("");
                            setOpen((was) => (was === reference.hid ? null : reference.hid));
                          }}
                        >
                          Change
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {items.length === 0 && (
                  <tr>
                    <td colSpan={8} className="muted">
                      {narrowed ? "No reference matches." : "There are no references yet."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Pager
            total={list.data.total}
            limit={PAGE}
            offset={offset}
            noun="references"
            onChange={(next) => show({ kind, form, title, offset: next })}
          />
          {mayEdit && opened && (
            <ReferenceChanges
              key={`${opened.hid} ${opened.row_version}`}
              reference={opened}
              choices={choices.data}
              taken={types.data?.taken ?? null}
              refused={types.data?.refused ?? []}
              level={2}
              onChanged={changed}
              onClose={() => setOpen(null)}
              onReload={list.reload}
            />
          )}
        </>
      )}
    </>
  );
}
