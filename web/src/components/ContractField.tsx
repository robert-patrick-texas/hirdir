import { api } from "../api";
import { contractLabel } from "../lib/contracts";
import { any } from "../lib/filter";
import { queryParams } from "../lib/gridQuery";
import { PICK_LIMIT } from "../lib/pick";
import { type Found, PickField, type PickFieldProps } from "./PickField";

/** The first few contracts that match what was typed, by number, vendor or agreement. */
async function findContracts(typed: string, signal: AbortSignal): Promise<Found | null> {
  const value = typed.trim().slice(0, 200);
  if (value === "") return null;
  const page = await api.request("get", "/api/v1/contracts", {
    query: queryParams({
      filter: any(
        { field: "number", op: "contains", value },
        { field: "vendor", op: "contains", value },
        { field: "agreement.name", op: "contains", value },
      ),
      sort: ["number"],
      limit: PICK_LIMIT,
      offset: 0,
      // A retired contract is given no further coverage, so it is not offered.
      include_archived: false,
      include_drafts: true,
    }),
    signal,
  });
  return {
    options: page.items.map((contract) => ({
      value: contract.hid,
      label: contract.agreement
        ? `${contractLabel(contract)} · ${contract.agreement.name}`
        : contractLabel(contract),
      draft: contract.record_status === "draft",
    })),
    total: page.total,
  };
}

/**
 * A field that holds a contract, chosen by searching for it by its number, its vendor or
 * the agreement it is in. Retired contracts are not offered.
 */
export function ContractField(props: PickFieldProps) {
  return (
    <PickField
      {...props}
      noun={["contract", "contracts"]}
      how="To choose one, type a part of its number, of its vendor or of its agreement."
      find={findContracts}
    />
  );
}
