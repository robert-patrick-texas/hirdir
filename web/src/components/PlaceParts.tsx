// One place of the Geography page: a region, a site or a location. Its path and its own
// fields, what it has in force with the level each thing came from, the contacts
// assigned to the place itself, and the ways to change it: edit, move, retire, and make
// a place within it.
//
// Nothing is resolved here. What a place has in force is the server's answer to
// `GET …/effective`, and a path is the one the server sent.

import {
  type FormEvent,
  type ReactNode,
  useEffect,
  useEffectEvent,
  useMemo,
  useState,
} from "react";
import { Link } from "react-router";
import { api, type Schemas } from "../api";
import { plural } from "../lib/format";
import { useAction, useLoad, useReloadOn } from "../lib/hooks";
import { EVERY, useChoices, useContactOptions, useRegions, useTags } from "../lib/lists";
import {
  choiceLabel,
  choiceOptions,
  optionLabel,
  RECORD_STATUSES,
  SETTABLE_STATUSES,
} from "../lib/options";
import type { FieldSpec, Option } from "../lib/patch";
import {
  ASSIGNED_TO,
  type Assignment,
  addressLines,
  addressOf,
  CONTACT_ROLE_LIST,
  contactLine,
  fromAbove,
  itemsWithin,
  type Level,
  LOCATION_KIND_LIST,
  type Location,
  levelLabel,
  locationsToMoveTo,
  noContactText,
  ownRoles,
  type Place,
  type PlaceEffective,
  placePath,
  type Region,
  regionsToMoveTo,
  type Site,
} from "../lib/places";
import { fieldErrors } from "../lib/problems";
import { ConfirmButton } from "./ConfirmButton";
import { CheckField, SelectField, TextField } from "./Field";
import { Notice, Problem } from "./Problem";
import { CreateForm, EditForm } from "./RecordForm";
import { Time } from "./Time";

type Choice = Schemas["ChoiceOut"];
/** A change to a place: the version it was read at, and the fields to change. */
type PlacePatch = { row_version: number } & Record<string, unknown>;
type PlaceCreate = Record<string, unknown>;

function isLocation(place: Place): place is Location {
  return "site_hid" in place;
}

function isSite(place: Place): place is Site {
  return "region_hid" in place;
}

function isRegion(place: Place): place is Region {
  return "parent_region_hid" in place;
}

function readPlace(level: Level, hid: string, signal: AbortSignal): Promise<Place> {
  const options = { path: { hid }, signal };
  if (level === "region") return api.request("get", "/api/v1/regions/{hid}", options);
  if (level === "site") return api.request("get", "/api/v1/sites/{hid}", options);
  return api.request("get", "/api/v1/locations/{hid}", options);
}

function readEffective(level: Level, hid: string, signal: AbortSignal): Promise<PlaceEffective> {
  const options = { path: { hid }, signal };
  if (level === "region") return api.request("get", "/api/v1/regions/{hid}/effective", options);
  if (level === "site") return api.request("get", "/api/v1/sites/{hid}/effective", options);
  return api.request("get", "/api/v1/locations/{hid}/effective", options);
}

function patchPlace(level: Level, hid: string, body: PlacePatch): Promise<Place> {
  const path = { hid };
  if (level === "region") {
    return api.request("patch", "/api/v1/regions/{hid}", {
      path,
      body: body as Schemas["RegionPatch"],
    });
  }
  if (level === "site") {
    return api.request("patch", "/api/v1/sites/{hid}", {
      path,
      body: body as Schemas["SitePatch"],
    });
  }
  return api.request("patch", "/api/v1/locations/{hid}", {
    path,
    body: body as Schemas["LocationPatch"],
  });
}

function retirePlace(level: Level, hid: string, rowVersion: number): Promise<Place> {
  const options = { path: { hid }, body: { row_version: rowVersion } };
  if (level === "region") return api.request("post", "/api/v1/regions/{hid}/retire", options);
  if (level === "site") return api.request("post", "/api/v1/sites/{hid}/retire", options);
  return api.request("post", "/api/v1/locations/{hid}/retire", options);
}

/** Make a place. The body names what it is in: a region, a site or a location. */
export function createPlace(level: Level, body: PlaceCreate): Promise<Place> {
  if (level === "region") {
    return api.request("post", "/api/v1/regions", { body: body as Schemas["RegionCreate"] });
  }
  if (level === "site") {
    return api.request("post", "/api/v1/sites", { body: body as Schemas["SiteCreate"] });
  }
  return api.request("post", "/api/v1/locations", { body: body as Schemas["LocationCreate"] });
}

function Dash() {
  return <span className="muted">—</span>;
}

const STREET: ReadonlyArray<[field: string, label: string]> = [
  ["address1", "Address line 1"],
  ["address2", "Address line 2"],
  ["city", "City"],
  ["state", "State or province"],
  ["postal_code", "Postal code"],
  ["country", "Country"],
];

/**
 * The fields of a place that a form sets. A region has the shipping set and no street
 * address; a location also has a kind. What a place is in is not among them: a place is
 * moved by the form of its own under Move.
 */
export function placeSpecs(
  level: Level,
  lists: { kinds: readonly Option[]; tags: readonly string[] },
  current: Place | null = null,
): FieldSpec[] {
  const shipFrom =
    level === "region" ? "the nearest region above that has one" : "the nearest place above it";
  const street: FieldSpec[] =
    level === "region"
      ? []
      : [
          ...STREET.map(
            ([name, label], place): FieldSpec => ({
              name,
              label,
              kind: "text",
              maxLength: 200,
              ...(place === 0
                ? {
                    heading: "Street address",
                    hint: "Where the place is. It is never taken for a shipping address.",
                  }
                : {}),
            }),
          ),
          {
            name: "latitude",
            label: "Latitude",
            kind: "text",
            maxLength: 10,
            hint: "Decimal degrees, as 41.878100. Given with the longitude or not at all.",
          },
          {
            name: "longitude",
            label: "Longitude",
            kind: "text",
            maxLength: 11,
            hint: "Decimal degrees, as -87.629800",
          },
        ];
  return [
    { name: "name", label: "Name", kind: "text", required: true, maxLength: 200 },
    {
      name: "code",
      label: "Code",
      kind: "text",
      maxLength: 40,
      hint: "A short name such as CEN or S2. Optional, and unique when given.",
    },
    ...(level === "location"
      ? [
          {
            name: "kind",
            label: "Kind",
            kind: "choice",
            blank: "Not said",
            options: lists.kinds,
          } satisfies FieldSpec,
        ]
      : []),
    {
      name: "record_status",
      label: "Record status",
      kind: "choice",
      options: SETTABLE_STATUSES,
      hint: "A draft is left out of default views",
    },
    { name: "notes", label: "Notes", kind: "longtext", maxLength: 10000 },
    {
      name: "tags",
      label: "Tags",
      kind: "set",
      options: [...new Set([...lists.tags, ...(current?.tags ?? [])])].map((label) => ({
        value: label,
        label,
      })),
      hint: "A tag is made under Admin, then used here",
    },
    ...street,
    ...STREET.map(
      ([name, label], place): FieldSpec => ({
        name: `ship_${name}`,
        label: `Shipping ${label.toLowerCase()}`,
        kind: "text",
        maxLength: 200,
        ...(place === 0
          ? {
              heading: "Shipping address",
              hint: `Where deliveries go. Left blank in all six fields, the address is that of ${shipFrom}, taken whole.`,
            }
          : {}),
      }),
    ),
    {
      name: "ship_instructions",
      label: "Shipping instructions",
      kind: "longtext",
      maxLength: 10000,
      hint: "Left blank, the instructions of the nearest place above that has any",
    },
  ];
}

/** The kinds a location may be, and every tag, for the forms of a place. */
export function usePlaceLists(currentKind: string | null = null) {
  const choices = useChoices();
  const tags = useTags();
  const lists = useMemo(
    () => ({
      kinds: choiceOptions(choices.data, LOCATION_KIND_LIST, currentKind),
      tags: (tags.data ?? []).map((tag) => tag.label),
    }),
    [choices.data, tags.data, currentKind],
  );
  return {
    lists,
    choices: choices.data,
    error: choices.error ?? tags.error,
    ready: !choices.loading && !tags.loading,
  };
}

interface PlaceDetailProps {
  level: Level;
  hid: string;
  /** The view of the tree, as the query of the page: kept in every link to a place. */
  search: string;
  mayEdit: boolean;
  /** Something changed that the tree shows: a name, a move, a status, a new place. */
  onTreeChanged: () => void;
  /** The site the place is, or is in: the tree shows the inside of it. */
  onSite: (siteHid: string) => void;
  /** A place was made within this one: go to it. */
  onCreated: (level: Level, place: Place) => void;
}

/** Geography → one place. */
export function PlaceDetail(props: PlaceDetailProps) {
  const { level, hid, search, mayEdit, onTreeChanged, onCreated } = props;
  const place = useLoad(`place ${level} ${hid}`, (signal) => readPlace(level, hid, signal));
  const record = place.data;
  const kind = record && isLocation(record) ? record.kind : null;
  const { lists, choices, error: listsError, ready } = usePlaceLists(kind);
  const [done, setDone] = useState("");
  // Counts the changes made here, so that what is in force is read again after each.
  const [turn, setTurn] = useState(0);
  const [adding, setAdding] = useState<Level | null>(null);
  const specs = useMemo(() => placeSpecs(level, lists, record ?? null), [level, lists, record]);
  const to = (toLevel: string, toHid: string) => ({ pathname: placePath(toLevel, toHid), search });

  const showSite = useEffectEvent(props.onSite);
  const siteHid = record
    ? isLocation(record)
      ? record.site_hid
      : isSite(record)
        ? record.hid
        : ""
    : "";
  useEffect(() => {
    if (siteHid) showSite(siteHid);
  }, [siteHid]);

  function changed(text: string, tree = true) {
    setDone(text);
    setTurn((count) => count + 1);
    place.reload();
    if (tree) onTreeChanged();
  }

  const editable = mayEdit && record !== undefined && record.record_status !== "retired";
  const within: Level[] = level === "region" ? ["region", "site"] : ["location"];

  return (
    <>
      {record && adding && (
        <NewPlace
          level={adding}
          within={{ level, place: record }}
          onCancel={() => setAdding(null)}
          onCreated={(made) => {
            setAdding(null);
            onTreeChanged();
            onCreated(adding, made);
          }}
        />
      )}
      <section
        aria-labelledby="place"
        className="place-detail"
        data-testid="place"
        data-level={level}
        data-hid={hid}
      >
        <h2 id="place">
          {record ? record.name : levelLabel(level)}
          <span className="badge badge-plain">{levelLabel(level)}</span>
          {record && record.record_status !== "active" && (
            <span className="badge">{optionLabel(RECORD_STATUSES, record.record_status)}</span>
          )}
        </h2>
        <Problem error={place.error} />
        <Problem error={listsError} />
        <Notice text={done} />
        {place.loading && !record && (
          <p role="status" className="muted loading-late">
            Loading…
          </p>
        )}
        {record && (
          <>
            <p className="place-path" data-testid="place-path">
              {record.path}
            </p>
            <p className="actions">
              <Link to={itemsWithin(record.hid)}>Items within it, in the grid of items</Link>
              {editable &&
                !adding &&
                within.map((child) => (
                  <button type="button" key={child} onClick={() => setAdding(child)}>
                    New {levelLabel(child).toLowerCase()} in it
                  </button>
                ))}
            </p>
            <PlaceFacts place={record} choices={choices} to={to} />
            <InForce level={level} place={record} turn={turn} to={to} />
            <AssignedHere
              level={level}
              place={record}
              choices={choices}
              mayEdit={editable}
              turn={turn}
              onChanged={(text) => changed(text, false)}
            />
            {editable && ready && (
              <section aria-labelledby="place-details">
                <h3 id="place-details">Details</h3>
                <EditForm<Place, PlacePatch>
                  key={`${record.hid} ${record.row_version}`}
                  specs={specs}
                  record={record}
                  save={(body) => patchPlace(level, record.hid, body)}
                  onSaved={() => changed(`The ${level} was saved.`)}
                  onReload={place.reload}
                />
              </section>
            )}
            {editable && (
              <Move
                key={`move ${record.hid} ${record.row_version}`}
                level={level}
                place={record}
                onMoved={changed}
                onReload={place.reload}
              />
            )}
            {mayEdit && (
              <PlaceStatus
                key={`status ${record.hid} ${record.row_version}`}
                level={level}
                place={record}
                onChanged={changed}
                onReload={place.reload}
              />
            )}
          </>
        )}
      </section>
    </>
  );
}

type To = (level: string, hid: string) => { pathname: string; search: string };

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children || <Dash />}</dd>
    </>
  );
}

/** What the place itself holds: what it is in, its own fields and its tags. */
function PlaceFacts(props: { place: Place; choices: readonly Choice[] | undefined; to: To }) {
  const { place, choices, to } = props;
  const street = isRegion(place) ? [] : addressLines(addressOf(place));
  const coordinates = !isRegion(place) && place.latitude && place.longitude;
  return (
    <dl className="facts" data-testid="place-facts">
      {isRegion(place) && (
        <Fact label="In region">
          {place.parent ? (
            <Link to={to("region", place.parent.hid)}>{place.parent.path}</Link>
          ) : (
            <span className="muted">None: a region at the top</span>
          )}
        </Fact>
      )}
      {isSite(place) && (
        <Fact label="In region">
          <Link to={to("region", place.region.hid)}>{place.region.path}</Link>
        </Fact>
      )}
      {isLocation(place) && (
        <>
          <Fact label="In site">
            <Link to={to("site", place.site.hid)}>{place.site.path}</Link>
          </Fact>
          <Fact label="In location">
            {place.parent ? (
              <Link to={to("location", place.parent.hid)}>{place.parent.name}</Link>
            ) : (
              <span className="muted">None: directly in the site</span>
            )}
          </Fact>
          <Fact label="Kind">{choiceLabel(choices, LOCATION_KIND_LIST, place.kind)}</Fact>
        </>
      )}
      <Fact label="Code">{place.code}</Fact>
      {!isRegion(place) && (
        <>
          <Fact label="Street address">{street.join(", ")}</Fact>
          <Fact label="Coordinates">
            {coordinates ? `${place.latitude}, ${place.longitude}` : ""}
          </Fact>
        </>
      )}
      <Fact label="Holds">
        <span data-testid="place-holds">
          {isRegion(place) &&
            `${plural(place.regions, "region")} and ${plural(place.sites, "site")} directly in it`}
          {isSite(place) && plural(place.locations, "location")}
          {isLocation(place) &&
            `${plural(place.locations, "location")} directly in it, and ${plural(place.items, "item")} placed here itself`}
        </span>
      </Fact>
      <Fact label="Notes">{place.notes}</Fact>
      <Fact label="Tags">
        <span data-testid="place-tags">{place.tags.join(", ")}</span>
      </Fact>
      <Fact label="Changed">
        <Time at={place.updated_at} />
      </Fact>
      <Fact label="HID">
        <span className="mono">{place.hid}</span>
      </Fact>
    </dl>
  );
}

/** Where something in force came from: the place itself, or a level above it, by its path. */
function From(props: {
  source: PlaceEffective["ship_address"]["source"];
  hid: string | null;
  path: string | null;
  to: To;
}) {
  const { source, hid, path, to } = props;
  if (source === "own") return "Set here";
  if (source === "none") return "Not set";
  return (
    <>
      From the {source} {hid ? <Link to={to(source, hid)}>{path ?? hid}</Link> : (path ?? "")}
    </>
  );
}

/**
 * What the place has in force: the contacts of each role, and the shipping address and
 * instructions, each with the level it came from. What came from a level above is shown
 * lighter, as an inherited value is in the grid.
 */
function InForce(props: { level: Level; place: Place; turn: number; to: To }) {
  const { level, place, turn, to } = props;
  const effective = useLoad(`effective ${level} ${place.hid}`, (signal) =>
    readEffective(level, place.hid, signal),
  );
  // Read again after every change made here, and stays on show meanwhile.
  useReloadOn(turn, effective.reload);
  const data = effective.data;
  return (
    <section aria-labelledby="in-force">
      <h3 id="in-force">In force</h3>
      <p className="hint">
        What holds for this {level}: its own where it has any, and otherwise what the nearest level
        above it has. Nothing is copied down, so a change above shows here at once.
      </p>
      <Problem error={effective.error} />
      {effective.loading && !data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {data && (
        <>
          <div className="scroll">
            <table data-testid="in-force-contacts">
              <caption className="visually-hidden">
                The contacts in force for {place.path}, by role, each with the level it came from
              </caption>
              <thead>
                <tr>
                  <th scope="col">Role</th>
                  <th scope="col">Contacts</th>
                  <th scope="col">From</th>
                </tr>
              </thead>
              <tbody>
                {data.contacts.map((role) => {
                  const lighter = fromAbove(role.source) ? "inherited" : undefined;
                  return (
                    <tr
                      key={role.role}
                      data-role={role.role}
                      data-source={role.source}
                      data-stopped={role.stopped ? "true" : "false"}
                    >
                      <th scope="row">{role.label}</th>
                      <td className={lighter}>
                        {role.contacts.length > 0 ? (
                          <ul className="plain-list">
                            {role.contacts.map((contact) => (
                              <li key={contact.assignment_hid}>
                                <Link
                                  to={`/contacts/${encodeURIComponent(contact.contact_hid)}`}
                                  {...(lighter ? { className: "link-inherited" } : {})}
                                >
                                  {contact.name}
                                </Link>
                                {contactLine({ ...contact, name: "" }) && (
                                  <span> · {contactLine({ ...contact, name: "" })}</span>
                                )}
                                {contact.record_status !== "active" && (
                                  <span className="badge">
                                    {optionLabel(RECORD_STATUSES, contact.record_status)}
                                  </span>
                                )}
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <span className="muted">{noContactText(role)}</span>
                        )}
                      </td>
                      <td className={lighter}>
                        <From
                          source={role.source}
                          hid={role.source_hid}
                          path={role.source_path}
                          to={to}
                        />
                      </td>
                    </tr>
                  );
                })}
                {data.contacts.length === 0 && (
                  <tr>
                    <td colSpan={3} className="muted">
                      The list of contact roles is empty.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <dl className="facts" data-testid="in-force-shipping">
            <dt>Shipping address</dt>
            <dd
              data-testid="ship-address"
              data-source={data.ship_address.source}
              className={fromAbove(data.ship_address.source) ? "inherited" : undefined}
            >
              {addressLines(data.ship_address.value).join(", ") || <Dash />}
              <span>
                {" · "}
                <From
                  source={data.ship_address.source}
                  hid={data.ship_address.source_hid}
                  path={data.ship_address.source_path}
                  to={to}
                />
              </span>
            </dd>
            <dt>Shipping instructions</dt>
            <dd
              data-testid="ship-instructions"
              data-source={data.ship_instructions.source}
              className={fromAbove(data.ship_instructions.source) ? "inherited" : undefined}
            >
              {data.ship_instructions.value || <Dash />}
              <span>
                {" · "}
                <From
                  source={data.ship_instructions.source}
                  hid={data.ship_instructions.source_hid}
                  path={data.ship_instructions.source_path}
                  to={to}
                />
              </span>
            </dd>
          </dl>
        </>
      )}
    </section>
  );
}

interface AssignedHereProps {
  level: Level;
  place: Place;
  choices: readonly Choice[] | undefined;
  mayEdit: boolean;
  turn: number;
  onChanged: (text: string) => void;
}

/**
 * The contacts assigned to the place itself, by role: add one, change its priority,
 * remove it, or say that the place has nobody in a role and that nothing further up is
 * to be looked at.
 */
function AssignedHere({ level, place, choices, mayEdit, turn, onChanged }: AssignedHereProps) {
  const field = ASSIGNED_TO[level];
  const assignments = useLoad(`assignments ${level} ${place.hid}`, (signal) =>
    api.request("get", "/api/v1/contact-assignments", {
      query: { filter: `${field}:eq:${place.hid}`, limit: EVERY },
      signal,
    }),
  );
  useReloadOn(turn, assignments.reload);
  const removing = useAction();
  const roles = ownRoles(assignments.data?.items ?? [], choices);
  const any = roles.some((role) => role.assigned.length > 0 || role.stop !== null);

  async function remove(assignment: Assignment, done: string) {
    const result = await removing.run(() =>
      api.request("delete", "/api/v1/contact-assignments/{hid}", { path: { hid: assignment.hid } }),
    );
    if (result.ok) onChanged(done);
  }

  return (
    <section aria-labelledby="assigned-here">
      <h3 id="assigned-here">Contacts assigned here</h3>
      <p className="hint">
        The contacts of this {level} itself. A role with none here takes those of the nearest level
        above that has any, unless this {level} says that it has none and that nothing further up is
        to be looked at.
      </p>
      <Problem error={assignments.error} />
      <Problem error={removing.error} />
      {assignments.loading && !assignments.data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {assignments.data && !any && <p className="muted">No contact is assigned here.</p>}
      {any && (
        <div className="scroll">
          <table data-testid="own-contacts">
            <caption className="visually-hidden">
              The contacts assigned to {place.path} itself, by role and priority
            </caption>
            <thead>
              <tr>
                <th scope="col">Role</th>
                <th scope="col">Contact</th>
                <th scope="col">Priority</th>
                {mayEdit && <th scope="col">Change</th>}
              </tr>
            </thead>
            <tbody>
              {roles.flatMap((role) => [
                ...role.assigned.map((assignment) => {
                  const name = assignment.contact?.name ?? "the contact";
                  return (
                    <tr key={assignment.hid} data-role={role.role} data-assignment={assignment.hid}>
                      <th scope="row">{role.label}</th>
                      <td>
                        {assignment.contact ? (
                          <>
                            <Link to={`/contacts/${encodeURIComponent(assignment.contact.hid)}`}>
                              {assignment.contact.name}
                            </Link>
                            {assignment.contact.record_status !== "active" && (
                              <span className="badge">
                                {optionLabel(RECORD_STATUSES, assignment.contact.record_status)}
                              </span>
                            )}
                          </>
                        ) : (
                          <Dash />
                        )}
                      </td>
                      <td data-testid="priority">{assignment.priority}</td>
                      {mayEdit && (
                        <td className="row-actions">
                          <Priority
                            key={`${assignment.hid} ${assignment.row_version}`}
                            assignment={assignment}
                            what={`${name} as ${role.label}`}
                            onChanged={onChanged}
                          />
                          <ConfirmButton
                            label="Remove"
                            title={`Remove ${name} as ${role.label} contact of ${place.name}?`}
                            confirmLabel="Remove contact"
                            onConfirm={() =>
                              remove(
                                assignment,
                                `${name} is no longer a ${role.label} contact of ${place.name}.`,
                              )
                            }
                            disabled={removing.busy}
                          >
                            <p>
                              The contact itself stays. What {place.name} then has in this role is
                              what is left here, or what the nearest level above it has.
                            </p>
                          </ConfirmButton>
                        </td>
                      )}
                    </tr>
                  );
                }),
                ...(role.stop
                  ? [
                      <tr key={role.stop.hid} data-role={role.role} data-stop="true">
                        <th scope="row">{role.label}</th>
                        <td colSpan={2}>None here, and nothing further up is looked at</td>
                        {mayEdit && (
                          <td className="row-actions">
                            <button
                              type="button"
                              disabled={removing.busy}
                              onClick={() =>
                                role.stop &&
                                remove(
                                  role.stop,
                                  `${place.name} takes its ${role.label} contacts from above again.`,
                                )
                              }
                            >
                              Look further up again
                              <span className="visually-hidden"> for {role.label}</span>
                            </button>
                          </td>
                        )}
                      </tr>,
                    ]
                  : []),
              ])}
            </tbody>
          </table>
        </div>
      )}
      {mayEdit && <Assign level={level} place={place} choices={choices} onChanged={onChanged} />}
    </section>
  );
}

/** Change the priority of one assignment: 1 is the first to be asked. */
function Priority(props: {
  assignment: Assignment;
  what: string;
  onChanged: (text: string) => void;
}) {
  const { assignment, what, onChanged } = props;
  const [typed, setTyped] = useState(String(assignment.priority));
  const action = useAction();
  const wanted = /^\d{1,4}$/.test(typed.trim()) ? Number.parseInt(typed.trim(), 10) : null;
  const refused = fieldErrors(action.error, ["priority"]).shown;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (wanted === null) return;
    const result = await action.run(() =>
      api.request("patch", "/api/v1/contact-assignments/{hid}", {
        path: { hid: assignment.hid },
        body: { row_version: assignment.row_version, priority: wanted },
      }),
    );
    if (result.ok) onChanged(`The priority of ${what} is now ${wanted}.`);
  }

  return (
    <form onSubmit={submit} className="cell-form" noValidate>
      <TextField
        label={`Priority of ${what}`}
        name="priority"
        value={typed}
        onChange={setTyped}
        inputMode="numeric"
        maxLength={4}
        autoComplete="off"
        disabled={action.busy}
        error={refused.priority ?? action.error?.message}
      />
      <button
        type="submit"
        disabled={action.busy || wanted === null || wanted === assignment.priority}
      >
        Set priority
      </button>
    </form>
  );
}

/** The form that assigns a contact to the place in a role, or says the place has none. */
function Assign(props: {
  level: Level;
  place: Place;
  choices: readonly Choice[] | undefined;
  onChanged: (text: string) => void;
}) {
  const { level, place, choices, onChanged } = props;
  const contacts = useContactOptions();
  const [role, setRole] = useState("");
  const [none, setNone] = useState(false);
  const [contact, setContact] = useState("");
  const [priority, setPriority] = useState("");
  const action = useAction();
  const roles = choiceOptions(choices, CONTACT_ROLE_LIST);
  const known = ["role", "contact_hid", "priority", "stop_inheritance"];
  const refused = fieldErrors(action.error, known).shown;
  const typed = priority.trim();
  const order = /^\d{1,4}$/.test(typed) ? Number.parseInt(typed, 10) : null;
  const ready = role !== "" && (none || contact !== "") && (typed === "" || order !== null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready) return;
    const body: Schemas["AssignmentCreate"] = {
      [ASSIGNED_TO[level]]: place.hid,
      role,
      ...(none
        ? { stop_inheritance: true }
        : { contact_hid: contact, ...(order === null ? {} : { priority: order }) }),
    };
    const result = await action.run(() =>
      api.request("post", "/api/v1/contact-assignments", { body }),
    );
    if (!result.ok) return;
    const label = optionLabel(roles, role);
    const name = result.value.contact?.name ?? "The contact";
    onChanged(
      none
        ? `${place.name} now has no ${label} contact, and nothing further up is looked at.`
        : `${name} is now a ${label} contact of ${place.name}.`,
    );
    setContact("");
    setPriority("");
    setNone(false);
  }

  return (
    <section aria-labelledby="assign-contact" className="panel">
      <h4 id="assign-contact">Assign a contact</h4>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={contacts.error} />
        <Problem error={action.error} shown={known} />
        <div className="fields">
          <SelectField
            label="Role"
            name="role"
            value={role}
            onChange={setRole}
            required
            disabled={action.busy}
            error={refused.role}
          >
            <option value="">Choose a role</option>
            {roles.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="Contact"
            name="contact_hid"
            value={none ? "" : contact}
            onChange={setContact}
            disabled={action.busy || none}
            error={refused.contact_hid}
            hint="A contact is made under Contacts, then assigned here"
          >
            <option value="">Choose a contact</option>
            {(contacts.data ?? []).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </SelectField>
          <TextField
            label="Priority"
            name="priority"
            value={none ? "" : priority}
            onChange={setPriority}
            inputMode="numeric"
            maxLength={4}
            autoComplete="off"
            disabled={action.busy || none}
            error={
              refused.priority ?? (typed !== "" && order === null ? "A whole number." : undefined)
            }
            hint="1 is asked first. Left blank, after the last one of the role."
          />
        </div>
        <CheckField
          label="None here, and do not look further up"
          name="stop_inheritance"
          checked={none}
          onChange={setNone}
          disabled={action.busy}
          error={refused.stop_inheritance}
          hint={`Says that this ${level} has nobody in the role, in place of a contact. It stands alone for the role.`}
        />
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || !ready}>
            {none ? "Say there is none" : "Assign contact"}
          </button>
        </p>
      </form>
    </section>
  );
}

interface MoveProps {
  level: Level;
  place: Place;
  onMoved: (text: string) => void;
  onReload: () => void;
}

/**
 * Move a place: a region to another parent or to the top, a site to another region, a
 * location to another place within its site. It is one change of one record: the paths
 * and the totals follow, and nothing in the place is written to.
 */
function Move({ level, place, onMoved, onReload }: MoveProps) {
  const regions = useRegions();
  const site = isLocation(place) ? place.site_hid : "";
  const locations = useLoad(`locations-of ${site}`, async (signal) => {
    if (site === "") return [];
    const page = await api.request("get", "/api/v1/locations", {
      query: { filter: `site_hid:eq:${site}`, limit: EVERY, include_drafts: true },
      signal,
    });
    return [...page.items].sort((one, other) => one.path.localeCompare(other.path));
  });
  const action = useAction();
  const field =
    level === "region"
      ? "parent_region_hid"
      : level === "site"
        ? "region_hid"
        : "parent_location_hid";
  const now = isLocation(place)
    ? (place.parent_location_hid ?? "")
    : isSite(place)
      ? place.region_hid
      : isRegion(place)
        ? (place.parent_region_hid ?? "")
        : "";
  const [wanted, setWanted] = useState(now);
  const refused = fieldErrors(action.error, [field]).shown;

  let options: Option[] = [];
  let top = "";
  let label = "Region";
  let hint = "";
  if (isLocation(place)) {
    options = locationsToMoveTo(locations.data ?? [], place);
    top = "Directly in the site";
    label = "In location";
    hint = "Another location of the same site. A location stays in the site it was made in.";
  } else if (isSite(place)) {
    options = (regions.data ?? []).map((region) => ({ value: region.hid, label: region.path }));
    hint =
      "The site moves with everything in it: its locations keep their items, and take the new path.";
  } else if (isRegion(place)) {
    options = regionsToMoveTo(regions.data ?? [], place);
    top = "At the top: in no region";
    label = "In region";
    hint = "The region moves with every region, site and location in it.";
  }
  // The place it is in now is offered also when the list did not bring it.
  if (now !== "" && !options.some((option) => option.value === now)) {
    const parent = isSite(place) ? place.region : place.parent;
    if (parent) options = [{ value: parent.hid, label: parent.path }, ...options];
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const result = await action.run(() =>
      patchPlace(level, place.hid, {
        row_version: place.row_version,
        [field]: wanted === "" ? null : wanted,
      }),
    );
    if (result.ok) onMoved(`${place.name} was moved: it is now ${result.value.path}.`);
  }

  return (
    <section aria-labelledby="move-place">
      <h3 id="move-place">Move</h3>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={regions.error ?? locations.error} />
        <Problem error={action.error} shown={[field]} onReload={onReload} />
        <div className="fields">
          <SelectField
            label={label}
            name={field}
            value={wanted}
            onChange={setWanted}
            disabled={action.busy}
            error={refused[field]}
            hint={hint}
          >
            {top !== "" && <option value="">{top}</option>}
            {options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </SelectField>
        </div>
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || wanted === now}>
            Move {levelLabel(level).toLowerCase()}
          </button>
        </p>
      </form>
    </section>
  );
}

interface PlaceStatusProps {
  level: Level;
  place: Place;
  onChanged: (text: string) => void;
  onReload: () => void;
}

/** Retire a place that holds nothing, or bring a retired one back. Nothing is deleted. */
function PlaceStatus({ level, place, onChanged, onReload }: PlaceStatusProps) {
  const action = useAction();
  const what = levelLabel(level).toLowerCase();

  async function retire() {
    const result = await action.run(() => retirePlace(level, place.hid, place.row_version));
    if (result.ok) onChanged(`The ${what} was retired.`);
  }

  async function bringBack() {
    const result = await action.run(() =>
      patchPlace(level, place.hid, { row_version: place.row_version, record_status: "active" }),
    );
    if (result.ok) onChanged(`The ${what} is active again.`);
  }

  return (
    <section aria-labelledby="retire-place">
      <h3 id="retire-place">{place.record_status === "retired" ? "Retired" : "Retire"}</h3>
      {/* A place is not brought back while what it is in is retired: the server says which
          to bring back first, as a sentence of its own. */}
      <Problem error={action.error} onReload={onReload} labels={{ record_status: "" }} />
      {place.record_status === "retired" ? (
        <>
          <p>This {what} is retired. Its record is kept, and it can be brought back.</p>
          <p className="actions">
            <button type="button" onClick={bringBack} disabled={action.busy}>
              Bring back as active
            </button>
          </p>
        </>
      ) : (
        <>
          <p>
            A {what} is retired only when nothing that is not retired is in it:{" "}
            {level === "region"
              ? "no region and no site."
              : level === "site"
                ? "no location."
                : "no location, no item and no device group."}{" "}
            A retired {what} is left out of the tree and is given to nothing further.
          </p>
          <p className="actions">
            <ConfirmButton
              label={`Retire ${what}`}
              title={`Retire ${place.name}?`}
              confirmLabel={`Retire ${what}`}
              onConfirm={retire}
              disabled={action.busy}
            >
              <p>
                The {what} stays on record and can be brought back. It is refused while something is
                still in it.
              </p>
            </ConfirmButton>
          </p>
        </>
      )}
    </section>
  );
}

// What a refusal calls the place a new one is made in: the form has no input for it.
const WITHIN_LABELS = {
  parent_region_hid: "The region it is in",
  region_hid: "The region it is in",
  site_hid: "The site it is in",
  parent_location_hid: "The location it is in",
} as const;

interface NewPlaceProps {
  level: Level;
  /** What the new place is in. Left out, a region at the top. */
  within?: { level: Level; place: Place };
  onCancel: () => void;
  onCreated: (place: Place) => void;
}

/** The form for a new region, site or location, within the place it is made in. */
export function NewPlace({ level, within, onCancel, onCreated }: NewPlaceProps) {
  const { lists, error } = usePlaceLists();
  const specs = useMemo(() => placeSpecs(level, lists), [level, lists]);
  const what = levelLabel(level).toLowerCase();
  const parent: PlaceCreate = !within
    ? {}
    : level === "region"
      ? { parent_region_hid: within.place.hid }
      : level === "site"
        ? { region_hid: within.place.hid }
        : within.level === "site"
          ? { site_hid: within.place.hid }
          : { parent_location_hid: within.place.hid };
  return (
    <CreateForm<PlaceCreate, Place>
      title={`New ${what}`}
      specs={specs}
      start={{ record_status: "active" }}
      create={(body) => createPlace(level, { ...body, ...parent })}
      onCreated={onCreated}
      onCancel={onCancel}
      submitLabel={`Create ${what}`}
      labels={WITHIN_LABELS}
    >
      <Problem error={error} />
      <p className="hint" data-testid="new-place-within">
        {within ? `In ${within.place.path}.` : "A region at the top, in no other region."} Its path
        is worked out from where it is, and follows when anything above it moves or is renamed.
      </p>
    </CreateForm>
  );
}
