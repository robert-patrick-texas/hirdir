import { api } from "../api";
import { queryParams } from "../lib/gridQuery";
import { operatorOptionLabel, operatorSearch } from "../lib/operators";
import { PICK_LIMIT } from "../lib/pick";
import { type Found, PickField, type PickFieldProps } from "./PickField";

/** The first few operators that match what was typed, each by its label and its person. */
async function findOperators(typed: string, signal: AbortSignal): Promise<Found | null> {
  const filter = operatorSearch(typed);
  if (filter === null) return null;
  const page = await api.request("get", "/api/v1/operators", {
    query: queryParams({
      filter,
      sort: ["label"],
      limit: PICK_LIMIT,
      offset: 0,
      // A released label is refused as a new operator, so it is not offered.
      include_archived: false,
      include_drafts: true,
    }),
    signal,
  });
  return {
    options: page.items.map((operator) => ({
      value: operator.hid,
      label: operatorOptionLabel(operator),
      draft: operator.record_status === "draft",
    })),
    total: page.total,
  };
}

/**
 * A field of a form that holds an operator, chosen by searching for it: by its label, or
 * by the name of the person behind it. What the form holds is the label's HID, never the
 * person. Released labels are not offered.
 */
export function OperatorField(props: PickFieldProps) {
  return (
    <PickField
      {...props}
      noun={["operator", "operators"]}
      how="To choose one, type a part of its label, or of the name of the person behind it. A label is made under Operators."
      find={findOperators}
    />
  );
}
