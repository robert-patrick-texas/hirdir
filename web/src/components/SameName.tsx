// 0.9.17: a name another contact has, said with how a file tells them apart (P-315).

import { Link } from "react-router";
import { namedAddress, sameNameWords, type Whose } from "../lib/sameName";

/**
 * Where other contacts not retired have this name, says so and links to the contacts of
 * that name; says nothing where none has it. The name is saved all the same.
 */
export function SameName({ name, others, whose }: { name: string; others: number; whose: Whose }) {
  const words = sameNameWords(name, others, whose);
  if (words === null) return null;
  return (
    <p className="alert alert-info" data-testid="same-name">
      {words} <Link to={namedAddress(name)}>The contacts named {name}</Link>
    </p>
  );
}
