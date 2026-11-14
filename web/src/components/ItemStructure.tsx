// The parts of an item's page that say where it stands among other records: the item it
// is in and the minor items in it, the groups it is a member of with its controllers,
// and the item it replaced or was replaced by.

import { type FormEvent, useMemo, useState } from "react";
import { Link } from "react-router";
import { api, type Schemas } from "../api";
import { effectiveLabel, effectiveText, isInherited, sourceHint } from "../lib/effective";
import { itemsPath } from "../lib/filter";
import { itemName, plural, today } from "../lib/format";
import { groupTypeLabel, membershipText } from "../lib/groups";
import { useAction, useLoad } from "../lib/hooks";
import { useEntryOptions } from "../lib/lists";
import { choiceLabel, choiceOptions } from "../lib/options";
import { buildCreate, type FieldSpec, type FormValue, type FormValues, formOf } from "../lib/patch";
import { pickLabel } from "../lib/pick";
import { fieldErrors } from "../lib/problems";
import { SelectField, TextField } from "./Field";
import { FormFields } from "./FormFields";
import { ItemPicker } from "./ItemPicker";
import { NewItem } from "./NewItem";
import { Pager } from "./Pager";
import { Problem } from "./Problem";

type Item = Schemas["ItemOut"];
type ItemRef = Schemas["ItemRef"];
type Choice = Schemas["ChoiceOut"];

const CHILDREN_PAGE = 100;

function itemPath(hid: string): string {
  return `/items/${encodeURIComponent(hid)}`;
}

function Dash() {
  return <span className="muted">—</span>;
}

interface ChangeProps {
  item: Item;
  mayEdit: boolean;
  onChanged: (text: string) => void;
  onReload: () => void;
}

/**
 * The item this one is in, with its position there, and the way to put it in another
 * item or to take it out. Out of every item it is a major item, with what is its own:
 * what it inherited stays with the item it left.
 */
export function Place({ item, mayEdit, onChanged, onReload }: ChangeProps) {
  const { parent } = item;
  const [moving, setMoving] = useState(false);
  const [chosen, setChosen] = useState<Item | null>(null);
  const [position, setPosition] = useState(item.position ?? "");
  const action = useAction();
  const known = ["parent_item_hid", "position"];
  const refused = fieldErrors(action.error, known).shown;
  const name = itemName(item);
  const typed = position.trim();
  const positionChanged = typed !== (item.position ?? "");

  async function save(event: FormEvent) {
    event.preventDefault();
    const body: Schemas["ItemPatch"] = { row_version: item.row_version };
    if (chosen) body.parent_item_hid = chosen.hid;
    if (positionChanged || chosen) body.position = typed === "" ? null : typed;
    const result = await action.run(() =>
      api.request("patch", "/api/v1/items/{hid}", { path: { hid: item.hid }, body }),
    );
    if (!result.ok) return;
    onChanged(
      chosen ? `${name} is now in ${itemName(chosen)}.` : `The position of ${name} was saved.`,
    );
  }

  async function takeOut() {
    const result = await action.run(() =>
      api.request("patch", "/api/v1/items/{hid}", {
        path: { hid: item.hid },
        body: { row_version: item.row_version, parent_item_hid: null, position: null },
      }),
    );
    if (result.ok) onChanged(`${name} was taken out of ${parent ? itemName(parent) : "its item"}.`);
  }

  return (
    <section aria-labelledby="place">
      <h2 id="place">Where it is</h2>
      <dl className="facts" data-testid="place">
        <dt>Major or minor</dt>
        <dd data-testid="major-or-minor">{item.is_major ? "Major item" : "Minor item"}</dd>
        <dt>In</dt>
        <dd data-testid="parent">
          {parent ? <Link to={itemPath(parent.hid)}>{pickLabel(parent)}</Link> : <Dash />}
        </dd>
        <dt>Position</dt>
        <dd data-testid="position">{item.position || <Dash />}</dd>
        {!item.is_major && (
          <>
            <dt>Depth</dt>
            <dd>{String(item.depth)}</dd>
          </>
        )}
      </dl>
      <p className="hint">
        {item.is_major
          ? "A major item is counted, and carries support weight. Put in another item it becomes a minor item of it, and is not."
          : "A minor item is not counted on its own. Left blank, its owner and its standing are those of the item it is in."}
      </p>
      <Problem error={action.error} shown={moving ? known : []} onReload={onReload} />
      {mayEdit && !moving && (
        <p className="actions">
          <button type="button" onClick={() => setMoving(true)}>
            {parent ? "Put in another item, or change the position" : "Put in another item"}
          </button>
          {parent && (
            <button type="button" onClick={takeOut} disabled={action.busy}>
              Take out of {itemName(parent)}
            </button>
          )}
        </p>
      )}
      {mayEdit && moving && (
        <section className="panel" aria-labelledby="move-item">
          <h3 id="move-item">{parent ? "Another item, or another position" : "Put in an item"}</h3>
          <form onSubmit={save} className="stack" noValidate>
            {chosen ? (
              <p data-testid="chosen-parent">
                To be put in <strong>{pickLabel(chosen)}</strong>.{" "}
                <button type="button" onClick={() => setChosen(null)} disabled={action.busy}>
                  Choose another
                </button>
              </p>
            ) : (
              <ItemPicker
                label={parent ? "Another item to put it in" : "The item to put it in"}
                taken={[item.hid, ...(parent ? [parent.hid] : [])]}
                onPick={setChosen}
                disabled={action.busy}
              />
            )}
            {refused.parent_item_hid && <p className="field-error">{refused.parent_item_hid}</p>}
            <div className="fields">
              <TextField
                label="Position"
                name="position"
                value={position}
                onChange={setPosition}
                maxLength={100}
                autoComplete="off"
                disabled={action.busy || (!parent && !chosen)}
                error={refused.position}
                hint="Where in the item it is: PS-A, Slot 3, Bay 7"
              />
            </div>
            <p className="actions">
              <button
                type="submit"
                className="primary"
                disabled={action.busy || (!chosen && !(parent && positionChanged))}
              >
                {chosen ? "Put it there" : "Save position"}
              </button>
              <button
                type="button"
                disabled={action.busy}
                onClick={() => {
                  setMoving(false);
                  setChosen(null);
                  setPosition(item.position ?? "");
                  action.clear();
                }}
              >
                Cancel
              </button>
            </p>
          </form>
        </section>
      )}
    </section>
  );
}

interface MinorItemsProps {
  item: Item;
  states: readonly string[];
  mayEdit: boolean;
  onChanged: (text: string) => void;
}

/** A value in force in a table: lighter, with its source on hover, when it is inherited. */
function InForce({ text, effective }: { text: string; effective: Schemas["EffectiveValue"] }) {
  const inherited = isInherited(effective);
  return (
    <td
      className={inherited ? "inherited" : undefined}
      title={sourceHint(effective) || undefined}
      data-source={effective.source}
    >
      {text || <Dash />}
    </td>
  );
}

/** The minor items directly in this one, by position, and the form that adds one. */
export function MinorItems({ item, states, mayEdit, onChanged }: MinorItemsProps) {
  const [offset, setOffset] = useState(0);
  const [turn, setTurn] = useState(0);
  const [adding, setAdding] = useState(false);
  // The version is in the key: moving this item changes what its minor items show.
  const children = useLoad(`children ${item.hid} ${item.row_version} ${offset} ${turn}`, (signal) =>
    api.request("get", "/api/v1/items/{hid}/children", {
      path: { hid: item.hid },
      query: { limit: CHILDREN_PAGE, offset },
      signal,
    }),
  );
  const rows = children.data?.items ?? [];
  const name = itemName(item);
  const inGrid = itemsPath(`parent_item_hid:eq:${item.hid}`);

  return (
    <section aria-labelledby="minor-items">
      <h2 id="minor-items">Minor items</h2>
      <Problem error={children.error} />
      {children.loading && !children.data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {children.data && rows.length === 0 && (
        <p className="muted">There is no minor item in {name}.</p>
      )}
      {rows.length > 0 && (
        <>
          <div className="scroll">
            <table data-testid="minor-items">
              <caption className="visually-hidden">
                The minor items in {name}, by position, with the standing and owner in force
              </caption>
              <thead>
                <tr>
                  <th scope="col">Position</th>
                  <th scope="col">Name</th>
                  <th scope="col">PID</th>
                  <th scope="col">Serial number</th>
                  <th scope="col">State</th>
                  <th scope="col">Owner</th>
                  <th scope="col">Minor items</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((child) => (
                  <tr
                    key={child.hid}
                    data-item={child.hid}
                    className={child.record_status === "active" ? undefined : "muted"}
                  >
                    <td>{child.position || <Dash />}</td>
                    <th scope="row">
                      <Link to={itemPath(child.hid)}>{itemName(child)}</Link>
                      {child.record_status !== "active" && (
                        <span className="badge">{child.record_status}</span>
                      )}
                    </th>
                    <td>{child.catalog?.pid || <Dash />}</td>
                    <td className="mono">{child.serial_number || <Dash />}</td>
                    <InForce
                      text={effectiveText(child.effective.lifecycle_state)}
                      effective={child.effective.lifecycle_state}
                    />
                    <InForce
                      text={effectiveLabel(child.effective.owner_hid)}
                      effective={child.effective.owner_hid}
                    />
                    <td>{child.minor_items > 0 ? String(child.minor_items) : <Dash />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {children.data && children.data.total > CHILDREN_PAGE && (
            <Pager
              total={children.data.total}
              limit={CHILDREN_PAGE}
              offset={offset}
              noun="minor items"
              onChange={setOffset}
            />
          )}
          <p>
            <Link to={inGrid}>{plural(children.data?.total ?? rows.length, "minor item")}</Link> in
            the grid of items
          </p>
        </>
      )}
      {mayEdit && !adding && (
        <p className="actions">
          <button type="button" onClick={() => setAdding(true)}>
            Add a minor item
          </button>
        </p>
      )}
      {mayEdit && adding && (
        <NewItem
          states={states}
          within={{ hid: item.hid, name }}
          onCancel={() => setAdding(false)}
          onCreated={(made) => {
            setAdding(false);
            setTurn((count) => count + 1);
            onChanged(`${itemName(made)} was added to ${name}.`);
          }}
        />
      )}
    </section>
  );
}

/**
 * The groups an item is a current member of, and for an endpoint its controllers, each
 * with the cluster it is in: a domain may hold several clusters, and an endpoint that
 * fails over between them is a member of the domain alone.
 */
export function Memberships({ item }: { item: Item }) {
  return (
    <section aria-labelledby="groups">
      <h2 id="groups">Groups</h2>
      {item.groups.length === 0 ? (
        <p className="muted">{itemName(item)} is a member of no group.</p>
      ) : (
        <div className="scroll">
          <table className="narrow" data-testid="memberships">
            <caption className="visually-hidden">
              The groups this item is a current member of
            </caption>
            <thead>
              <tr>
                <th scope="col">Group</th>
                <th scope="col">Type</th>
                <th scope="col">As</th>
                <th scope="col">Since</th>
              </tr>
            </thead>
            <tbody>
              {item.groups.map((member) => (
                <tr key={member.hid}>
                  <th scope="row">
                    <Link to={`/groups/${encodeURIComponent(member.group_hid)}`}>
                      {member.name}
                    </Link>
                  </th>
                  <td>{groupTypeLabel(member.type)}</td>
                  <td>{membershipText(member)}</td>
                  <td className="nowrap">{member.joined_on}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {item.controllers.length > 0 && (
        <>
          <h3 id="controllers">Controllers</h3>
          <ul aria-labelledby="controllers" data-testid="controllers">
            {item.controllers.map((controller) => (
              <li key={controller.hid} data-cluster={controller.cluster ?? ""}>
                <Link to={itemPath(controller.hid)}>{pickLabel(controller)}</Link>
                {controller.cluster_hid ? (
                  <span className="muted">
                    {" · in the cluster "}
                    <Link to={`/groups/${encodeURIComponent(controller.cluster_hid)}`}>
                      {controller.cluster ?? "(no name)"}
                    </Link>
                  </span>
                ) : (
                  <span className="muted"> · a controller of the domain itself</span>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function ReplacementFact({
  label,
  other,
  choices,
  testId,
}: {
  label: string;
  other: Schemas["ReplacementRef"];
  choices: readonly Choice[] | undefined;
  testId: string;
}) {
  const named: ItemRef = {
    hid: other.item_hid,
    name: other.name,
    serial_number: other.serial_number,
    asset_tag: null,
    pid: null,
  };
  return (
    <>
      <dt>{label}</dt>
      <dd data-testid={testId}>
        <Link to={itemPath(other.item_hid)}>{pickLabel(named)}</Link> on {other.replaced_on}, for{" "}
        {choiceLabel(choices, "replacement_reason", other.reason)}
        {other.reference && <span className="muted"> · {other.reference}</span>}
      </dd>
    </>
  );
}

interface ReplacementProps extends ChangeProps {
  choices: readonly Choice[] | undefined;
}

/**
 * What this item replaced and what replaced it, and the Replace action. A replacement
 * links the two records and hands over the old item's place in every group it is a
 * current member of. It moves neither item in the lifecycle: that is a move of its own.
 */
export function Replacement({ item, choices, mayEdit, onChanged, onReload }: ReplacementProps) {
  const [open, setOpen] = useState(false);
  const { replaces, replaced_by: replacedBy } = item;
  return (
    <section aria-labelledby="replacement">
      <h2 id="replacement">Replacement</h2>
      {replaces || replacedBy ? (
        <dl className="facts">
          {replaces && (
            <ReplacementFact
              label="Took the place of"
              other={replaces}
              choices={choices}
              testId="replaces"
            />
          )}
          {replacedBy && (
            <ReplacementFact
              label="Replaced by"
              other={replacedBy}
              choices={choices}
              testId="replaced-by"
            />
          )}
        </dl>
      ) : (
        <p className="muted">{itemName(item)} replaced no item, and was not replaced.</p>
      )}
      {mayEdit && !replacedBy && !open && (
        <p className="actions">
          <button type="button" onClick={() => setOpen(true)}>
            Replace this item
          </button>
        </p>
      )}
      {mayEdit && !replacedBy && open && (
        <Replace
          item={item}
          choices={choices}
          onCancel={() => setOpen(false)}
          onChanged={onChanged}
          onReload={onReload}
        />
      )}
    </section>
  );
}

interface ReplaceProps {
  item: Item;
  choices: readonly Choice[] | undefined;
  onCancel: () => void;
  onChanged: (text: string) => void;
  onReload: () => void;
}

const WITH_NEW = "new";
const WITH_EXISTING = "existing";

function Replace({ item, choices, onCancel, onChanged, onReload }: ReplaceProps) {
  const entries = useEntryOptions();
  const [how, setHow] = useState(WITH_EXISTING);
  const [chosen, setChosen] = useState<Item | null>(null);
  const [reason, setReason] = useState("");
  const [reference, setReference] = useState("");
  const [day, setDay] = useState("");
  const specs = useMemo<FieldSpec[]>(
    () => [
      {
        name: "catalog_entry_hid",
        label: "Catalog entry",
        kind: "choice",
        blank: "No catalog entry",
        options: entries.data ?? [],
        hint: "The vendor and PID. A serial number needs one.",
      },
      { name: "serial_number", label: "Serial number", kind: "text", maxLength: 100 },
      { name: "asset_tag", label: "Asset tag", kind: "text", maxLength: 100 },
      { name: "name", label: "Name", kind: "text", maxLength: 200 },
      { name: "hostname", label: "Hostname", kind: "text", maxLength: 255 },
    ],
    [entries.data],
  );
  const [values, setValues] = useState<FormValues>(() => ({
    ...formOf(specs),
    // The same model, more often than not.
    catalog_entry_hid: item.catalog_entry_hid ?? "",
  }));
  const [found, setFound] = useState<Record<string, string>>({});
  const action = useAction();
  const reasons = choiceOptions(choices, "replacement_reason");
  const known = ["reason", "reference", "replaced_on", "new_item_hid"];
  const names = specs.map((spec) => spec.name);
  const errors = fieldErrors(action.error, [...known, ...names]);
  const refused = errors.shown;
  const name = itemName(item);

  function change(field: string, value: FormValue) {
    setValues((was) => ({ ...was, [field]: value }));
    setFound((was) => {
      const { [field]: _, ...rest } = was;
      return rest;
    });
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
    const result = await action.run(() =>
      api.request("post", "/api/v1/items/{hid}/replace", { path: { hid: item.hid }, body }),
    );
    if (result.ok) {
      onChanged(`${name} was replaced by ${itemName(result.value.new_item)}.`);
    }
  }

  const ready = reason !== "" && (how === WITH_NEW || chosen !== null);
  return (
    <section className="panel" aria-labelledby="replace-item">
      <h3 id="replace-item">Replace {name}</h3>
      <p className="hint">
        Both records stay, linked by the replacement. The item that takes the place takes over the
        current memberships of {name}, with the same role and position, from the day of the
        replacement. Neither item is moved in the lifecycle: move {name} to Pending-Removal, or
        where it goes, by a move of its own.
      </p>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={[...known, ...names]} onReload={onReload} />
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
            hint={`Left blank, today: ${today()}`}
          />
          <SelectField
            label="What takes its place"
            name="how"
            value={how}
            onChange={(next) => setHow(next === WITH_NEW ? WITH_NEW : WITH_EXISTING)}
          >
            <option value={WITH_EXISTING}>An item that is in the inventory</option>
            <option value={WITH_NEW}>A new item, created now</option>
          </SelectField>
        </div>
        {how === WITH_EXISTING &&
          (chosen ? (
            <p data-testid="chosen-replacement">
              <strong>{pickLabel(chosen)}</strong> takes its place.{" "}
              <button type="button" onClick={() => setChosen(null)} disabled={action.busy}>
                Choose another
              </button>
            </p>
          ) : (
            <ItemPicker
              label="The item that takes its place"
              taken={[item.hid]}
              onPick={setChosen}
              disabled={action.busy}
            />
          ))}
        {how === WITH_EXISTING && refused.new_item_hid && (
          <p className="field-error">{refused.new_item_hid}</p>
        )}
        {how === WITH_NEW && (
          <fieldset className="plain">
            <legend>The new item</legend>
            <Problem error={entries.error} />
            <FormFields
              specs={specs}
              values={values}
              onChange={change}
              errors={{ ...refused, ...found }}
              disabled={action.busy}
            />
            <p className="hint">
              It needs something to know it by: a serial number with a catalog entry, an asset tag,
              a name or a hostname. The rest is filled in on its own page.
            </p>
          </fieldset>
        )}
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
