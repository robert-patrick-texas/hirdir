import { useState } from "react";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { ConfirmButton } from "../components/ConfirmButton";
import { Notice, Problem } from "../components/Problem";
import { CreateForm, EditForm } from "../components/RecordForm";
import { AdminNav } from "../components/Shell";
import { plural } from "../lib/format";
import { useAction, useTitle } from "../lib/hooks";
import { useTags } from "../lib/lists";
import type { FieldSpec } from "../lib/patch";
import { allows } from "../lib/roles";

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
  { name: "colour", label: "Colour", kind: "text", maxLength: 7, hint: "In the form #1f6feb" },
  { name: "description", label: "Description", kind: "longtext", maxLength: 10000 },
];

/** A tag's colour as a small square. The colour is checked before it is used as one. */
function Swatch({ colour }: { colour: string | null }) {
  if (!colour || !/^#[0-9a-f]{6}$/i.test(colour)) return <span className="muted">—</span>;
  return (
    <>
      <span className="swatch" style={{ backgroundColor: colour }} aria-hidden="true" />{" "}
      <span className="mono">{colour}</span>
    </>
  );
}

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
  const open = rows.find((tag) => tag.hid === editing) ?? null;

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
                <th scope="col">Label</th>
                <th scope="col">Colour</th>
                <th scope="col">Description</th>
                <th scope="col">On</th>
                {mayEdit && (
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((tag) => (
                <tr key={tag.hid}>
                  <th scope="row">{tag.label}</th>
                  <td>
                    <Swatch colour={tag.colour} />
                  </td>
                  <td>{tag.description}</td>
                  <td className="nowrap">{plural(tag.uses, "record")}</td>
                  {mayEdit && (
                    <td className="row-actions">
                      <button
                        type="button"
                        onClick={() => {
                          setDone("");
                          setEditing(tag.hid);
                        }}
                        aria-label={`Edit the tag ${tag.label}`}
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
      {mayEdit && open && (
        <section className="panel" aria-labelledby="edit-tag">
          <h2 id="edit-tag">The tag {open.label}</h2>
          <EditForm<Tag, Schemas["TagPatch"]>
            key={`${open.hid} ${open.row_version}`}
            specs={SPECS}
            record={open}
            save={(body) =>
              api.request("patch", "/api/v1/tags/{hid}", { path: { hid: open.hid }, body })
            }
            onSaved={() => {
              setEditing("");
              changed(`The tag ${open.label} was saved.`);
            }}
            onReload={tags.reload}
          />
          <p className="actions">
            <button type="button" onClick={() => setEditing("")}>
              Close
            </button>
          </p>
        </section>
      )}
    </>
  );
}
