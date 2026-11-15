import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { Balance } from "../components/CapacityBalance";
import { CapacityTrend } from "../components/CapacityRecords";
import type { GridColumn } from "../components/grid/columns";
import { DataGrid } from "../components/grid/DataGrid";
import { Notice, Problem } from "../components/Problem";
import { CreateForm, EditForm } from "../components/RecordForm";
import { Retire } from "../components/Retire";
import { Time } from "../components/Time";
import {
  CATEGORY_LIST,
  type CapacityLine,
  capacityLinePath,
  EFFECTS,
  lineForForm,
  MULTIPLY,
  measureText,
  multiplies,
  SIDES,
  STAFF,
  staffLineOptions,
  supplyCategories,
} from "../lib/capacity";
import { formatTime } from "../lib/format";
import { queryParams } from "../lib/gridQuery";
import { useLoad, useTitle } from "../lib/hooks";
import {
  EVERY,
  useChoices,
  useMoney,
  useRegionOptions,
  useSiteOptions,
  useVendorOptions,
  withCurrent,
} from "../lib/lists";
import {
  choiceFilterOptions,
  choiceLabel,
  optionLabel,
  RECORD_STATUSES,
  SETTABLE_STATUSES,
} from "../lib/options";
import type { FieldSpec, Option } from "../lib/patch";
import { allows } from "../lib/roles";

type Choice = Schemas["ChoiceOut"];

function Dash() {
  return <span className="muted">—</span>;
}

function lineColumns(choices: readonly Choice[] | undefined): GridColumn<CapacityLine>[] {
  return [
    {
      id: "side",
      header: "Side",
      kind: "choice",
      value: (line) => optionLabel(SIDES, line.side),
      choices: SIDES,
      width: 110,
    },
    {
      id: "category",
      header: "Category",
      kind: "choice",
      value: (line) => line.category_label || choiceLabel(choices, CATEGORY_LIST, line.category),
      choices: choiceFilterOptions(choices, CATEGORY_LIST),
      width: 190,
    },
    {
      id: "name",
      header: "Name",
      kind: "text",
      value: (line) => line.name,
      link: true,
      width: 260,
    },
    {
      // Whether it adds a fixed amount or multiplies the staff lines it applies to.
      id: "effect",
      header: "Effect",
      kind: "choice",
      value: (line) => optionLabel(EFFECTS, line.effect),
      choices: EFFECTS,
      width: 130,
    },
    {
      id: "quantity",
      header: "Quantity",
      kind: "number",
      value: (line) => line.quantity,
      numeric: true,
      width: 110,
    },
    {
      id: "units_each",
      header: "Units each",
      kind: "number",
      value: (line) => line.units_each,
      numeric: true,
      width: 120,
    },
    {
      // Quantity times units each: worked out by the server. A line that multiplies has
      // none of its own: its gain is in the report, for each view.
      id: "units",
      header: "Units",
      kind: "number",
      value: (line) => line.units,
      numeric: true,
      width: 100,
    },
    {
      // A line that multiplies: how much more one person does with it.
      id: "factor",
      header: "Factor",
      kind: "number",
      value: (line) => line.factor,
      numeric: true,
      width: 100,
    },
    {
      // A line that multiplies: the share of the positions that use it.
      id: "share",
      header: "Share",
      kind: "number",
      value: (line) => line.share,
      numeric: true,
      width: 100,
    },
    {
      // A line that multiplies: the staff lines it works on, by name. The server filters
      // by any of them and sorts by the first.
      id: "applies_to",
      header: "Applies to",
      kind: "text",
      value: (line) => line.applies_to.map((target) => target.name).join(", "),
      width: 240,
    },
    {
      // It counts today: not before it starts, and not after it ends.
      id: "in_date",
      header: "In date",
      kind: "boolean",
      column: null,
      value: (line) => (line.in_date ? "Yes" : "No"),
      width: 110,
    },
    {
      id: "annual_cost",
      header: "Annual cost",
      kind: "number",
      value: (line) => line.annual_cost,
      numeric: true,
      width: 130,
    },
    {
      id: "vendor",
      header: "Vendor",
      kind: "text",
      value: (line) => line.vendor?.name,
      width: 150,
    },
    {
      id: "region",
      header: "Region",
      kind: "text",
      value: (line) => line.region?.name,
      hint: (line) => line.region?.path,
      hide: true,
      width: 150,
    },
    {
      id: "site",
      header: "Site",
      kind: "text",
      value: (line) => line.site?.name,
      hint: (line) => line.site?.path,
      hide: true,
      width: 150,
    },
    {
      id: "starts_on",
      header: "Starts",
      kind: "date",
      value: (line) => line.starts_on,
      width: 130,
    },
    { id: "ends_on", header: "Ends", kind: "date", value: (line) => line.ends_on, width: 130 },
    {
      id: "record_status",
      header: "Record status",
      kind: "choice",
      value: (line) => optionLabel(RECORD_STATUSES, line.record_status),
      choices: RECORD_STATUSES,
      width: 140,
    },
    { id: "notes", header: "Notes", kind: "text", value: (line) => line.notes, hide: true },
    {
      id: "updated_at",
      header: "Changed",
      kind: "timestamp",
      value: (line) => formatTime(line.updated_at),
      hide: true,
    },
    {
      id: "hid",
      header: "HID",
      kind: "reference",
      value: (line) => line.hid,
      mono: true,
      hide: true,
    },
  ];
}

interface LineLists {
  categories: readonly Option[];
  vendors: readonly Option[];
  regions: readonly Option[];
  sites: readonly Option[];
  /** The staff lines that add, which a line that multiplies may work on. */
  staff: readonly Option[];
}

/**
 * The fields of a capacity line that a form sets. The side is chosen when the line is
 * made and stays: a demand line is other work, and has no category to choose. A supply
 * line adds a fixed amount, its quantity times the units of one, or multiplies the staff
 * lines it applies to: then it has a factor and a share in place of a quantity.
 */
function lineSpecs(lists: LineLists, line: CapacityLine | null): FieldSpec[] {
  const supply = (values: Record<string, unknown>) => (line ? line.side : values.side) === "supply";
  const multiplying = (values: Record<string, unknown>) =>
    supply(values) && values.effect === MULTIPLY;
  const adding = (values: Record<string, unknown>) => !multiplying(values);
  return [
    ...(line
      ? []
      : [
          {
            name: "side",
            label: "Side",
            kind: "choice",
            required: true,
            options: SIDES,
            hint: "Supply is a source of resource units. Demand is work that is not the infrastructure: a project, a transition. The infrastructure itself is counted from the inventory.",
          } satisfies FieldSpec,
        ]),
    {
      name: "category",
      label: "Category",
      kind: "choice",
      options: lists.categories,
      ...(line ? {} : { blank: "Choose a category" }),
      when: supply,
      hint: "Staff is the team's own positions. A level of seniority is a line of its own.",
    },
    {
      name: "effect",
      label: "Effect",
      kind: "choice",
      options: EFFECTS,
      when: supply,
      hint: "A line adds its units. A tool or a service that makes people more effective, of the category Tools or Services, multiplies the staff lines it applies to instead, and has no quantity of its own.",
    },
    {
      name: "name",
      label: "Name",
      kind: "text",
      required: true,
      maxLength: 200,
      hint: "A kind of position, a service, a tool, or a piece of other work: never a person. Unique on its side.",
    },
    {
      name: "quantity",
      label: "Quantity",
      kind: "decimal",
      places: 2,
      when: adding,
      hint: "Positions, contracted blocks of hours, subscriptions.",
    },
    {
      name: "units_each",
      label: "Units each",
      kind: "decimal",
      places: 2,
      required: true,
      when: adding,
      hint: "The resource units that one of the quantity provides, or takes. By convention one mid-level position is 1.0.",
    },
    {
      name: "factor",
      label: "Factor",
      kind: "decimal",
      places: 2,
      required: true,
      when: multiplying,
      hint: "How much more one person does with it, at least 1: 1.25 is a quarter more.",
    },
    {
      name: "share",
      label: "Share",
      kind: "decimal",
      places: 2,
      when: multiplying,
      hint: "The share of the positions that use it, from 0 to 1. Left blank, 1: all of them.",
    },
    {
      name: "applies_to",
      label: "Applies to",
      kind: "set",
      options: lists.staff,
      required: true,
      when: multiplying,
      hint: "The staff lines it works on, which add. Its gain is (factor − 1) × share × their units in each view, in its own category; it works on their units alone, and does not compound another line that multiplies.",
    },
    {
      name: "annual_cost",
      label: "Annual cost",
      kind: "decimal",
      places: 2,
      hint: "Optional, for comparing options.",
    },
    {
      name: "vendor_hid",
      label: "Vendor",
      kind: "choice",
      options: lists.vendors,
      blank: "None",
      hint: "The line is then in that vendor's portfolio.",
    },
    {
      name: "region_hid",
      label: "Region it serves",
      kind: "choice",
      options: lists.regions,
      blank: "Everywhere",
      hint: "A region or a site, not both. It is kept and shown, and narrows nothing yet: the balance is of the whole installation.",
    },
    {
      name: "site_hid",
      label: "Site it serves",
      kind: "choice",
      options: lists.sites,
      blank: "Everywhere",
    },
    {
      name: "starts_on",
      label: "Starts on",
      kind: "date",
      hint: "Outside its dates a line is not counted.",
    },
    { name: "ends_on", label: "Ends on", kind: "date" },
    {
      name: "record_status",
      label: "Record status",
      kind: "choice",
      options: SETTABLE_STATUSES,
      hint: "A draft line is a what-if: it counts only in the balance with drafts.",
    },
    { name: "notes", label: "Notes", kind: "longtext", maxLength: 10000 },
  ];
}

/** The staff lines that add, drafts among them: what a line that multiplies may work on. */
function useStaffLines() {
  return useLoad("capacity-staff-lines", async (signal) => {
    const page = await api.request("get", "/api/v1/capacity-lines", {
      query: {
        filter: `side:eq:supply category:eq:${STAFF} effect:eq:add`,
        include_drafts: true,
        sort: ["name"],
        limit: EVERY,
      },
      signal,
    });
    return page.items;
  });
}

function useLineLists(choices: readonly Choice[] | undefined, line: CapacityLine | null) {
  const vendors = useVendorOptions();
  const regions = useRegionOptions();
  const sites = useSiteOptions();
  const staff = useStaffLines();
  const lists = useMemo<LineLists>(
    () => ({
      staff: staffLineOptions(staff.data ?? [], line),
      categories: supplyCategories(choices, line?.category ?? null),
      vendors: withCurrent(
        vendors.data,
        line?.vendor ? { value: line.vendor.hid, label: line.vendor.name } : null,
      ),
      regions: withCurrent(
        regions.data,
        line?.region ? { value: line.region.hid, label: line.region.path } : null,
      ),
      sites: withCurrent(
        sites.data,
        line?.site ? { value: line.site.hid, label: line.site.path } : null,
      ),
    }),
    [choices, vendors.data, regions.data, sites.data, staff.data, line],
  );
  return {
    lists,
    loading: vendors.loading || regions.loading || sites.loading || staff.loading,
    error: vendors.error ?? regions.error ?? sites.error ?? staff.error,
  };
}

/**
 * Capacity: demand beside supply, the balance and the coverage, without the drafts and
 * with them, and the lines the supply and the other work are made of. The purpose is
 * right-sizing the team.
 */
export function Capacity() {
  useTitle("Capacity");
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const startFilter = params.get("filter");
  const [adding, setAdding] = useState(false);
  const choices = useChoices();
  const { lists, error } = useLineLists(choices.data, null);
  const columns = useMemo(() => lineColumns(choices.data), [choices.data]);
  const specs = useMemo(() => lineSpecs(lists, null), [lists]);
  const report = useLoad("capacity-report", (signal) =>
    api.request("get", "/api/v1/reports/capacity", { signal }),
  );
  const money = useMoney();

  return (
    <>
      <h1>Capacity</h1>
      <p>
        The support weight of the inventory is demand. It is balanced against the resource units
        that staff positions, services, smart hands and tools supply, and against other work that
        calls on the same people. The balance is of the whole installation, as of today.
      </p>
      <Problem error={report.error} />
      <Problem error={choices.error ?? error} />
      {report.loading && !report.data && (
        <p role="status" className="muted loading-late">
          Working it out…
        </p>
      )}
      {report.data && <Balance report={report.data} money={money} />}
      <CapacityTrend mayEdit={allows(user.role, "inventory")} />
      <section aria-labelledby="capacity-lines">
        <h2 id="capacity-lines">Lines</h2>
        <p>
          A supply line is a source of resource units; a demand line is work that is not the
          infrastructure. A draft line is a what-if: turn Include drafts on to see them here. A line
          is opened to change it, and is retired or given an end date, never deleted.
        </p>
        {adding && (
          <CreateForm<Schemas["CapacityLineCreate"], CapacityLine>
            title="New capacity line"
            specs={specs}
            start={{ side: "supply", effect: "add", quantity: "1", record_status: "active" }}
            create={(body) => api.request("post", "/api/v1/capacity-lines", { body })}
            onCreated={(line) => navigate(capacityLinePath(line.hid))}
            onCancel={() => setAdding(false)}
            submitLabel="Create line"
          />
        )}
        {!choices.loading && (
          <DataGrid<CapacityLine>
            key={startFilter ?? ""}
            id="capacity-lines"
            noun={["line", "lines"]}
            entity="capacity_lines"
            columns={columns}
            load={(request, signal) =>
              api.request("get", "/api/v1/capacity-lines", { query: queryParams(request), signal })
            }
            rowId={(line) => line.hid}
            rowLink={(line) => capacityLinePath(line.hid)}
            dimmed={(line) => line.record_status !== "active" || !line.in_date}
            shortFilter="side:eq:supply category:eq:staff"
            startFilter={startFilter}
            switches={{ archived: "Include archived", drafts: "Include drafts" }}
          >
            {allows(user.role, "inventory") && !adding && (
              <button type="button" className="primary" onClick={() => setAdding(true)}>
                New line
              </button>
            )}
          </DataGrid>
        )}
      </section>
    </>
  );
}

/** Capacity → one line: what it is, the form that changes it, and retiring it. */
export function CapacityLineDetail() {
  const { hid = "" } = useParams();
  const { user } = useAuth();
  const mayEdit = allows(user.role, "inventory");
  const line = useLoad(`capacity-line ${hid}`, (signal) =>
    api.request("get", "/api/v1/capacity-lines/{hid}", { path: { hid }, signal }),
  );
  const choices = useChoices();
  const record = line.data;
  const { lists, loading, error } = useLineLists(choices.data, record ?? null);
  const [done, setDone] = useState("");
  const money = useMoney();
  useTitle(record ? record.name : "Capacity line");
  const specs = useMemo(() => lineSpecs(lists, record ?? null), [lists, record]);

  function changed(text: string) {
    setDone(text);
    line.reload();
  }

  return (
    <>
      <p className="crumbs">
        <Link to="/capacity">Capacity</Link>
      </p>
      <h1>
        {record ? record.name : "Capacity line"}
        {record && <span className="badge badge-plain">{optionLabel(SIDES, record.side)}</span>}
        {record && record.record_status !== "active" && (
          <span className="badge">{optionLabel(RECORD_STATUSES, record.record_status)}</span>
        )}
      </h1>
      <Problem error={line.error} />
      <Problem error={choices.error ?? error} />
      <Notice text={done} />
      {line.loading && !record && <p role="status">Loading…</p>}
      {record && (
        <>
          <dl className="facts" data-testid="capacity-line-facts">
            <dt>Side</dt>
            <dd>{optionLabel(SIDES, record.side)}</dd>
            <dt>Category</dt>
            <dd>{record.category_label || record.category}</dd>
            {record.side === "supply" && (
              <>
                <dt>Effect</dt>
                <dd data-testid="line-effect">{optionLabel(EFFECTS, record.effect)}</dd>
              </>
            )}
            {multiplies(record) ? (
              <>
                <dt>Factor</dt>
                <dd data-testid="line-factor">{measureText(record.factor, "units")}</dd>
                <dt>Share</dt>
                <dd data-testid="line-share">{measureText(record.share, "units")}</dd>
                <dt>Applies to</dt>
                <dd data-testid="line-applies-to">
                  {record.applies_to.length === 0 ? (
                    <Dash />
                  ) : (
                    <ul className="plain-list">
                      {record.applies_to.map((target) => (
                        <li key={target.hid}>
                          <Link to={capacityLinePath(target.hid)}>{target.name}</Link>
                        </li>
                      ))}
                    </ul>
                  )}
                </dd>
                <dt>Units</dt>
                <dd data-testid="line-units">
                  <span className="muted">
                    (factor − 1) × share × the units of the lines it applies to, in each view:{" "}
                    <Link to="/capacity">see Lines that multiply</Link>
                  </span>
                </dd>
              </>
            ) : (
              <>
                <dt>Quantity</dt>
                <dd>{measureText(record.quantity, "units")}</dd>
                <dt>Units each</dt>
                <dd>{measureText(record.units_each, "units")}</dd>
                <dt>Units</dt>
                <dd data-testid="line-units">
                  {measureText(record.units, "units")}
                  <span className="muted"> · quantity × units each</span>
                </dd>
              </>
            )}
            <dt>Counts today</dt>
            <dd data-testid="line-counts">
              {record.record_status === "retired"
                ? "No: it is retired"
                : !record.in_date
                  ? "No: today is outside its dates"
                  : record.record_status === "draft"
                    ? "Only with the drafts: it is a what-if"
                    : "Yes"}
            </dd>
            <dt>Annual cost{money}</dt>
            <dd>{record.annual_cost ? measureText(record.annual_cost, "money") : <Dash />}</dd>
            <dt>Vendor</dt>
            <dd>
              {record.vendor ? (
                <Link to={`/vendors/${encodeURIComponent(record.vendor.hid)}`}>
                  {record.vendor.name}
                </Link>
              ) : (
                <Dash />
              )}
            </dd>
            <dt>Serves</dt>
            <dd>{record.site?.path ?? record.region?.path ?? "Everywhere"}</dd>
            <dt>Period</dt>
            <dd>
              {record.starts_on ?? "from the beginning"} to {record.ends_on ?? "further notice"}
            </dd>
            <dt>Notes</dt>
            <dd>{record.notes || <Dash />}</dd>
            <dt>Changed</dt>
            <dd>
              <Time at={record.updated_at} />
            </dd>
            <dt>HID</dt>
            <dd className="mono">{record.hid}</dd>
          </dl>
          {mayEdit && record.record_status !== "retired" && !loading && !choices.loading && (
            <section aria-labelledby="details">
              <h2 id="details">Details</h2>
              <EditForm<ReturnType<typeof lineForForm>, Schemas["CapacityLinePatch"]>
                key={`${record.hid} ${record.row_version}`}
                specs={specs}
                record={lineForForm(record)}
                save={(body) =>
                  api.request("patch", "/api/v1/capacity-lines/{hid}", {
                    path: { hid: record.hid },
                    body,
                  })
                }
                onSaved={() => changed("The line was saved.")}
                onReload={line.reload}
              />
            </section>
          )}
          {mayEdit && (
            <Retire
              key={`status ${record.hid} ${record.row_version}`}
              what="line"
              name={record.name}
              retired={record.record_status === "retired"}
              about="A retired line counts for nothing any more. To have it count until a day, give it an end date instead."
              retiredAbout="This line is retired: it counts for nothing."
              retire={() =>
                api.request("post", "/api/v1/capacity-lines/{hid}/retire", {
                  path: { hid: record.hid },
                  body: { row_version: record.row_version },
                })
              }
              bringBack={() =>
                api.request("patch", "/api/v1/capacity-lines/{hid}", {
                  path: { hid: record.hid },
                  body: { row_version: record.row_version, record_status: "active" },
                })
              }
              onChanged={changed}
              onReload={line.reload}
            />
          )}
        </>
      )}
    </>
  );
}
