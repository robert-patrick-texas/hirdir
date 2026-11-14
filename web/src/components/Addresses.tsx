import { type FormEvent, useMemo, useState } from "react";
import { Link } from "react-router";
import { api, type Schemas } from "../api";
import {
  ADDRESS_ROLES,
  type Address,
  addressRoleLabel,
  addressText,
  mayBePrimary,
  networkText,
  newAddress,
} from "../lib/addresses";
import { useAction, useLoad } from "../lib/hooks";
import { EVERY, useNetworkOptions } from "../lib/lists";
import type { FieldSpec } from "../lib/patch";
import { fieldErrors } from "../lib/problems";
import { ConfirmButton } from "./ConfirmButton";
import { CheckField, SelectField, TextField } from "./Field";
import { Notice, Problem } from "./Problem";
import { EditForm } from "./RecordForm";

/** The item or the device group whose addresses these are. */
export type AddressHolder = { item_hid: string } | { group_hid: string };

interface AddressesProps {
  holder: AddressHolder;
  /** What to call the holder in a sentence: "this item", "this group". */
  whose: string;
  mayEdit: boolean;
}

function holderFilter(holder: AddressHolder): string {
  const [field, value] =
    "item_hid" in holder ? ["item_hid", holder.item_hid] : ["group_hid", holder.group_hid];
  return JSON.stringify({ field, op: "eq", value });
}

/**
 * The addresses of one item or one device group: each with its network and its role,
 * the primary management address first. Inventory may add one, change one, remove one
 * and mark one as primary. An address is removed outright; the audit trail keeps what
 * it was.
 */
export function Addresses({ holder, whose, mayEdit }: AddressesProps) {
  const [turn, setTurn] = useState(0);
  const [done, setDone] = useState("");
  const [editing, setEditing] = useState("");
  const [adding, setAdding] = useState(false);
  const action = useAction();
  const filter = holderFilter(holder);
  const addresses = useLoad(`addresses ${filter} ${turn}`, (signal) =>
    api.request("get", "/api/v1/addresses", {
      query: { filter, sort: ["-is_primary", "address"], limit: EVERY },
      signal,
    }),
  );
  const networks = useNetworkOptions();
  const rows = addresses.data?.items ?? [];
  const open = rows.find((address) => address.hid === editing) ?? null;

  function changed(text: string) {
    setDone(text);
    setEditing("");
    setTurn((count) => count + 1);
  }

  async function makePrimary(address: Address) {
    setDone("");
    const result = await action.run(() =>
      api.request("patch", "/api/v1/addresses/{hid}", {
        path: { hid: address.hid },
        body: { row_version: address.row_version, is_primary: true },
      }),
    );
    if (result.ok) changed(`${address.address} is now the primary management address.`);
  }

  async function remove(address: Address) {
    setDone("");
    const result = await action.run(() =>
      api.request("delete", "/api/v1/addresses/{hid}", { path: { hid: address.hid } }),
    );
    if (result.ok) changed(`The address ${address.address} was removed.`);
  }

  return (
    <section aria-labelledby="addresses">
      <h2 id="addresses">Addresses</h2>
      <Problem error={addresses.error} />
      <Problem error={action.error} onReload={() => setTurn((count) => count + 1)} />
      <Notice text={done} />
      {addresses.loading && !addresses.data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {addresses.data && rows.length === 0 && (
        <p className="muted">There is no address on {whose}.</p>
      )}
      {rows.length > 0 && (
        <div className="scroll">
          <table className="narrow" data-testid="addresses">
            <caption className="visually-hidden">
              The addresses of {whose}, the primary management address first
            </caption>
            <thead>
              <tr>
                <th scope="col">Address</th>
                <th scope="col">Network</th>
                <th scope="col">Role</th>
                <th scope="col">Primary</th>
                {mayEdit && (
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((address) => {
                const named = addressText({
                  address: address.address,
                  network: address.network?.label ?? null,
                });
                return (
                  <tr key={address.hid} data-address={address.address}>
                    <th scope="row" className="mono">
                      {address.address}
                    </th>
                    <td className={address.network ? undefined : "muted"}>
                      {networkText(address.network?.label)}
                    </td>
                    <td>{addressRoleLabel(address.role)}</td>
                    <td>{address.is_primary ? "Primary" : ""}</td>
                    {mayEdit && (
                      <td className="row-actions">
                        {mayBePrimary(address.role) && !address.is_primary && (
                          <button
                            type="button"
                            disabled={action.busy}
                            onClick={() => makePrimary(address)}
                            aria-label={`Make ${named} the primary management address`}
                          >
                            Make primary
                          </button>
                        )}
                        <button
                          type="button"
                          disabled={action.busy}
                          onClick={() => {
                            setDone("");
                            setAdding(false);
                            setEditing(address.hid);
                          }}
                          aria-label={`Change the address ${named}`}
                        >
                          Change
                        </button>
                        <ConfirmButton
                          label="Remove"
                          title={`Remove the address ${named}?`}
                          confirmLabel="Remove address"
                          onConfirm={() => remove(address)}
                          disabled={action.busy}
                        >
                          <p>
                            The address is taken off {whose} for good. The audit trail keeps what it
                            was.
                          </p>
                        </ConfirmButton>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {mayEdit && open && (
        <EditAddress
          key={`${open.hid} ${open.row_version}`}
          address={open}
          networks={networks.data ?? []}
          onSaved={() => changed(`The address ${open.address} was saved.`)}
          onReload={() => setTurn((count) => count + 1)}
          onClose={() => setEditing("")}
        />
      )}
      {mayEdit && !adding && (
        <p className="actions">
          <button
            type="button"
            onClick={() => {
              setDone("");
              setEditing("");
              setAdding(true);
            }}
          >
            Add an address
          </button>
        </p>
      )}
      {mayEdit && adding && (
        <NewAddress
          holder={holder}
          networks={networks.data ?? []}
          first={rows.length === 0}
          onCancel={() => setAdding(false)}
          onCreated={(address) => {
            setAdding(false);
            changed(`The address ${address.address} was added.`);
          }}
        />
      )}
      {mayEdit && <Problem error={networks.error} />}
    </section>
  );
}

interface Named {
  value: string;
  label: string;
}

interface EditAddressProps {
  address: Address;
  networks: readonly Named[];
  onSaved: () => void;
  onReload: () => void;
  onClose: () => void;
}

function EditAddress({ address, networks, onSaved, onReload, onClose }: EditAddressProps) {
  const specs = useMemo<FieldSpec[]>(
    () => [
      {
        name: "address",
        label: "Address",
        kind: "text",
        required: true,
        maxLength: 45,
        hint: "IPv4 or IPv6, with no prefix length",
      },
      {
        name: "network_hid",
        label: "Network",
        kind: "choice",
        blank: "No network",
        options: networks,
      },
      { name: "role", label: "Role", kind: "choice", options: ADDRESS_ROLES },
      {
        name: "is_primary",
        label: "The primary management address",
        kind: "boolean",
        hint: "Only a management address may be. The mark is taken off the one that had it.",
      },
    ],
    [networks],
  );
  return (
    <section className="panel" aria-labelledby="edit-address">
      <h3 id="edit-address">The address {address.address}</h3>
      <EditForm<Address, Schemas["AddressPatch"]>
        specs={specs}
        record={address}
        save={(body) =>
          api.request("patch", "/api/v1/addresses/{hid}", { path: { hid: address.hid }, body })
        }
        onSaved={onSaved}
        onReload={onReload}
        submitLabel="Save address"
      />
      <p className="actions">
        <button type="button" onClick={onClose}>
          Close
        </button>
      </p>
    </section>
  );
}

interface NewAddressProps {
  holder: AddressHolder;
  networks: readonly Named[];
  /** The record has no address yet: a first management address is offered as primary. */
  first: boolean;
  onCancel: () => void;
  onCreated: (address: Address) => void;
}

function NewAddress({ holder, networks, first, onCancel, onCreated }: NewAddressProps) {
  const [address, setAddress] = useState("");
  const [network, setNetwork] = useState("");
  const [role, setRole] = useState("management");
  const [primary, setPrimary] = useState(first);
  const action = useAction();
  const known = ["address", "network_hid", "role", "is_primary"];
  const refused = fieldErrors(action.error, known).shown;

  async function submit(event: FormEvent) {
    event.preventDefault();
    const body = newAddress(holder, {
      address,
      network_hid: network,
      role,
      is_primary: primary,
    });
    const result = await action.run(() => api.request("post", "/api/v1/addresses", { body }));
    if (result.ok) onCreated(result.value);
  }

  return (
    <section className="panel" aria-labelledby="new-address">
      <h3 id="new-address">New address</h3>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={known} />
        <div className="fields">
          <TextField
            label="Address"
            name="address"
            value={address}
            onChange={setAddress}
            required
            maxLength={45}
            autoComplete="off"
            error={refused.address}
            hint="IPv4 or IPv6, with no prefix length"
          />
          <SelectField
            label="Network"
            name="network_hid"
            value={network}
            onChange={setNetwork}
            error={refused.network_hid}
            hint="A VRF, a tenant, a colour. The same address under two networks is two addresses."
          >
            <option value="">No network</option>
            {networks.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="Role"
            name="role"
            value={role}
            onChange={setRole}
            error={refused.role}
          >
            {ADDRESS_ROLES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </SelectField>
        </div>
        <CheckField
          label="The primary management address"
          name="is_primary"
          checked={primary && mayBePrimary(role)}
          disabled={!mayBePrimary(role)}
          onChange={setPrimary}
          error={refused.is_primary}
          hint="Only a management address may be. The mark is taken off the one that had it."
        />
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || address.trim() === ""}>
            Add address
          </button>
          <button type="button" onClick={onCancel} disabled={action.busy}>
            Cancel
          </button>
        </p>
        <p className="hint">
          A network is made under <Link to="/networks">Networks</Link> before it is used here.
        </p>
      </form>
    </section>
  );
}
