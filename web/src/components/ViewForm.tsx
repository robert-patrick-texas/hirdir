import { type FormEvent, useState } from "react";
import { parseShort } from "../lib/filter";
import { CheckField, TextField } from "./Field";

/** A view of the items, as the item list has it: a filter and the two switches. */
export interface ItemView {
  /** The item filter, in the short form. Blank is every item. */
  filter: string;
  includeArchived: boolean;
  includeDrafts: boolean;
}

/** The view the address of a page asks for. */
export function viewOfParams(params: URLSearchParams): ItemView {
  return {
    filter: params.get("filter") ?? "",
    includeArchived: params.get("archived") === "1",
    includeDrafts: params.get("drafts") === "1",
  };
}

/** A view as the query of a page's address. What is blank or off is left out. */
export function paramsOfView(view: ItemView): Record<string, string> {
  return {
    ...(view.filter.trim() ? { filter: view.filter.trim() } : {}),
    ...(view.includeArchived ? { archived: "1" } : {}),
    ...(view.includeDrafts ? { drafts: "1" } : {}),
  };
}

interface ItemViewFormProps {
  view: ItemView;
  onShow: (view: ItemView) => void;
  /** What the filter box is called on this page. */
  label: string;
  hint: string;
  /** What each switch adds on this page. */
  archivedHint?: string;
  draftsHint?: string;
}

/**
 * The view a page counts: a filter of the item list, and the two switches of the list.
 * The short form is read here as the server reads it; a filter tree as JSON is the
 * server's to judge.
 */
export function ItemViewForm(props: ItemViewFormProps) {
  const { view, onShow, label, hint, archivedHint, draftsHint } = props;
  const [draft, setDraft] = useState(view.filter);
  const [filterError, setFilterError] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    const typed = draft.trim();
    const parsed = typed.startsWith("{") ? null : parseShort(typed);
    if (parsed && !parsed.ok) {
      setFilterError(parsed.error);
      return;
    }
    setFilterError("");
    onShow({ ...view, filter: typed });
  }

  return (
    <form onSubmit={submit} className="stack" noValidate>
      <div className="inline">
        <TextField
          label={label}
          name="filter"
          type="search"
          value={draft}
          onChange={setDraft}
          autoComplete="off"
          hint={hint}
          error={filterError || undefined}
        />
        <button type="submit">Apply</button>
        <button
          type="button"
          disabled={!view.filter && !draft}
          onClick={() => {
            setDraft("");
            setFilterError("");
            onShow({ ...view, filter: "" });
          }}
        >
          Clear
        </button>
      </div>
      <div className="inline">
        <CheckField
          label="Include archived"
          name="include_archived"
          checked={view.includeArchived}
          onChange={(on) => onShow({ ...view, includeArchived: on })}
          {...(archivedHint ? { hint: archivedHint } : {})}
        />
        <CheckField
          label="Include drafts"
          name="include_drafts"
          checked={view.includeDrafts}
          onChange={(on) => onShow({ ...view, includeDrafts: on })}
          {...(draftsHint ? { hint: draftsHint } : {})}
        />
      </div>
    </form>
  );
}
