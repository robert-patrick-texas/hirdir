import { useMemo } from "react";
import { api, type Schemas } from "../api";
import { useEntryOptions, useOwnerOptions, useTags } from "../lib/lists";
import type { FieldSpec } from "../lib/patch";
import { Problem } from "./Problem";
import { CreateForm } from "./RecordForm";

type Item = Schemas["ItemOut"];

interface NewItemProps {
  states: readonly string[];
  /** The item the new one is in. Given, the new item is a minor item of it. */
  within?: { hid: string; name: string };
  onCancel: () => void;
  onCreated: (item: Item) => void;
}

/**
 * The form for a new item. Within another item it makes a minor item: one with a
 * position there, which has the owner and the standing of the item it is in until it is
 * given its own.
 */
export function NewItem({ states, within, onCancel, onCreated }: NewItemProps) {
  const entries = useEntryOptions();
  const owners = useOwnerOptions();
  const tags = useTags();
  const minor = within !== undefined;
  const specs = useMemo<FieldSpec[]>(() => {
    return [
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
      {
        name: "name",
        label: "Name",
        kind: "text",
        maxLength: 200,
        hint: "Left blank, the hostname is shown",
      },
      { name: "hostname", label: "Hostname", kind: "text", maxLength: 255 },
      ...(minor
        ? [
            {
              name: "position",
              label: "Position",
              kind: "text",
              maxLength: 100,
              hint: "Where in the item it is: PS-A, Slot 3, Bay 7",
            } satisfies FieldSpec,
          ]
        : []),
      {
        name: "mac_address",
        label: "MAC address",
        kind: "text",
        maxLength: 40,
        hint: "In any common notation",
      },
      {
        name: "owner_hid",
        label: "Owner",
        kind: "choice",
        blank: minor ? "The owner of the item it is in" : "No owner",
        options: owners.data ?? [],
      },
      {
        name: "operator_hid",
        label: "Operator",
        kind: "operator",
        blank: "None of its own: the one it has from above, if any",
        hint: "The label of who of the team looks after it. Left blank, it has the operator of the item it is in, of a group it joins, or of where it is.",
      },
      {
        name: "location_hid",
        label: "Location",
        kind: "location",
        blank: minor ? "Where the item it is in is" : "No location",
        hint: "Left empty, the item is where the item it is in is, or a group it joins.",
      },
      {
        name: "planned_location_hid",
        label: "Planned location",
        kind: "planned_location",
        blank: "No plan",
        hint: "Where it is going, when that place is not in use yet. It stays where it is until the place is made active, and is then moved there by that change. Left empty, it has the plan of the item it is in, or of a group it joins.",
      },
      {
        name: "lifecycle_state",
        label: "Lifecycle state",
        kind: "choice",
        blank: minor ? "The standing of the item it is in" : "No state yet",
        options: states.map((state) => ({ value: state, label: state })),
        hint: "The disposition and intent are set as the state has them on entry",
      },
      {
        name: "tags",
        label: "Tags",
        kind: "set",
        options: (tags.data ?? []).map((tag) => ({ value: tag.label, label: tag.label })),
      },
    ];
  }, [entries.data, owners.data, tags.data, states, minor]);

  return (
    <CreateForm<Schemas["ItemCreate"], Item>
      title={minor ? "New minor item" : "New item"}
      specs={specs}
      create={(body) =>
        api.request("post", "/api/v1/items", {
          body: within ? { ...body, parent_item_hid: within.hid } : body,
        })
      }
      onCreated={onCreated}
      onCancel={onCancel}
      submitLabel={minor ? "Create minor item" : "Create item"}
    >
      <Problem error={entries.error ?? owners.error ?? tags.error} />
      {within ? (
        <p className="hint">
          A minor item of {within.name}: a power supply, a module, a transceiver. Left blank, its
          owner, its location and its lifecycle state are those of the item it is in, and follow it.
          It needs something to know it by: a serial number with a catalog entry, an asset tag, a
          name or a hostname.
        </p>
      ) : (
        <p className="hint">
          An item needs something to know it by: a serial number with a catalog entry, an asset tag,
          a name or a hostname. Everything else may be left blank and filled in later.
        </p>
      )}
    </CreateForm>
  );
}
