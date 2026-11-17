import { api } from "../api";
import { queryParams } from "../lib/gridQuery";
import { contactFinder, personLabel } from "../lib/people";
import { PICK_LIMIT } from "../lib/pick";
import { type Found, PickField, type PickFieldProps } from "./PickField";

/**
 * The first few contacts that match what was typed, each by its name and address and
 * the user it is, where it is one. 0.9.3: those that are users, those that are not, or
 * either (P-172).
 */
async function findContacts(
  typed: string,
  users: boolean | undefined,
  signal: AbortSignal,
): Promise<Found | null> {
  const filter = contactFinder(typed, users);
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
      label: personLabel(contact),
      draft: contact.record_status === "draft",
    })),
    total: page.total,
  };
}

interface ContactFieldProps extends PickFieldProps {
  /**
   * 0.9.3: offer only the contacts that are users, with true, or only those that are not,
   * with false. Left out, any contact.
   */
  users?: boolean;
}

/**
 * A field of a form that holds a contact, such as the operator of an item, chosen by
 * searching for it by name or by email address. The list of contacts may be long, so it
 * is never offered whole. Retired contacts are not offered.
 */
export function ContactField({ users, ...props }: ContactFieldProps) {
  return (
    <PickField
      {...props}
      noun={
        users === true
          ? ["user", "users"]
          : users === false
            ? ["other contact", "other contacts"]
            : ["contact", "contacts"]
      }
      how="To choose one, type a part of the name or of the email address."
      find={(typed, signal) => findContacts(typed, users, signal)}
    />
  );
}
