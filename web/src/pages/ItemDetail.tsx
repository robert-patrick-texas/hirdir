import { type FormEvent, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { Addresses, ManagementAddresses } from "../components/Addresses";
import { BringBackElsewhere, refusedForItsPlace } from "../components/BringBack";
import { ConnectedCircuits } from "../components/CircuitConnections";
import { ConfirmButton } from "../components/ConfirmButton";
import { ItemCoverage } from "../components/Coverage";
import { FromAbove, InheritedFrom, OwnerNote, PlaceNote } from "../components/Descent";
import { CheckField, SelectField } from "../components/Field";
import { HealthWithReasons, Observation, ObservedText } from "../components/Health";
import { WhatRunsOnIt } from "../components/Hosted";
import { HostFacts } from "../components/HostFacts";
import { Memberships, MinorItems, Place, Replacement } from "../components/ItemStructure";
import { LinkList } from "../components/Links";
import { MinorLine } from "../components/MinorLine";
import { Operator, OperatorNote } from "../components/Operator";
import { Pager } from "../components/Pager";
import { Notice, Problem } from "../components/Problem";
import { ItemPurchaseLine } from "../components/PurchaseLine";
import { EditForm } from "../components/RecordForm";
import { References } from "../components/References";
import { Registrations } from "../components/Registrations";
import { DeleteRecord, useHostedQuestion } from "../components/Removal";
import { SortTh } from "../components/SortTh";
import { StackFacts } from "../components/StackMember";
import { Time } from "../components/Time";
import { ValueLink } from "../components/ValueLink";
// 0.8.0: a default and a minimum of the support weight of a major item (P-155).
import { Raised } from "../components/Weight";
import { WhyEachValue } from "../components/WhyEachValue";
import { aboveItem, descentHint, isFromAbove, knownAbove, ownerSource } from "../lib/descent";
import {
  effectiveLabel,
  effectiveText,
  inheritHint,
  isInherited,
  sourceHint,
  sourceLabel,
} from "../lib/effective";
import { formatMac, formatValue, itemName } from "../lib/format";
import { CONDITION_LIST } from "../lib/health";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { HOST_FIELD, hostPath, hostSpecs, hostValue, sentHost } from "../lib/hosting";
import {
  DISPOSITIONS,
  dispositionsIn,
  intentChoices,
  mayBeOnline,
  mayInheritAgain,
  nextStates,
  onlineText,
  type Rule,
  standingChoices,
  standingOf,
  stateNames,
} from "../lib/lifecycle";
import { useChoices, useOwnerOptions, useRules, useTags, withCurrent } from "../lib/lists";
import { operatorOptionLabel } from "../lib/operators";
import {
  CATALOG_KINDS,
  choiceLabel,
  choiceOptions,
  optionLabel,
  RECORD_STATUSES,
  SETTABLE_STATUSES,
} from "../lib/options";
import { ownerOption } from "../lib/owners";
import type { FieldSpec } from "../lib/patch";
import { entryLabel, entrySeen, pickLabel } from "../lib/pick";
import { itemsWithin, placePath } from "../lib/places";
import { fieldErrors } from "../lib/problems";
import { itemRetiredText } from "../lib/removal";
import { allows } from "../lib/roles";
import { dateValue, decimalValue } from "../lib/sort";
import type { SaidPart } from "../lib/stacks";
import { HISTORY_SORT } from "../lib/tableSorts";
import { useServerSort } from "../lib/useServerSort";
import { useSorting } from "../lib/useSorting";
// 0.8.0: the default of a major item names its setting (P-155).
import { raisedText, weightSource } from "../lib/weights";

type Item = Schemas["ItemOut"];
type Choice = Schemas["ChoiceOut"];
/** The fields an item inherits from its catalog entry. */
type Inherited =
  | "est_value"
  | "support_weight"
  | "annual_support_cost"
  | "end_of_sale"
  | "end_of_sw_support"
  | "end_of_hw_support"
  | "ldos";

const HISTORY_PAGE = 50;

/** Those fields as people read them. */
const INHERITED: ReadonlyArray<[field: Inherited, label: string]> = [
  ["est_value", "Estimated value"],
  ["support_weight", "Support weight"],
  ["annual_support_cost", "Annual support cost"],
  ["end_of_sale", "End of sale"],
  ["end_of_sw_support", "End of software support"],
  ["end_of_hw_support", "End of hardware support"],
  ["ldos", "Last day of support (LDoS)"],
];

/**
 * What the page lists among the values in force: those above, and the flag not to renew,
 * which is yes or no, the item's own word or its model's (D-169, D-182).
 */
type InForceField = Inherited | "do_not_renew";
const IN_FORCE: ReadonlyArray<[field: InForceField, label: string]> = [
  ...INHERITED,
  ["do_not_renew", "Not to be renewed"],
];

// Those of them that are dates. The rest are decimals, as the server writes them.
const INHERITED_DATES: ReadonlySet<Inherited> = new Set([
  "end_of_sale",
  "end_of_sw_support",
  "end_of_hw_support",
  "ldos",
]);

function Dash() {
  return <span className="muted">—</span>;
}

/**
 * What to say under the flag not to renew on the form of an item: its own word, or what
 * its model says, which a blank has. A renewal of a contract leaves an item behind whose
 * flag is in force: its coverage ends with the present term.
 */
function notRenewedHint(item: Item): string {
  const inForce = item.effective.do_not_renew;
  const what =
    "Yes is for an item whose support is not bought again when its contract is renewed: a renewal leaves it behind, its coverage ending with the present term, and with no cover it is no gap.";
  if (item.do_not_renew !== null && item.do_not_renew !== undefined) {
    return `${what} Set here. "As its model says" has its model's again.`;
  }
  if (inForce.source === "catalog") {
    return `${what} Blank has its model's: ${effectiveText(inForce)}.`;
  }
  return `${what} Blank, and its model says nothing: No.`;
}

/** Items → one item: what it is, the values in force, its standing, and its history. */
export function ItemDetail() {
  const { hid = "" } = useParams();
  const { user } = useAuth();
  const mayEdit = allows(user.role, "inventory");
  const item = useLoad(`item ${hid}`, (signal) =>
    api.request("get", "/api/v1/items/{hid}", { path: { hid }, signal }),
  );
  const choices = useChoices();
  const rules = useRules();
  // 0.9.8: what was done, and the same in parts with records as links (P-242).
  const [done, setDone] = useState<{ text: string; parts?: SaidPart[] }>({ text: "" });
  const states = useMemo(() => stateNames(rules.data ?? []), [rules.data]);
  useTitle(item.data ? itemName(item.data) : "Item");

  function changed(text: string, parts?: SaidPart[]) {
    setDone(parts ? { text, parts } : { text });
    item.reload();
  }

  const record = item.data;
  return (
    <>
      <p className="crumbs">
        <Link to="/items">Items</Link>
      </p>
      <h1>
        {record ? itemName(record) : "Item"}
        {record && record.record_status !== "active" && (
          <span className="badge">{optionLabel(RECORD_STATUSES, record.record_status)}</span>
        )}
      </h1>
      {/* 0.9.6: what a minor item is and where, under its heading (P-216). */}
      {record && <MinorLine item={record} choices={choices.data} />}
      {/* 0.9.5: links to the sections of the page that are on it (P-189). */}
      {record && <SectionLinks version={`${record.hid} ${record.row_version}`} />}
      <Problem error={item.error} />
      <Problem error={choices.error ?? rules.error} />
      <Notice {...done} />
      {item.loading && !record && <p role="status">Loading…</p>}
      {record && (
        <>
          <Facts
            item={record}
            choices={choices.data}
            mayChange={mayEdit && record.record_status !== "retired"}
            onChanged={changed}
          />
          <Doing
            key={`doing ${record.hid} ${record.row_version}`}
            item={record}
            choices={choices.data}
            mayEdit={mayEdit && record.record_status !== "retired"}
            onChanged={changed}
            onReload={item.reload}
          />
          <Place
            key={`place ${record.hid} ${record.row_version}`}
            item={record}
            mayEdit={mayEdit && record.record_status !== "retired"}
            onChanged={changed}
            onReload={item.reload}
          />
          <MinorItems
            item={record}
            states={states}
            mayEdit={mayEdit && record.record_status !== "retired"}
            onChanged={changed}
          />
          <Memberships item={record} />
          {/* 0.9.8: what runs on it, and on those (P-250). */}
          <WhatRunsOnIt
            of="item"
            hid={record.hid}
            count={record.hosted_count}
            version={String(record.row_version)}
          />
          {/* 0.8.0: the circuits it is connected to, each with its side (P-147). */}
          <ConnectedCircuits circuits={record.circuits} whose={itemName(record)} />
          {/*
            0.9.0: its own references, its model's and those of where it is (P-158). A
            retired item keeps its references and takes more.
          */}
          <References
            key={`references ${record.hid}`}
            holder={{ kind: "item", hid: record.hid }}
            mayEdit={mayEdit}
          />
          <Addresses
            key={`addresses ${record.hid}`}
            holder={{ item_hid: record.hid }}
            whose={itemName(record)}
            mayEdit={mayEdit && record.record_status !== "retired"}
            onChanged={item.reload}
          />
          <ItemCoverage
            key={`coverage ${record.hid}`}
            item={record}
            mayEdit={mayEdit && record.record_status !== "retired"}
            onChanged={changed}
          />
          <Registrations
            key={`registrations ${record.hid}`}
            holder={{ item_hid: record.hid }}
            whose={itemName(record)}
            note="The registrations of the item itself. A stack or a cluster that a system knows as one device is registered as the group: what the group this item is a member of is registered with is listed beneath, to be read."
            throughGroups={record.group_registrations}
            review={record.review}
            retireAt="retire"
            mayEdit={mayEdit && record.record_status !== "retired"}
            onChanged={changed}
          />
          <ItemPurchaseLine
            key={`purchase ${record.hid} ${record.row_version}`}
            item={record}
            mayEdit={mayEdit && record.record_status !== "retired"}
            onChanged={changed}
            onReload={item.reload}
          />
          <ValuesInForce item={record} />
          <Lifecycle
            key={`standing ${record.hid} ${record.row_version}`}
            item={record}
            rules={rules.data ?? []}
            choices={choices.data}
            mayEdit={mayEdit && record.record_status !== "retired"}
            mayForce={allows(user.role, "admin")}
            onChanged={changed}
            onReload={item.reload}
          />
          {mayEdit && record.record_status !== "retired" && (
            <Details
              key={`details ${record.hid} ${record.row_version}`}
              item={record}
              onSaved={() => changed("The item was saved.")}
              onReload={item.reload}
            />
          )}
          <Replacement
            key={`replacement ${record.hid} ${record.row_version}`}
            item={record}
            choices={choices.data}
            mayEdit={mayEdit && record.record_status !== "retired"}
            // 0.9.8: an Admin removes a replacement that was a mistake (P-238).
            mayRemove={allows(user.role, "admin")}
            onChanged={changed}
            onReload={item.reload}
          />
          {mayEdit && (
            <RecordStatus
              key={`status ${record.hid} ${record.row_version}`}
              item={record}
              onChanged={changed}
              onReload={item.reload}
            />
          )}
          {/* 0.9.7: an Admin deletes an item that was a mistake (P-227). */}
          {allows(user.role, "admin") && (
            <DeleteRecord kind="item" hid={record.hid} name={itemName(record)} />
          )}
          <History item={record} />
        </>
      )}
    </>
  );
}

function Fact({
  label,
  children,
  change,
  within,
  more,
}: {
  label: string;
  children: ReactNode;
  /** The name of the field of the form of details that changes it, for a link to it. */
  change?: string | false;
  /** The form that field is in, where it is not the form of details. */
  within?: string;
  /** What stands after the value, as a link to the items there. */
  more?: ReactNode;
}) {
  return (
    <>
      <dt>{label}</dt>
      <dd>
        {children || <Dash />}
        {more}
        {change && <ChangeLink field={change} label={label} {...(within ? { within } : {})} />}
      </dd>
    </>
  );
}

/**
 * Beside a place among the first facts, a link to the list of items at it and within it
 * (P-189). Its name says which place.
 */
function ItemsHere({ hid, name, testId }: { hid: string; name: string; testId: string }) {
  return (
    <Link className="here-link" to={itemsWithin(hid)} data-testid={testId}>
      items here<span className="visually-hidden"> at {name}</span>
    </Link>
  );
}

/**
 * Under the name of an item, a row of links to the sections of its page (P-189). Only
 * the sections that are on the page, for this item and this person, are named: they are
 * read from the page as it stands, since each part decides for itself whether it shows.
 * Each is a link to the section's heading, within the page.
 */
function SectionLinks({ version }: { version: string }) {
  const nav = useRef<HTMLElement>(null);
  const [sections, setSections] = useState<{ id: string; text: string }[]>([]);
  useEffect(() => {
    const page = nav.current?.parentElement;
    if (!page || version === "") return;
    function read() {
      if (!page) return;
      const found = [...page.querySelectorAll<HTMLElement>(":scope > section > h2[id]")].map(
        (heading) => ({ id: heading.id, text: heading.textContent?.trim() ?? "" }),
      );
      setSections((was) =>
        was.length === found.length &&
        was.every((one, place) => one.id === found[place]?.id && one.text === found[place]?.text)
          ? was
          : found,
      );
    }
    read();
    const watcher = new MutationObserver(read);
    watcher.observe(page, { childList: true, subtree: true, characterData: true });
    return () => watcher.disconnect();
  }, [version]);
  const here = `${window.location.pathname}${window.location.search}`;
  return (
    <nav aria-label="Sections of the page" className="section-links" ref={nav}>
      <ul>
        {sections.map((section) => (
          <li key={section.id}>
            <a href={`${here}#${encodeURIComponent(section.id)}`}>{section.text}</a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

// How long Change waits for a field of the form of details to be there, in milliseconds.
const CHANGE_WAIT = 10_000;

// How long a field that Change moved to is held where it stands, in milliseconds.
const SETTLE = 15_000;

/**
 * Hold a field where it stands in the window while the page settles. The parts of a page
 * above the field may come after Change has moved to it, on a busy server, and push it
 * down and out of the window with the keyboard still in it. For a quarter of a minute,
 * while the keyboard is in the field, the window follows the field when the page above
 * it grows or shrinks. A person who scrolls is not held: scrolling does not move the
 * field on the page, and only that is followed.
 */
function keepInView(field: HTMLElement): void {
  const until = performance.now() + SETTLE;
  const top = () => field.getBoundingClientRect().top;
  // Where the field stands on the page, and in the window, when last looked at.
  let onPage = top() + window.scrollY;
  let inWindow = top();
  const look = () => {
    if (document.activeElement !== field || performance.now() > until) return;
    if (Math.abs(top() + window.scrollY - onPage) > 1) {
      // The page moved under the field. Where the browser has not followed, follow.
      const drift = top() - inWindow;
      if (Math.abs(drift) > 1) window.scrollBy(0, drift);
      onPage = top() + window.scrollY;
    }
    inWindow = top();
    window.setTimeout(look, 150);
  };
  window.setTimeout(look, 150);
}

/**
 * From a fact to the field of the form of details that changes it (P-185): the window
 * moves to the field and the keyboard is put in it, a list to choose from or a box to
 * search in alike. Nothing is changed here; the form, its checks and its audit stay the
 * one way. Where the form is still being made ready, the window moves to it and the keyboard
 * follows when the field is there. It is a
 * button that reads as a link: it moves within the page and leaves its address as it is.
 */
function ChangeLink({
  field,
  label,
  within = 'section[aria-labelledby="details"]',
  text,
}: {
  field: string;
  label: string;
  /** The form the field is in: the form of details, or that of a move (P-189). */
  within?: string;
  /** What it says, where Change would not: "Name its host". */
  text?: string;
}) {
  function go() {
    const until = performance.now() + CHANGE_WAIT;
    let moved = false;
    // The form waits for the lists it offers, which may come after its facts do: the
    // window moves to the form at once, and the keyboard to the field when it is there.
    function seek() {
      const form = document.querySelector<HTMLElement>(within);
      const input = form?.querySelector<HTMLElement>(`[name="${field}"]`) ?? null;
      if (input) {
        input.scrollIntoView({ block: "center" });
        input.focus({ preventScroll: true });
        keepInView(input);
        return;
      }
      if (form && !moved) {
        form.scrollIntoView({ block: "start" });
        moved = true;
      }
      if (performance.now() < until) window.setTimeout(seek, 100);
    }
    seek();
  }
  return (
    <button type="button" className="change-link" data-change={field} onClick={go}>
      {text ?? (
        <>
          Change<span className="visually-hidden"> the {label.toLowerCase()}</span>
        </>
      )}
    </button>
  );
}

// What a planned location is, beneath its field.
const PLAN_HINT =
  "Where it is going, when that place is not in use yet. It stays where it is until the place is made active, and is then moved there by that change.";

interface FactsProps {
  item: Item;
  choices: readonly Choice[] | undefined;
  /** Whether the person may change the item, and the form of details is on the page. */
  mayChange: boolean;
  /** Said at the top of the page when a change among the facts was made: the item is read again. */
  onChanged: (text: string) => void;
}

function Facts({ item, choices, mayChange, onChanged }: FactsProps) {
  const { catalog } = item;
  // The owner in force: an item with none of its own has the owner of the item it is
  // in, or of its group.
  const owner = item.effective.owner_hid;
  const ownerInherited = isFromAbove(owner);
  // The location in force, likewise: an item with none of its own is where the item
  // it is in is, or its group. The planned location in the same way.
  const location = item.effective.location_hid;
  const locationInherited = isFromAbove(location);
  const planned = item.effective.planned_location_hid;
  const standing = standingOf(item);
  const serial = item.effective.serial_number;
  const serialFromHost =
    serial.source === "host" && typeof serial.value === "string" ? serial.value : "";
  return (
    <section aria-labelledby="identity">
      <h2 id="identity">Identity</h2>
      <dl className="facts">
        <Fact label="Name">{item.name}</Fact>
        {/* 0.9.6: the stack it is a member of, with the stack's names, or Join a stack (P-222). */}
        <StackFacts item={item} mayChange={mayChange} onChanged={onChanged} />
        {/* 0.9.8: what it runs on and what it was seen on, where it is of such a kind (P-250). */}
        <HostFacts
          item={item}
          change={
            mayChange && (
              <ChangeLink
                field={HOST_FIELD}
                label="Host"
                {...(item.host ? {} : { text: "Name its host" })}
              />
            )
          }
        />
        <Fact label="Hostname">{item.hostname}</Fact>
        <Fact label="FQDN">{item.fqdn}</Fact>
        <Fact label="Serial number">
          {item.serial_number ? (
            <span className="mono">{item.serial_number}</span>
          ) : (
            // 0.9.8: a virtual context shows the serial number of its host (P-246).
            serialFromHost && (
              <span data-testid="serial-from-host" data-source="host">
                <span className="mono">{serialFromHost}</span>
                <InheritedFrom
                  from={
                    item.host
                      ? { text: `the host ${item.host.name}`, path: hostPath(item.host) }
                      : null
                  }
                />
              </span>
            )
          )}
        </Fact>
        <Fact label="Asset tag">{item.asset_tag}</Fact>
        <Fact label="MAC address">
          {item.mac_address && <span className="mono">{formatMac(item.mac_address)}</span>}
        </Fact>
        <Fact label="Catalog entry" change={mayChange && "catalog_entry_hid"}>
          {catalog && (
            <>
              <Link to={`/catalog/${encodeURIComponent(catalog.hid)}`}>
                {catalog.vendor} {catalog.pid}
              </Link>
              {catalog.model_name && <span className="muted"> · {catalog.model_name}</span>}
            </>
          )}
        </Fact>
        {catalog && catalog.links.length > 0 && (
          // The links of its model: an item has none of its own (D-189).
          <Fact label="Links of its model">
            <div className="inherited" data-testid="model-links" data-source="catalog">
              <LinkList links={catalog.links} testId="model-links-list" />
              <InheritedFrom
                from={{
                  path: `/catalog/${encodeURIComponent(catalog.hid)}`,
                  text: `the catalog entry ${catalog.vendor} ${catalog.pid}`,
                }}
              />
            </div>
          </Fact>
        )}
        <Fact label="Kind, type, function">
          {catalog &&
            [
              optionLabel(CATALOG_KINDS, catalog.kind),
              choiceLabel(choices, "catalog_type", catalog.type),
              choiceLabel(choices, "catalog_function", catalog.function),
            ]
              .filter(Boolean)
              .join(" · ")}
        </Fact>
        <Fact label="Owner" change={mayChange && "owner_hid"}>
          {typeof owner.value === "string" && (
            <span data-testid="owner" data-source={owner.source}>
              <Link
                to={`/owners/${encodeURIComponent(owner.value)}`}
                {...(ownerInherited ? { className: "link-inherited" } : {})}
              >
                {effectiveLabel(owner)}
              </Link>
              {ownerInherited && <InheritedFrom from={ownerSource(owner, knownAbove(item))} />}
              {item.owner_exception && (
                <span className="badge" data-testid="owner-exception">
                  Outside the operations team
                </span>
              )}
            </span>
          )}
        </Fact>
        {item.owner_exception && typeof owner.value === "string" && (
          <Fact label="Reason for the exception">
            <span data-testid="owner-exception-reason">{item.owner_exception_reason}</span>
            <span className="muted">
              {" "}
              · the owner&apos;s own reason, changed on{" "}
              <Link to={`/owners/${encodeURIComponent(owner.value)}`}>the page of the owner</Link>
            </span>
          </Fact>
        )}
        <Fact label="Operator" change={mayChange && "operator_hid"}>
          <Operator effective={item.effective.operator_hid} testId="operator" host={item.host} />
        </Fact>
        <Fact
          label="Location"
          change={mayChange && "location_hid"}
          more={
            typeof location.value === "string" && (
              <ItemsHere
                hid={location.value}
                name={effectiveLabel(location)}
                testId="items-at-location"
              />
            )
          }
        >
          {typeof location.value === "string" && (
            <span data-testid="location" data-source={location.source}>
              <Link
                to={placePath("location", location.value)}
                {...(locationInherited ? { className: "link-inherited" } : {})}
              >
                {effectiveLabel(location)}
              </Link>
              <FromAbove effective={location} host={item.host} />
            </span>
          )}
        </Fact>
        <Fact
          label="Site"
          more={
            location.site &&
            location.site_hid && (
              <ItemsHere hid={location.site_hid} name={location.site} testId="items-at-site" />
            )
          }
        >
          {location.site && location.site_hid && (
            <Link to={placePath("site", location.site_hid)} data-testid="site">
              {location.site}
            </Link>
          )}
        </Fact>
        <Fact label="Region">
          {location.region && location.region_hid && (
            <Link to={placePath("region", location.region_hid)} data-testid="region">
              {location.region}
            </Link>
          )}
        </Fact>
        {typeof planned.value === "string" && (
          <Fact label="Planned location">
            <span data-testid="planned-location" data-source={planned.source}>
              Planned for{" "}
              <Link
                to={placePath("location", planned.value)}
                {...(isFromAbove(planned) ? { className: "link-inherited" } : {})}
              >
                {effectiveLabel(planned)}
              </Link>
              , when that place is made active
            </span>
            <FromAbove effective={planned} host={item.host} />
          </Fact>
        )}
        {/* 0.9.5: the standing among the first facts, with Change to a move (P-189). */}
        <Fact
          label="Lifecycle state"
          change={mayChange && "to"}
          within='section[aria-labelledby="move"]'
        >
          {standing.state && (
            <span
              data-testid="standing-fact"
              className={standing.inherited ? "inherited" : undefined}
            >
              {[standing.state, standing.disposition, onlineText(standing.online)]
                .filter(Boolean)
                .join(" · ")}
            </span>
          )}
        </Fact>
        <Fact label="Management address">
          <ManagementAddresses addresses={item.addresses} />
        </Fact>
        <Fact label="Quantity">{String(item.quantity)}</Fact>
        <Fact label="Tags">{item.tags.join(", ")}</Fact>
        <Fact label="Description">{item.description}</Fact>
        <Fact label="Comments" change={mayChange && "comments"}>
          {item.comments}
        </Fact>
        <Fact label="Procured">{item.procured_on}</Fact>
        <Fact label="Delivered">{item.delivered_on}</Fact>
        <Fact label="In service">{item.in_service_on}</Fact>
        <Fact label="Warranty">
          {(item.warranty_start || item.warranty_end) &&
            `${item.warranty_start ?? "…"} to ${item.warranty_end ?? "…"}`}
        </Fact>
        <Fact label="Created">
          <Time at={item.created_at} />
        </Fact>
        <Fact label="Changed">
          <Time at={item.updated_at} />
        </Fact>
        <Fact label="HID">
          <span className="mono">{item.hid}</span>
        </Fact>
      </dl>
    </section>
  );
}

interface DoingProps {
  item: Item;
  choices: readonly Choice[] | undefined;
  mayEdit: boolean;
  onChanged: (text: string) => void;
  onReload: () => void;
}

/**
 * How the item is doing. Three facts are kept apart: the condition, which a person
 * records; what is observed, with the moment it was seen; and the intent, which is under
 * Lifecycle. The health is what the server makes of the three, with its reasons.
 */
function Doing({ item, choices, mayEdit, onChanged, onReload }: DoingProps) {
  const [condition, setCondition] = useState(item.condition ?? "");
  const saving = useAction();
  const seeing = useAction();
  const conditions = choiceOptions(choices, CONDITION_LIST, item.condition);
  const refused = fieldErrors(saving.error, ["condition"]).shown;
  const intent = item.effective.expected_online.value;

  async function saveCondition(event: FormEvent) {
    event.preventDefault();
    const result = await saving.run(() =>
      api.request("patch", "/api/v1/items/{hid}", {
        path: { hid: item.hid },
        body: { row_version: item.row_version, condition: condition === "" ? null : condition },
      }),
    );
    if (result.ok) onChanged("The condition of the item was saved.");
  }

  return (
    <section aria-labelledby="doing">
      <h2 id="doing">Condition and health</h2>
      <dl className="facts">
        <dt>Health</dt>
        <dd>
          <HealthWithReasons health={item.health} testId="health" />
        </dd>
        <dt>Condition</dt>
        <dd data-testid="condition" data-condition={item.condition ?? ""}>
          {choiceLabel(choices, CONDITION_LIST, item.condition) || (
            <span className="muted">Nobody has said</span>
          )}
        </dd>
        <dt>Observed</dt>
        <dd data-testid="observed" data-observed={item.observed_status ?? ""}>
          <ObservedText status={item.observed_status} at={item.observed_at} />
        </dd>
        <dt>Expected online</dt>
        <dd>{typeof intent === "boolean" ? intent ? "Yes" : "No" : <Dash />}</dd>
      </dl>
      <p className="hint">
        The condition is the state of the hardware as a person knows it, and holds while the item is
        on a shelf. What is observed is what is seen of the item on the network, or Present: what a
        person saw of something that is never on the network. Health is worked out from the two and
        from whether the item is expected online, each time the item is read. None of them moves the
        item in the lifecycle: a move is made under Lifecycle, with its own reason.
        {!item.is_major &&
          " A minor item inherits neither: each is a fact about one piece of hardware."}
      </p>
      {mayEdit && (
        <>
          <section aria-labelledby="set-condition" className="panel">
            <h3 id="set-condition">Record the condition</h3>
            <form onSubmit={saveCondition} className="stack" noValidate>
              <Problem error={saving.error} shown={["condition"]} onReload={onReload} />
              <div className="inline">
                <SelectField
                  label="Condition"
                  name="condition"
                  value={condition}
                  onChange={setCondition}
                  disabled={saving.busy}
                  error={refused.condition}
                  hint="Untested is new and not yet tried, and so of unknown health"
                >
                  <option value="">Nobody has said</option>
                  {conditions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </SelectField>
              </div>
              <p className="actions">
                <button
                  type="submit"
                  className="primary"
                  disabled={saving.busy || condition === (item.condition ?? "")}
                >
                  Save condition
                </button>
              </p>
            </form>
          </section>
          <section aria-labelledby="set-observed" className="panel">
            <h3 id="set-observed">Record what is seen</h3>
            <Observation
              whose={itemName(item)}
              status={item.observed_status}
              busy={seeing.busy}
              error={seeing.error}
              onReload={onReload}
              onChange={async (patch, done) => {
                const result = await seeing.run(() =>
                  api.request("patch", "/api/v1/items/{hid}", {
                    path: { hid: item.hid },
                    body: { row_version: item.row_version, ...patch },
                  }),
                );
                if (result.ok) onChanged(done);
              }}
            />
          </section>
        </>
      )}
    </section>
  );
}

/** Every field the item inherits: the value in force, and where it came from. */
function ValuesInForce({ item }: { item: Item }) {
  const sorting = useSorting(IN_FORCE, {
    field: ([, label]) => label,
    // A date is sorted as a date, a decimal as a number and yes or no as its word, and
    // none is last.
    value: ([field]) => {
      const text = effectiveText(item.effective[field]);
      if (field === "do_not_renew") return text || null;
      return INHERITED_DATES.has(field) ? dateValue(text) : decimalValue(text);
    },
    // 0.8.0: the weight's source as its cell says it (P-155).
    source: ([field]) =>
      field === "support_weight"
        ? weightSource(item.effective.support_weight, "item")
        : sourceLabel(item.effective[field]),
  });
  return (
    <section aria-labelledby="values">
      <h2 id="values">Values in force</h2>
      <p className="hint">
        A blank on the item inherits from its catalog entry. A value set on the item overrides it.
      </p>
      <div className="scroll">
        <table className="narrow">
          <caption className="visually-hidden">Values in force, each with its source</caption>
          <thead>
            <tr>
              <SortTh sort={sorting} column="field">
                Field
              </SortTh>
              <SortTh sort={sorting} column="value">
                Value in force
              </SortTh>
              <SortTh sort={sorting} column="source">
                Source
              </SortTh>
            </tr>
          </thead>
          <tbody>
            {sorting.rows.map(([field, label]) => {
              const effective = item.effective[field];
              const inherited = isInherited(effective);
              return (
                <tr key={field} data-field={field} data-source={effective.source}>
                  <th scope="row">{label}</th>
                  <td
                    className={inherited ? "inherited" : undefined}
                    title={sourceHint(effective) || undefined}
                  >
                    {effectiveText(effective) || <Dash />}
                    {/* 0.8.0: a weight raised to the minimum of a major item (P-155). */}
                    {field === "support_weight" && (
                      <Raised weight={item.effective.support_weight} kind="item" />
                    )}
                  </td>
                  <td className={inherited ? "inherited" : undefined}>
                    {/* 0.8.0: the default of a major item names its setting (P-155). */}
                    {field === "support_weight"
                      ? weightSource(item.effective.support_weight, "item")
                      : sourceLabel(effective)}
                    <span className="visually-hidden"> ({effective.source})</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {/* 0.9.4: why it has each value, the walk of each as a row of boxes (P-176); folded
          until it is asked for since 0.9.6 (P-198). */}
      <WhyEachValue
        of="item"
        hid={item.hid}
        version={`${item.row_version} ${JSON.stringify(item.effective)}`}
      >
        <p className="hint" id="walks-intro">
          The records it looks at in their order, its own first, then its own groups, the item it is
          in and that item's groups, or what it runs on and that one's groups, and for the operator
          where it is. The first that holds a value decides, and those after it are passed over.
        </p>
      </WhyEachValue>
    </section>
  );
}

interface LifecycleProps {
  item: Item;
  rules: readonly Rule[];
  choices: readonly Choice[] | undefined;
  mayEdit: boolean;
  mayForce: boolean;
  onChanged: (text: string) => void;
  onReload: () => void;
}

/** The item's standing, and the two ways to change it: a move, and an edit within a state. */
function Lifecycle(props: LifecycleProps) {
  const { item, rules, choices, mayEdit } = props;
  const standing = standingOf(item);
  const lighter = standing.inherited ? "inherited" : undefined;
  const allowed = dispositionsIn(rules, item.lifecycle_state, item.disposition);
  const hint =
    allowed.length > 0
      ? `An item in ${item.lifecycle_state} is ${allowed.join(" or ")}.`
      : `An item in ${item.lifecycle_state} carries no disposition.`;

  return (
    <section aria-labelledby="lifecycle">
      <h2 id="lifecycle">Lifecycle</h2>
      {/* The standing in force. For a minor item with no state of its own it is that of
          the item above it, shown lighter, and the page says whose it is. */}
      <dl
        className="facts"
        data-testid="standing"
        data-source={item.effective.lifecycle_state.source}
      >
        <dt>State</dt>
        <dd data-testid="state" className={lighter}>
          {standing.state ?? <Dash />}
        </dd>
        <dt>Disposition</dt>
        <dd data-testid="disposition" className={lighter}>
          {standing.disposition ?? <Dash />}
        </dd>
        <dt>Intent</dt>
        <dd data-testid="intent" className={lighter}>
          {onlineText(standing.online) || <Dash />}
        </dd>
        <dt>Reason</dt>
        <dd>{choiceLabel(choices, "state_reason", item.state_reason) || <Dash />}</dd>
        <dt>Since</dt>
        <dd>
          <Time at={item.state_changed_at} />
        </dd>
      </dl>
      {!item.is_major && !item.lifecycle_state && (
        <p data-testid="standing-inherited">
          {standing.inherited && standing.sourceHid ? (
            <>
              This minor item has no state of its own. Its state, disposition and intent are those
              of{" "}
              <Link to={`/items/${encodeURIComponent(standing.sourceHid)}`}>
                {standing.sourceHid === item.parent?.hid
                  ? itemName(item.parent)
                  : "the nearest item above it that has a state"}
              </Link>
              , taken together, and follow it. Moving it to a state gives it a standing of its own.
            </>
          ) : (
            "This minor item has no state of its own, and no item above it has one either."
          )}
        </p>
      )}
      {mayEdit && mayInheritAgain(item) && (
        <InheritAgain item={item} onChanged={props.onChanged} onReload={props.onReload} />
      )}
      {mayEdit && <Transition {...props} />}
      {mayEdit && item.lifecycle_state && (
        <section aria-labelledby="standing-form" className="panel">
          <h3 id="standing-form">Change the disposition or the intent</h3>
          <p className="hint">
            Within a state this is an ordinary change. {hint} The state itself is changed by a move.
          </p>
          <WithinState
            item={item}
            rules={rules}
            onChanged={props.onChanged}
            onReload={props.onReload}
          />
        </section>
      )}
    </section>
  );
}

/** The value of a yes-or-no select for an intent: blank for none. */
function intentValue(online: boolean | null | undefined): string {
  return online === true ? "true" : online === false ? "false" : "";
}

/**
 * Change an item's disposition and intent within its state (P-191). Only what the rule of
 * the state allows is offered, as the server's check has it: the dispositions of the rule,
 * None only where it asks for none, and for Expected online only Yes where the disposition
 * chosen must be online and only No where it may not be. What the item has now is offered
 * all the same, allowed or not. The server judges the change; only what differs is sent.
 */
function WithinState({
  item,
  rules,
  onChanged,
  onReload,
}: Pick<LifecycleProps, "item" | "rules" | "onChanged" | "onReload">) {
  const action = useAction();
  const [disposition, setDisposition] = useState(item.disposition ?? "");
  const [online, setOnline] = useState(intentValue(item.expected_online));
  const offered = standingChoices(rules, item.lifecycle_state, item.disposition);
  const dispositions = DISPOSITIONS.filter(
    (name) => offered.dispositions.includes(name) || name === item.disposition,
  );
  const intents = intentChoices(rules, item.lifecycle_state, disposition || null);
  const known = ["disposition", "expected_online"];
  const refused = fieldErrors(action.error, known).shown;
  const changed =
    disposition !== (item.disposition ?? "") || online !== intentValue(item.expected_online);

  function chooseDisposition(next: string) {
    setDisposition(next);
    // An intent the disposition chosen does not allow gives way to the one it does.
    const now = intentChoices(rules, item.lifecycle_state, next || null);
    if (now.length === 1 && online !== intentValue(now[0])) setOnline(intentValue(now[0]));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const body: Schemas["ItemPatch"] = { row_version: item.row_version };
    if (disposition !== (item.disposition ?? "")) body.disposition = disposition || null;
    if (online !== intentValue(item.expected_online)) body.expected_online = online === "true";
    const result = await action.run(() =>
      api.request("patch", "/api/v1/items/{hid}", { path: { hid: item.hid }, body }),
    );
    if (result.ok) onChanged("The item's standing was changed.");
  }

  return (
    <form onSubmit={submit} className="stack" noValidate>
      <Problem error={action.error} shown={known} onReload={onReload} />
      <div className="fields">
        <SelectField
          label="Disposition"
          name="disposition"
          value={disposition}
          onChange={chooseDisposition}
          error={refused.disposition}
          disabled={action.busy}
        >
          {(offered.none || !item.disposition) && <option value="">None</option>}
          {dispositions.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </SelectField>
        <SelectField
          label="Expected online"
          name="expected_online"
          value={online}
          onChange={setOnline}
          error={refused.expected_online}
          disabled={action.busy}
        >
          {/* An item with a state is expected online or it is not: no blank to choose. */}
          {item.expected_online == null && <option value="">—</option>}
          {[true, false]
            .filter((value) => intents.includes(value) || value === item.expected_online)
            .map((value) => (
              <option key={String(value)} value={intentValue(value)}>
                {value ? "Yes" : "No"}
              </option>
            ))}
        </SelectField>
      </div>
      <p className="actions">
        <button type="submit" className="primary" disabled={action.busy || !changed}>
          Save standing
        </button>
        <button
          type="button"
          disabled={action.busy || !changed}
          onClick={() => {
            setDisposition(item.disposition ?? "");
            setOnline(intentValue(item.expected_online));
            action.clear();
          }}
        >
          Undo changes
        </button>
      </p>
    </form>
  );
}

/**
 * Return a minor item that has a state of its own to the standing of the item it is in.
 * It is a move to no state, recorded like any other.
 */
function InheritAgain({
  item,
  onChanged,
  onReload,
}: Pick<LifecycleProps, "item" | "onChanged" | "onReload">) {
  const action = useAction();
  const above = item.parent ? itemName(item.parent) : "the item it is in";

  async function inherit() {
    const result = await action.run(() =>
      api.request("post", "/api/v1/items/{hid}/transition", {
        path: { hid: item.hid },
        body: { row_version: item.row_version, to: null },
      }),
    );
    if (result.ok) onChanged(`The item has the standing of ${above} again.`);
  }

  return (
    <section aria-labelledby="inherit-again" className="panel">
      <h3 id="inherit-again">A state of its own</h3>
      <Problem error={action.error} onReload={onReload} />
      <p>
        This minor item has a state of its own, so it no longer follows {above}. Returning it gives
        up its own state, disposition and intent together. The move is in the history like any
        other.
      </p>
      <p className="actions">
        <button type="button" onClick={inherit} disabled={action.busy}>
          Return to the standing of {above}
        </button>
      </p>
    </section>
  );
}

/** Move an item to another state, recording who, when, from, to and why. */
function Transition({ item, rules, choices, mayForce, onChanged, onReload }: LifecycleProps) {
  const [force, setForce] = useState(false);
  const [to, setTo] = useState("");
  const [reason, setReason] = useState("");
  const [disposition, setDisposition] = useState("");
  const [online, setOnline] = useState("");
  const action = useAction();
  const targets = nextStates(rules, item.lifecycle_state, force);
  const target = targets.includes(to) ? to : "";
  const reasons = choiceOptions(choices, "state_reason");
  const dispositions = dispositionsIn(rules, target, item.disposition);
  const known = ["to", "reason", "disposition", "expected_online", "force"];
  const refused = fieldErrors(action.error, known).shown;

  async function submit(event: FormEvent) {
    event.preventDefault();
    // What is left as the rules have it is not sent, so that the rules decide it.
    const body: Schemas["Transition"] = { row_version: item.row_version, to: target };
    if (reason) body.reason = reason;
    if (disposition && dispositions.includes(disposition)) body.disposition = disposition;
    if (online) body.expected_online = online === "true";
    if (force) body.force = true;
    const result = await action.run(() =>
      api.request("post", "/api/v1/items/{hid}/transition", { path: { hid: item.hid }, body }),
    );
    if (result.ok) onChanged(`The item was moved to ${target}.`);
  }

  return (
    <section aria-labelledby="move" className="panel">
      <h3 id="move">Move to another state</h3>
      {targets.length === 0 ? (
        <p>
          An item in {item.lifecycle_state} does not move on.
          {mayForce ? " An Admin may force a move." : ""}
        </p>
      ) : (
        !item.lifecycle_state && (
          <p className="hint">
            {item.is_major
              ? "An item with no state may be given any."
              : "A minor item with no state of its own may be given any."}
          </p>
        )
      )}
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={known} onReload={onReload} />
        <div className="fields">
          <SelectField
            label="Move to"
            name="to"
            value={target}
            onChange={setTo}
            required
            error={refused.to}
            disabled={targets.length === 0}
          >
            <option value="">Choose a state</option>
            {targets.map((state) => (
              <option key={state} value={state}>
                {state}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="Reason"
            name="reason"
            value={reason}
            onChange={setReason}
            required={force}
            error={refused.reason}
            hint={force ? "A forced move needs a reason" : "Optional"}
          >
            <option value="">No reason given</option>
            {reasons.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="Disposition"
            name="disposition"
            value={dispositions.includes(disposition) ? disposition : ""}
            onChange={setDisposition}
            error={refused.disposition}
            disabled={target === "" || dispositions.length === 0}
            hint={
              target !== "" && dispositions.length === 0
                ? `An item in ${target} carries none`
                : "Optional"
            }
          >
            <option value="">As the rules set it</option>
            {dispositions.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="Expected online"
            name="expected_online"
            value={online}
            onChange={setOnline}
            error={refused.expected_online}
            hint={
              target !== "" && !mayBeOnline(rules, target)
                ? `An item in ${target} is not expected online`
                : "Optional"
            }
          >
            <option value="">As the rules set it</option>
            <option value="true">Yes</option>
            <option value="false">No</option>
          </SelectField>
        </div>
        {mayForce && item.lifecycle_state && (
          <CheckField
            label="Force a move the rules do not list"
            name="force"
            checked={force}
            onChange={setForce}
            hint="For an Admin, with a reason. The move is marked as forced in the history."
            error={refused.force}
          />
        )}
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || target === ""}>
            Move
          </button>
        </p>
      </form>
    </section>
  );
}

interface DetailsProps {
  item: Item;
  onSaved: () => void;
  onReload: () => void;
}

/** The form for everything about an item but its state. Only what was changed is sent. */
function Details({ item, onSaved, onReload }: DetailsProps) {
  const owners = useOwnerOptions();
  const tags = useTags();
  const specs = useMemo<FieldSpec[]>(() => {
    const { catalog, owner } = item;
    // The owners to choose from, the item's own among them as the item names it, also
    // when the list no longer brings it. One outside the team says so, with its reason.
    const offered = withCurrent(
      owners.data,
      owner && ownerOption({ ...owner, exception_reason: item.owner_exception_reason }),
    );
    return [
      {
        name: "catalog_entry_hid",
        label: "Catalog entry",
        // 0.9.6: searched for, not a list of every model (P-200).
        kind: "entry",
        blank: "No catalog entry",
        options: catalog ? [{ value: catalog.hid, label: entryLabel(catalog) }] : [],
        heading: "Identity",
      },
      { name: "serial_number", label: "Serial number", kind: "text", maxLength: 100 },
      { name: "asset_tag", label: "Asset tag", kind: "text", maxLength: 100 },
      {
        name: "name",
        label: "Name",
        kind: "text",
        maxLength: 200,
        hint: "Left blank, the hostname is shown",
      },
      { name: "hostname", label: "Hostname", kind: "text", maxLength: 255 },
      { name: "fqdn", label: "FQDN", kind: "text", maxLength: 255 },
      {
        name: "mac_address",
        label: "MAC address",
        kind: "text",
        maxLength: 40,
        hint: "In any common notation",
      },
      { name: "quantity", label: "Quantity", kind: "integer", hint: "Seats or licences" },
      // 0.9.8: what it runs on, where its model is of a kind that does (P-250).
      ...(item.is_major
        ? hostSpecs({
            kindOf: (hid) =>
              hid === catalog?.hid ? catalog.kind : (entrySeen(hid)?.kind ?? undefined),
            host: item.host,
            observed: item.observed_host
              ? { hid: item.observed_host.hid, label: pickLabel(item.observed_host) }
              : null,
            self: item.hid,
          })
        : []),
      {
        name: "owner_hid",
        label: "Owner",
        kind: "choice",
        blank: aboveItem(item) ? "None of its own" : "No owner",
        options: offered,
      },
      {
        name: "operator_hid",
        label: "Operator",
        kind: "operator",
        blank: "None of its own",
        options: item.operator
          ? [{ value: item.operator.hid, label: operatorOptionLabel(item.operator) }]
          : [],
      },
      {
        name: "location_hid",
        label: "Location",
        kind: "location",
        blank: aboveItem(item) ? "None of its own" : "No location",
        options: item.location ? [{ value: item.location.hid, label: item.location.path }] : [],
      },
      {
        name: "planned_location_hid",
        label: "Planned location",
        kind: "planned_location",
        blank: aboveItem(item) ? "None of its own" : "No plan",
        options: item.planned_location
          ? [{ value: item.planned_location.hid, label: item.planned_location.path }]
          : [],
        hint: PLAN_HINT,
      },
      {
        name: "record_status",
        label: "Record status",
        kind: "choice",
        options: SETTABLE_STATUSES,
        hint: "A draft is left out of counts and default views",
      },
      { name: "description", label: "Description", kind: "longtext", maxLength: 10000 },
      { name: "comments", label: "Comments", kind: "longtext", maxLength: 10000 },
      {
        name: "tags",
        label: "Tags",
        kind: "set",
        // Every tag there is, and any the item carries that the list did not bring.
        options: [...new Set([...(tags.data ?? []).map((tag) => tag.label), ...item.tags])].map(
          (label) => ({ value: label, label }),
        ),
        hint: "A tag is made under Admin, then used here",
      },
      { name: "procured_on", label: "Procured on", kind: "date", heading: "Dates" },
      { name: "delivered_on", label: "Delivered on", kind: "date" },
      { name: "in_service_on", label: "In service on", kind: "date" },
      { name: "warranty_start", label: "Warranty start", kind: "date" },
      { name: "warranty_end", label: "Warranty end", kind: "date" },
      {
        name: "est_value",
        label: "Estimated value",
        kind: "decimal",
        places: 2,
        heading: "Overrides of what the catalog entry says",
      },
      { name: "support_weight", label: "Support weight", kind: "decimal", places: 2 },
      { name: "annual_support_cost", label: "Annual support cost", kind: "decimal", places: 2 },
      { name: "end_of_sale", label: "End of sale", kind: "date" },
      { name: "end_of_sw_support", label: "End of software support", kind: "date" },
      { name: "end_of_hw_support", label: "End of hardware support", kind: "date" },
      { name: "ldos", label: "Last day of support (LDoS)", kind: "date" },
      {
        // Its own word on renewing its support: blank has its model's (D-182).
        name: "do_not_renew",
        label: "Not to be renewed",
        kind: "tristate",
        blank: "As its model says",
      },
    ];
  }, [item, owners.data, tags.data]);

  // Under each field that inherits: what a blank shows, or that it is set here.
  const hints: Record<string, string> = {};
  for (const [field] of INHERITED) {
    hints[field] = inheritHint(
      item[field],
      item.effective[field].source === "own" ? null : item.effective[field],
    );
  }
  // 0.8.0: a weight in force raised to the minimum of a major item says so (P-155).
  const raised = raisedText(item.effective.support_weight, "item");
  if (raised) hints.support_weight = `${hints.support_weight} ${raised}.`;
  hints.do_not_renew = notRenewedHint(item);
  // The location and the planned location of an item that has something above it:
  // with one of its own the form says that it is an override and how to give it up;
  // with none it shows the one in force from above, before one is chosen.
  const above = aboveItem(item);
  const ownerHint = descentHint("owner", "item", item.owner_hid, item.effective.owner_hid, above);
  if (ownerHint) hints.owner_hid = ownerHint;
  const whereHint = descentHint(
    "location",
    "item",
    item.location_hid,
    item.effective.location_hid,
    above,
  );
  if (whereHint) hints.location_hid = whereHint;
  const planHint = descentHint(
    "planned",
    "item",
    item.planned_location_hid,
    item.effective.planned_location_hid,
    above,
  );
  hints.planned_location_hid = [PLAN_HINT, planHint].filter(Boolean).join(" ");
  // The operator: with one of its own the form says how to give it up; with none it
  // shows the one in force from above, read-only, before anybody is chosen.
  if (item.operator_hid) {
    hints.operator_hid =
      "The label of who of the team looks after it. Set here: clear it to have the operator from above again, if there is one.";
  } else {
    hints.operator_hid = "The label of who of the team looks after it.";
  }
  const notes = {
    ...(item.operator_hid
      ? {}
      : {
          operator_hid: (
            <OperatorNote effective={item.effective.operator_hid} what="item" host={item.host} />
          ),
        }),
    ...(isFromAbove(item.effective.owner_hid)
      ? {
          owner_hid: (
            <OwnerNote
              effective={item.effective.owner_hid}
              from={ownerSource(item.effective.owner_hid, knownAbove(item))}
              what="item"
            />
          ),
        }
      : {}),
    ...(isFromAbove(item.effective.location_hid)
      ? {
          location_hid: (
            <PlaceNote
              kind="location"
              effective={item.effective.location_hid}
              what="item"
              host={item.host}
            />
          ),
        }
      : {}),
    ...(isFromAbove(item.effective.planned_location_hid)
      ? {
          planned_location_hid: (
            <PlaceNote
              kind="planned"
              effective={item.effective.planned_location_hid}
              what="item"
              host={item.host}
            />
          ),
        }
      : {}),
  };
  const ready = !owners.loading && !tags.loading;

  return (
    <section aria-labelledby="details">
      <h2 id="details">Details</h2>
      <Problem error={owners.error ?? tags.error} />
      {!ready && <p role="status">Loading…</p>}
      {ready && (
        <EditForm<Item & { [HOST_FIELD]: string }, Schemas["ItemPatch"]>
          specs={specs}
          // 0.9.8: what it runs on as one field, an item or a group (P-250).
          record={{ ...item, [HOST_FIELD]: hostValue(item) }}
          hints={hints}
          notes={notes}
          save={(body) =>
            api.request("patch", "/api/v1/items/{hid}", {
              path: { hid: item.hid },
              body: sentHost(body),
            })
          }
          onSaved={onSaved}
          onReload={onReload}
        />
      )}
    </section>
  );
}

interface RecordStatusProps {
  item: Item;
  onChanged: (text: string) => void;
  onReload: () => void;
}

/** Retire an item, or bring a retired one back. Nothing is ever deleted. */
function RecordStatus({ item, onChanged, onReload }: RecordStatusProps) {
  const action = useAction();
  const name = itemName(item);
  // 0.9.8: what runs on it is named before the question is answered, and goes with it (P-247).
  const hosted = useHostedQuestion("item", item.hid, item.hosted_count);

  async function retire() {
    const result = await action.run(() =>
      api.request("post", "/api/v1/items/{hid}/retire", {
        path: { hid: item.hid },
        body: { row_version: item.row_version },
      }),
    );
    if (result.ok) onChanged(itemRetiredText(hosted.count));
  }

  /** Bring the item back: as it was, or with another location, or none, in the same change. */
  async function bringBack(location?: string | null) {
    const result = await action.run(() =>
      api.request("patch", "/api/v1/items/{hid}", {
        path: { hid: item.hid },
        body: {
          row_version: item.row_version,
          record_status: "active",
          ...(location === undefined ? {} : { location_hid: location }),
        },
      }),
    );
    if (result.ok) onChanged("The item is active again.");
  }

  return (
    <section aria-labelledby="retire">
      <h2 id="retire">{item.record_status === "retired" ? "Retired" : "Retire"}</h2>
      <Problem error={action.error} onReload={onReload} labels={{ record_status: "" }} />
      {item.record_status === "retired" ? (
        <>
          <p>
            This item is retired. It is left out of counts and default views, and its record and
            history are kept.
          </p>
          <p className="actions">
            <button type="button" onClick={() => bringBack()} disabled={action.busy}>
              Bring back as active
            </button>
          </p>
          {refusedForItsPlace(action.error) && (
            <BringBackElsewhere
              what="item"
              blank={item.is_major ? "No location" : "Where the item it is in is"}
              busy={action.busy}
              onBringBack={bringBack}
            />
          )}
        </>
      ) : (
        <>
          <p>
            A retired item is left out of counts and default views. Its record and history are kept,
            and it can be brought back.
          </p>
          <p className="actions">
            <ConfirmButton
              label="Retire item"
              title={`Retire ${name}?`}
              confirmLabel="Retire item"
              onConfirm={retire}
              disabled={action.busy}
              onOpen={hosted.onOpen}
              confirmDisabled={!hosted.ready}
            >
              {hosted.shown}
              <p>The item stays in the inventory and can be brought back.</p>
              {item.groups.length > 0 && (
                <p>
                  Its {item.groups.length === 1 ? "membership" : "memberships"} of{" "}
                  {item.groups.map((group) => group.name).join(", ")} end
                  {item.groups.length === 1 ? "s" : ""} today, and stay
                  {item.groups.length === 1 ? "s" : ""} on record with that day.
                </p>
              )}
            </ConfirmButton>
          </p>
        </>
      )}
    </section>
  );
}

/**
 * Every change made to the item, newest first until a header is clicked: who, when, what
 * was and what is.
 */
function History({ item }: { item: Item }) {
  const { user } = useAuth();
  // 0.9.8: the user who made a change opens the user's page, for an Admin (P-240).
  const admin = allows(user.role, "admin");
  const [offset, setOffset] = useState(0);
  // The server sorts the events, over the whole history, each with its rows kept
  // together: another order starts at its first page.
  const sort = useServerSort<Schemas["AuditEventOut"]>({
    fields: HISTORY_SORT,
    onChange: () => setOffset(0),
  });
  // The version is part of the key, so the history is read again after every change.
  const history = sort.held(
    useLoad(`history ${item.hid} ${item.row_version} ${offset} ${sort.param ?? ""}`, (signal) =>
      api.request("get", "/api/v1/items/{hid}/history", {
        path: { hid: item.hid },
        query: {
          limit: HISTORY_PAGE,
          offset,
          // The contract has the sort as a list: this is a list of the one.
          ...sort.query,
        },
        signal,
      }),
    ),
  );
  const events = history.data?.items ?? [];
  const holdsAll = history.data !== undefined && history.data.total <= events.length;

  return (
    <section aria-labelledby="history">
      <h2 id="history">History</h2>
      <Problem error={history.error} />
      {history.loading && !history.data && <p role="status">Loading…</p>}
      {history.data && (
        <>
          <div className="scroll">
            <table className="history">
              <caption className="visually-hidden">
                Changes to this item, newest first until a header is clicked
              </caption>
              <thead>
                <tr>
                  <SortTh sort={sort.header("at", holdsAll)} column="at">
                    When
                  </SortTh>
                  <SortTh sort={sort.header("actor_name", holdsAll)} column="actor_name">
                    Who
                  </SortTh>
                  <SortTh sort={sort.header("action", holdsAll)} column="action">
                    Action
                  </SortTh>
                  <th scope="col">Field</th>
                  <th scope="col">Was</th>
                  <th scope="col">Is</th>
                </tr>
              </thead>
              {sort.arrange(events, holdsAll).map((event) => {
                const changes = event.changes.length > 0 ? event.changes : [{}];
                return (
                  <tbody key={event.hid} data-action={event.action}>
                    {changes.map((change, place) => {
                      const field = typeof change.field === "string" ? change.field : "";
                      return (
                        <tr key={`${event.hid} ${field || place}`}>
                          {place === 0 && (
                            <>
                              <td className="nowrap" rowSpan={changes.length}>
                                <Time at={event.at} />
                              </td>
                              <td rowSpan={changes.length}>
                                {event.actor_name ? (
                                  <ValueLink kind="user" hid={event.actor_hid} admin={admin}>
                                    {event.actor_name}
                                  </ValueLink>
                                ) : (
                                  <Dash />
                                )}
                              </td>
                              <td rowSpan={changes.length}>{event.action}</td>
                            </>
                          )}
                          <td>{field}</td>
                          <td>{field && formatValue(change.old)}</td>
                          <td>{field && formatValue(change.new)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                );
              })}
              {events.length === 0 && (
                <tbody>
                  <tr>
                    <td colSpan={6} className="muted">
                      There are no changes on record.
                    </td>
                  </tr>
                </tbody>
              )}
            </table>
          </div>
          <Pager
            total={history.data.total}
            limit={HISTORY_PAGE}
            offset={offset}
            noun="events"
            onChange={setOffset}
          />
        </>
      )}
    </section>
  );
}
