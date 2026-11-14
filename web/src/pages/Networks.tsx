import { useState } from "react";
import { Link, NavLink, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { ConfirmButton } from "../components/ConfirmButton";
import type { GridColumn } from "../components/grid/columns";
import { DataGrid } from "../components/grid/DataGrid";
import { Notice, Problem } from "../components/Problem";
import { CreateForm, EditForm } from "../components/RecordForm";
import { SortTh } from "../components/SortTh";
import {
  ADDRESS_ROLES,
  type Address,
  addressRoleLabel,
  FAMILIES,
  familyLabel,
  holderPath,
  NETWORK_KINDS,
  primaryText,
} from "../lib/addresses";
import { formatTime, itemName, plural } from "../lib/format";
import { queryBody } from "../lib/gridQuery";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { EVERY } from "../lib/lists";
import { optionLabel } from "../lib/options";
import type { FieldSpec } from "../lib/patch";
import { allows } from "../lib/roles";
import { useSorting } from "../lib/useSorting";

type Network = Schemas["NetworkOut"];

/** The second row of navigation on the pages of addresses. */
function AddressNav() {
  return (
    <nav className="sub" aria-label="Addresses">
      <ul>
        <li>
          <NavLink to="/addresses">Addresses</NavLink>
        </li>
        <li>
          <NavLink to="/networks">Networks</NavLink>
        </li>
        <li>
          <NavLink to="/reports/duplicates">Held more than once</NavLink>
        </li>
      </ul>
    </nav>
  );
}

const COLUMNS: GridColumn<Address>[] = [
  {
    id: "address",
    header: "Address",
    kind: "address",
    value: (address) => address.address,
    // The page of a row is the page of the item or the group that has the address.
    link: true,
    mono: true,
    width: 220,
  },
  {
    id: "network.label",
    header: "Network",
    kind: "text",
    value: (address) => address.network?.label,
    width: 150,
  },
  {
    id: "item.name",
    header: "Item",
    kind: "text",
    value: (address) => (address.item ? itemName(address.item) : ""),
    width: 220,
  },
  {
    id: "group.name",
    header: "Group",
    kind: "text",
    value: (address) => address.group?.name,
    width: 200,
  },
  {
    id: "role",
    header: "Role",
    kind: "choice",
    value: (address) => addressRoleLabel(address.role),
    choices: ADDRESS_ROLES,
    width: 140,
  },
  {
    // Read from the address by the server: it filters, sorts and exports by it.
    id: "family",
    header: "Family",
    kind: "choice",
    value: (address) => familyLabel(address.family),
    choices: FAMILIES.map((family) => ({ value: String(family), label: familyLabel(family) })),
    width: 100,
  },
  {
    // A record may have a primary management address of each family.
    id: "is_primary",
    header: "Primary",
    kind: "boolean",
    value: (address) => (address.is_primary ? "Yes" : "No"),
    hint: (address) => (address.is_primary ? `${primaryText(address)} management address` : ""),
    width: 110,
  },
  {
    id: "updated_at",
    header: "Changed",
    kind: "timestamp",
    value: (address) => formatTime(address.updated_at),
    hide: true,
  },
  {
    id: "created_at",
    header: "Created",
    kind: "timestamp",
    value: (address) => formatTime(address.created_at),
    hide: true,
  },
  {
    id: "hid",
    header: "HID",
    kind: "reference",
    value: (address) => address.hid,
    mono: true,
    hide: true,
  },
];

/**
 * Addresses: every address of every item and device group, in the grid. An address is
 * added, changed and removed on the page of the item or the group that has it.
 */
export function AllAddresses() {
  useTitle("Addresses");
  const [params] = useSearchParams();
  const startFilter = params.get("filter");
  return (
    <>
      <AddressNav />
      <h1>Addresses</h1>
      <p>
        Every address of every item and device group. An address is added, changed and removed on
        the page of the item or the group that has it: open a row to go there.
      </p>
      <DataGrid<Address>
        key={startFilter ?? ""}
        id="addresses"
        noun={["address", "addresses"]}
        entity="addresses"
        columns={COLUMNS}
        load={(request, signal) =>
          api.request("post", "/api/v1/addresses/query", { body: queryBody(request), signal })
        }
        rowId={(address) => address.hid}
        rowLink={(address) => holderPath(address) ?? "/addresses"}
        shortFilter="network.label:eq:Red address:prefix:192.0.2."
        startFilter={startFilter}
      />
    </>
  );
}

const SPECS: FieldSpec[] = [
  {
    name: "label",
    label: "Label",
    kind: "text",
    required: true,
    maxLength: 100,
    hint: "Red, Black, Tenant1: a VRF, a tenant, a colour",
  },
  { name: "kind", label: "Kind", kind: "choice", options: NETWORK_KINDS },
];

/**
 * Networks: the labels an address may be under. The same address under two networks is
 * two addresses. A network that no address is under may be removed.
 */
export function Networks() {
  useTitle("Networks");
  const { user } = useAuth();
  const mayEdit = allows(user.role, "inventory");
  const [turn, setTurn] = useState(0);
  const networks = useLoad(`networks ${turn}`, (signal) =>
    api.request("get", "/api/v1/networks", { query: { limit: EVERY }, signal }),
  );
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState("");
  const [done, setDone] = useState("");
  const action = useAction();
  const rows = networks.data?.items ?? [];
  const open = rows.find((network) => network.hid === editing) ?? null;
  // The list is read whole, and is sorted here only when it is.
  const sorting = useSorting(
    rows,
    {
      label: (network) => network.label,
      kind: (network) => optionLabel(NETWORK_KINDS, network.kind),
      uses: (network) => network.uses,
    },
    { enabled: (networks.data?.total ?? 0) <= rows.length },
  );

  function changed(text: string) {
    setDone(text);
    setTurn((count) => count + 1);
  }

  async function remove(network: Network) {
    setDone("");
    const result = await action.run(() =>
      api.request("delete", "/api/v1/networks/{hid}", { path: { hid: network.hid } }),
    );
    if (result.ok) changed(`The network ${network.label} was removed.`);
  }

  return (
    <>
      <AddressNav />
      <h1>Networks</h1>
      <p>
        A network is a label for an address space: a VRF, a tenant, a colour. It is made here before
        an address is put under it. Renaming one renames it on every address at once, and one that
        any address is under cannot be removed.
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
            New network
          </button>
        </p>
      )}
      {adding && (
        <CreateForm<Schemas["NetworkCreate"], Network>
          title="New network"
          specs={SPECS}
          start={{ kind: "network" }}
          create={(body) => api.request("post", "/api/v1/networks", { body })}
          onCreated={(network) => {
            setAdding(false);
            changed(`The network ${network.label} was created.`);
          }}
          onCancel={() => setAdding(false)}
          submitLabel="Create network"
        />
      )}
      <Problem error={networks.error} />
      <Problem error={action.error} />
      <Notice text={done} />
      {networks.loading && !networks.data && <p role="status">Loading…</p>}
      {networks.data && (
        <div className="scroll">
          <table data-testid="networks">
            <caption className="visually-hidden">Networks, by label</caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="label">
                  Label
                </SortTh>
                <SortTh sort={sorting} column="kind">
                  Kind
                </SortTh>
                <SortTh sort={sorting} column="uses">
                  Addresses
                </SortTh>
                {mayEdit && (
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((network) => (
                <tr key={network.hid}>
                  <th scope="row">{network.label}</th>
                  <td>{optionLabel(NETWORK_KINDS, network.kind)}</td>
                  <td className="nowrap">
                    {network.uses > 0 ? (
                      <Link
                        to={`/addresses?filter=${encodeURIComponent(`network.label:eq:${network.label}`)}`}
                      >
                        {plural(network.uses, "address", "addresses")}
                      </Link>
                    ) : (
                      plural(network.uses, "address", "addresses")
                    )}
                  </td>
                  {mayEdit && (
                    <td className="row-actions">
                      <button
                        type="button"
                        onClick={() => {
                          setDone("");
                          setEditing(network.hid);
                        }}
                        aria-label={`Rename or change the network ${network.label}`}
                      >
                        Rename
                      </button>
                      <ConfirmButton
                        label="Remove"
                        title={`Remove the network ${network.label}?`}
                        confirmLabel="Remove network"
                        onConfirm={() => remove(network)}
                        disabled={action.busy || network.uses > 0}
                      >
                        <p>No address is under it, and it will be gone for good.</p>
                      </ConfirmButton>
                    </td>
                  )}
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={mayEdit ? 4 : 3} className="muted">
                    There are no networks. An address with no network is in the unlabelled address
                    space.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {mayEdit && open && (
        <section className="panel" aria-labelledby="edit-network">
          <h2 id="edit-network">The network {open.label}</h2>
          <EditForm<Network, Schemas["NetworkPatch"]>
            key={`${open.hid} ${open.row_version}`}
            specs={SPECS}
            record={open}
            save={(body) =>
              api.request("patch", "/api/v1/networks/{hid}", { path: { hid: open.hid }, body })
            }
            onSaved={() => {
              setEditing("");
              changed(`The network ${open.label} was saved.`);
            }}
            onReload={() => setTurn((count) => count + 1)}
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
