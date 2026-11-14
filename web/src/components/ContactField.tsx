import { api } from "../api";
import { queryParams } from "../lib/gridQuery";
import { contactLabel, contactSearch } from "../lib/operators";
import { PICK_LIMIT } from "../lib/pick";
import { type Found, PickField, type PickFieldProps } from "./PickField";

/** The first few contacts that match what was typed, each by its name and address. */
async function findContacts(typed: string, signal: AbortSignal): Promise<Found | null> {
  const filter = contactSearch(typed);
  if (filter === null) return null;
  const page = await api.request("get", "/api/v1/contacts", {
    query: queryParams({
      filter,
      sort: ["name"],
      limit: PICK_LIMIT,
      offset: 0,
      // A retired contact is refused as a new operator, so it is not offered.
      include_archived: false,
      include_drafts: true,
    }),
    signal,
  });
  return {
    options: page.items.map((contact) => ({
      value: contact.hid,
      label: contactLabel(contact),
      draft: contact.record_status === "draft",
    })),
    total: page.total,
  };
}

/**
 * A field of a form that holds a contact, such as the operator of an item, chosen by
 * searching for it by name or by email address. The list of contacts may be long, so it
 * is never offered whole. Retired contacts are not offered.
 */
export function ContactField(props: PickFieldProps) {
  return (
    <PickField
      {...props}
      noun={["contact", "contacts"]}
      how="To choose one, type a part of the name or of the email address."
      find={findContacts}
    />
  );
}
