import { Fragment, useState } from "react";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { ColourShown } from "../components/ColourPicker";
import { ConfirmButton } from "../components/ConfirmButton";
import { Notice, Problem } from "../components/Problem";
import { CreateForm, EditForm } from "../components/RecordForm";
import { FormRow, useOpeners } from "../components/RowForm";
import { AdminNav } from "../components/Shell";
import { SortTh } from "../components/SortTh";
import { plural } from "../lib/format";
import { useAction, useTitle } from "../lib/hooks";
import { useTags } from "../lib/lists";
import { safeColour } from "../lib/operators";
import type { FieldSpec } from "../lib/patch";
import { allows } from "../lib/roles";
import { useSorting } from "../lib/useSorting";

type Tag = Schemas["TagOut"];

const SPECS: FieldSpec[] = [
  {
    name: "label",
    label: "Label",
    kind: "text",
    required: true,
    maxLength: 100,
    hint: "No semicolon: it separates tags in a file",
  },
  // 0.9.13: chosen from the grid, by the slider or typed, beside the tag as it will show (P-285).
  {
    name: "colour",
    label: "Colour",
    kind: "colour",
    hint: "Press a colour, move the slider, or type one in the form #1f6feb. Blank is no colour.",
    sample: (values) => (typeof values.label === "string" ? values.label : ""),
    sampleAs: "tag",
  },
  { name: "description", label: "Description", kind: "longtext", maxLength: 10000 },
];

/** Admin → Tags: the labels that may be put on records. A tag is made before it is used. */
export function Tags() {
  useTitle("Tags");
  const { user } = useAuth();
  const mayEdit = allows(user.role, "inventory");
  const tags = useTags();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState("");
  const [done, setDone] = useState("");
  const action = useAction();
  const rows = tags.data ?? [];
  const sorting = useSorting(rows, {
    label: (tag) => tag.label,
    colour: (tag) => safeColour(tag.colour),
    description: (tag) => tag.description,
    on: (tag) => tag.uses,
  });
  // 0.9.3: a tag is edited in a form beneath its row, and the focus goes back to its Edit
  // button when the form closes (P-171).
  const openers = useOpeners(tags);

  function close(hid: string, reading = false) {
    setEditing("");
    openers.closed(hid, reading);
  }

  function changed(text: string) {
    setDone(text);
    tags.reload();
  }

  async function remove(tag: Tag) {
    setDone("");
    const result = await action.run(() =>
      api.request("delete", "/api/v1/tags/{hid}", { path: { hid: tag.hid } }),
    );
    if (result.ok) changed(`The tag ${tag.label} was removed.`);
  }

  return (
    <>
      <AdminNav />
      <h1>Tags</h1>
      <p>
        A tag is made here before it is put on a record. A tag that is on any record cannot be
        removed.
      </p>
      {mayEdit && !adding && (
        <p className="actions">
          <button
            type="button"
            className="primary"
            onClick={() => {
              setDone("");
              setAdding(true);
            }}
          >
            New tag
          </button>
        </p>
      )}
      {adding && (
        <CreateForm<Schemas["TagCreate"], Tag>
          title="New tag"
          specs={SPECS}
          create={(body) => api.request("post", "/api/v1/tags", { body })}
          onCreated={(tag) => {
            setAdding(false);
            changed(`The tag ${tag.label} was created.`);
          }}
          onCancel={() => setAdding(false)}
          submitLabel="Create tag"
        />
      )}
      <Problem error={tags.error} />
      <Problem error={action.error} />
      <Notice text={done} />
      {tags.loading && !tags.data && <p role="status">Loading…</p>}
      {tags.data && (
        <div className="scroll">
          <table>
            <caption className="visually-hidden">Tags, by label</caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="label">
                  Label
                </SortTh>
                <SortTh sort={sorting} column="colour">
                  Colour
                </SortTh>
                <SortTh sort={sorting} column="description">
                  Description
                </SortTh>
                <SortTh sort={sorting} column="on">
                  On
                </SortTh>
                {mayEdit && (
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((tag) => (
                <Fragment key={tag.hid}>
                  <tr data-tag={tag.label}>
                    <th scope="row">{tag.label}</th>
                    <td>
                      <ColourShown colour={tag.colour} />
                    </td>
                    <td>{tag.description}</td>
                    <td className="nowrap">{plural(tag.uses, "record")}</td>
                    {mayEdit && (
                      <td className="row-actions">
                        <button
                          type="button"
                          ref={openers.opener(tag.hid)}
                          onClick={() => {
                            setDone("");
                            openers.forget();
                            setEditing(tag.hid);
                          }}
                          aria-label={`Edit the tag ${tag.label}`}
                          aria-expanded={editing === tag.hid}
                        >
                          Edit
                        </button>
                        <ConfirmButton
                          label="Remove"
                          title={`Remove the tag ${tag.label}?`}
                          confirmLabel="Remove tag"
                          onConfirm={() => remove(tag)}
                          disabled={action.busy || tag.uses > 0}
                        >
                          <p>The tag is on no record, and will be gone for good.</p>
                        </ConfirmButton>
                      </td>
                    )}
                  </tr>
                  {mayEdit && editing === tag.hid && (
                    <FormRow of={tag.hid} columns={5}>
                      <TagForm
                        tag={tag}
                        onSaved={() => {
                          close(tag.hid, true);
                          changed(`The tag ${tag.label} was saved.`);
                        }}
                        onClose={() => close(tag.hid)}
                        onReload={tags.reload}
                      />
                    </FormRow>
                  )}
                </Fragment>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={mayEdit ? 5 : 4} className="muted">
                    There are no tags.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

interface TagFormProps {
  tag: Tag;
  onSaved: () => void;
  onClose: () => void;
  onReload: () => void;
}

/** Change a tag: its label, colour and description. */
function TagForm({ tag, onSaved, onClose, onReload }: TagFormProps) {
  return (
    <section className="panel" aria-labelledby="edit-tag" data-testid="tag-form">
      <h2 id="edit-tag">The tag {tag.label}</h2>
      <EditForm<Tag, Schemas["TagPatch"]>
        key={`${tag.hid} ${tag.row_version}`}
        specs={SPECS}
        record={tag}
        save={(body) =>
          api.request("patch", "/api/v1/tags/{hid}", { path: { hid: tag.hid }, body })
        }
        onSaved={onSaved}
        onReload={onReload}
      />
      <p className="actions">
        <button type="button" onClick={onClose}>
          Close
        </button>
      </p>
    </section>
  );
}
