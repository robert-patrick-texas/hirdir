// 0.9.17: a field that holds the account of a person (P-316): the person answerable for
// an agent, on New user, on the agent's page and in a retirement that hands an agent
// over. Only a person's account that is not retired is offered, as the server takes.

import { api } from "../api";
import { userOptionLabel } from "../lib/people";
import { PICK_LIMIT } from "../lib/pick";
import { type Found, PickField, type PickFieldProps } from "./PickField";

/** The first few people that match what was typed, by username or by name. */
async function findPeople(
  typed: string,
  leaveOut: readonly string[],
  signal: AbortSignal,
): Promise<Found | null> {
  const q = typed.trim();
  if (q === "") return null;
  const page = await api.request("get", "/api/v1/users", {
    // The list leaves the retired out; one more is read for each left out here.
    query: { q, kind: "person", limit: PICK_LIMIT + leaveOut.length, offset: 0 },
    signal,
  });
  const users = page.items.filter((user) => !leaveOut.includes(user.hid)).slice(0, PICK_LIMIT);
  return {
    options: users.map((user) => ({
      value: user.hid,
      label: userOptionLabel(user),
      // A sentence calls a person by their name, or by their username where they have none.
      name: user.display_name || user.username,
    })),
    total: page.total - (page.items.length - users.length),
  };
}

interface PersonUserFieldProps extends PickFieldProps {
  /** Accounts not to offer: the person retired, or the one answerable already. */
  leaveOut?: readonly string[];
}

/** The account of a person, chosen by searching for it by username or by name. */
export function PersonUserField({ leaveOut = [], ...props }: PersonUserFieldProps) {
  return (
    <PickField
      {...props}
      noun={["person", "people"]}
      how="To choose one, type a part of the username or of the name. Only a person who is not retired is offered."
      find={(typed, signal) => findPeople(typed, leaveOut, signal)}
    />
  );
}
