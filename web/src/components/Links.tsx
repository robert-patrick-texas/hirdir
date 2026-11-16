// The links of a record on its page: each opens in a new tab and gives the page it opens
// nothing of hirdir's, neither the page it came from nor a hold on this one. The editor
// changes the list whole: links are added, removed and moved, and saved in one change.

import { type FormEvent, useState } from "react";
import { useAction } from "../lib/hooks";
import {
  draftKey,
  draftsOf,
  isWebAddress,
  type Link,
  type LinkDraft,
  type LinkIn,
  linkLabel,
  linksBody,
  MAX_LINKS,
  moved,
  refusedLink,
  sameLinks,
} from "../lib/links";
import { fieldErrors } from "../lib/problems";
import { TextField } from "./Field";
import { Problem } from "./Problem";

interface LinkListProps {
  links: readonly Link[];
  testId?: string;
  /** What to say when there are none. Left out, nothing is said. */
  empty?: string;
}

/** The links in their order, each opening in a new tab. */
export function LinkList({ links, testId = "links", empty }: LinkListProps) {
  if (links.length === 0) {
    return empty ? (
      <p className="muted" data-testid={testId}>
        {empty}
      </p>
    ) : null;
  }
  // The same address may be listed twice: how many times it came before tells them apart.
  const seen = new Map<string, number>();
  const keyed = links.map((link) => {
    const count = (seen.get(link.url) ?? 0) + 1;
    seen.set(link.url, count);
    return { key: `${count} ${link.url}`, link };
  });
  return (
    <ol className="links-list" data-testid={testId}>
      {keyed.map(({ key, link }) => (
        <li key={key} className="link-item">
          {isWebAddress(link.url) ? (
            <a href={link.url} target="_blank" rel="noopener noreferrer">
              {linkLabel(link)}
            </a>
          ) : (
            <span>{linkLabel(link)}</span>
          )}
          {link.text.trim() !== "" && <span className="link-address mono">{link.url}</span>}
        </li>
      ))}
    </ol>
  );
}

interface LinksProps {
  /** The links the record has. */
  links: readonly Link[];
  /** What the record is, for the words of the section: "site", "catalog entry". */
  what: string;
  /** Whether the reader may change them. */
  mayEdit: boolean;
  /** Send the links whole, with the version of the record. */
  save: (links: LinkIn[]) => Promise<unknown>;
  onSaved: () => void;
  /** Read the record again, as when somebody else changed it. */
  onReload: () => void;
  /** The level of the section's heading among those of the page. */
  level?: 2 | 3 | 4;
}

/** A record's own links, and the editor of them for whoever may change the record. */
export function Links(props: LinksProps) {
  const { links, what, mayEdit, save, onSaved, onReload, level = 3 } = props;
  const [editing, setEditing] = useState(false);
  const Heading = level === 2 ? "h2" : level === 3 ? "h3" : "h4";
  return (
    <section aria-labelledby="record-links" data-testid="record-links">
      <Heading id="record-links">Links</Heading>
      {!editing && (
        <>
          <LinkList links={links} empty={`This ${what} has no links.`} />
          {mayEdit && (
            <p className="actions">
              <button type="button" onClick={() => setEditing(true)}>
                {links.length === 0 ? "Add links" : "Change the links"}
              </button>
            </p>
          )}
        </>
      )}
      {editing && (
        <LinksEditor
          links={links}
          save={save}
          onSaved={() => {
            setEditing(false);
            onSaved();
          }}
          onCancel={() => setEditing(false)}
          onReload={onReload}
        />
      )}
    </section>
  );
}

interface LinksEditorProps {
  links: readonly Link[];
  save: (links: LinkIn[]) => Promise<unknown>;
  onSaved: () => void;
  onCancel: () => void;
  onReload: () => void;
}

/** The links as a list to change: add one, remove one, move one, then save them all. */
function LinksEditor({ links, save, onSaved, onCancel, onReload }: LinksEditorProps) {
  const [drafts, setDrafts] = useState<LinkDraft[]>(() =>
    links.length === 0 ? [{ key: draftKey(), url: "", text: "" }] : draftsOf(links),
  );
  const action = useAction();
  const body = linksBody(drafts);
  const unchanged = sameLinks(links, body);
  const refused = fieldErrors(action.error, ["links"]).shown.links;
  // The server names the link it refuses by its number among those sent.
  const sentPlace = refusedLink(refused);
  const sent = drafts.filter((draft) => draft.url.trim() !== "" || draft.text.trim() !== "");
  const refusedKey = sentPlace === null ? null : (sent[sentPlace - 1]?.key ?? null);

  function change(key: string, next: Partial<LinkDraft>) {
    setDrafts((was) => was.map((draft) => (draft.key === key ? { ...draft, ...next } : draft)));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const result = await action.run(() => save(body));
    if (result.ok) onSaved();
  }

  return (
    <form onSubmit={submit} className="stack panel" noValidate aria-label="The links">
      <Problem error={action.error} shown={["links"]} onReload={onReload} />
      <p className="hint">
        Each link is an address that begins with https:// or http://, and the text to show for it;
        with no text, the address itself is shown. They are listed in this order, {MAX_LINKS} at
        most.
      </p>
      {refused && sentPlace === null && (
        <p className="field-error" data-testid="links-refused">
          {refused}
        </p>
      )}
      <ol className="links-editor">
        {drafts.map((draft, place) => {
          const wrong = draft.key === refusedKey ? refused : undefined;
          return (
            <li key={draft.key}>
              <fieldset className="link-draft" data-invalid={wrong ? "true" : undefined}>
                <legend>Link {place + 1}</legend>
                <div className="fields">
                  <TextField
                    label="Address"
                    name={`link-url-${place + 1}`}
                    value={draft.url}
                    onChange={(url) => change(draft.key, { url })}
                    maxLength={2000}
                    autoComplete="off"
                    placeholder="https://"
                    error={wrong}
                    disabled={action.busy}
                  />
                  <TextField
                    label="Text"
                    name={`link-text-${place + 1}`}
                    value={draft.text}
                    onChange={(text) => change(draft.key, { text })}
                    maxLength={200}
                    autoComplete="off"
                    disabled={action.busy}
                  />
                </div>
                <p className="actions">
                  <button
                    type="button"
                    onClick={() => setDrafts((was) => moved(was, place, -1))}
                    disabled={action.busy || place === 0}
                  >
                    Up
                  </button>
                  <button
                    type="button"
                    onClick={() => setDrafts((was) => moved(was, place, 1))}
                    disabled={action.busy || place === drafts.length - 1}
                  >
                    Down
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      setDrafts((was) => was.filter((other) => other.key !== draft.key))
                    }
                    disabled={action.busy}
                  >
                    Remove
                  </button>
                </p>
              </fieldset>
            </li>
          );
        })}
      </ol>
      <p className="actions">
        <button
          type="button"
          onClick={() => setDrafts((was) => [...was, { key: draftKey(), url: "", text: "" }])}
          disabled={action.busy || drafts.length >= MAX_LINKS}
        >
          Add a link
        </button>
      </p>
      <p className="actions">
        <button type="submit" className="primary" disabled={action.busy || unchanged}>
          Save the links
        </button>
        <button type="button" onClick={onCancel} disabled={action.busy}>
          Cancel
        </button>
      </p>
    </form>
  );
}
