// 0.9.14: the chain of one person, on the page of a user, of a contact and of an
// operator (P-291, P-297): operator, contact, user, each a link to its page, a retired
// one marked, read from `GET .../linked`. The three records travel together when one is
// retired, so each page shows what the record it is of is linked to.

import type { ReactNode } from "react";
import { Link } from "react-router";
import { useAuth } from "../auth";
import { useLoad } from "../lib/hooks";
import { type PersonKind, userState } from "../lib/linked";
import { briefMark } from "../lib/onboarding";
import { readLinked } from "../lib/person";
import { allows } from "../lib/roles";
import { OperatorMark } from "./Operator";
import { Problem } from "./Problem";

interface PersonChainProps {
  /** Which of the three the page is of, and its HID. */
  kind: PersonKind;
  hid: string;
  /** The chain is read again when this is another value: the version of the record. */
  turn: string | number;
}

/** One part of the chain, marked where it is the record the page is of. */
function Part({ here, children }: { here: boolean; children: ReactNode }) {
  if (!here) return <>{children}</>;
  return (
    <span className="chain-here" data-here="true">
      {children}
      <span className="visually-hidden"> (this page)</span>
    </span>
  );
}

export function PersonChain({ kind, hid, turn }: PersonChainProps) {
  const auth = useAuth();
  const admin = allows(auth.user.role, "admin");
  const linked = useLoad(`linked ${kind} ${hid} ${turn}`, (signal) =>
    readLinked({ kind, hid }, signal),
  );
  const data = linked.data;
  return (
    <>
      <Problem error={linked.error} />
      {data && (
        <nav className="person-chain" aria-label="The person this belongs to" data-testid="chain">
          <span className="person-chain-label" aria-hidden="true">
            One person
          </span>
          <ol>
            <li className="chain-part" data-part="operator">
              <span className="chain-kind">
                {data.operators.length > 1 ? "Operators" : "Operator"}
              </span>
              {data.operators.length === 0 && <span className="people-gap">no operator</span>}
              {data.operators.length > 0 && (
                <span className="people-marks">
                  {data.operators.map((operator) => (
                    <Part key={operator.hid} here={kind === "operator" && operator.hid === hid}>
                      <OperatorMark mark={briefMark(operator, data.contact)} />
                    </Part>
                  ))}
                </span>
              )}
            </li>
            <li className="chain-part" data-part="contact">
              <span className="chain-kind">Contact</span>
              {data.contact ? (
                <Part here={kind === "contact"}>
                  <Link to={`/contacts/${encodeURIComponent(data.contact.hid)}`}>
                    {data.contact.name}
                  </Link>
                  {data.contact.record_status === "retired" && (
                    <span className="badge">Retired</span>
                  )}
                </Part>
              ) : (
                <span className="people-gap">no contact</span>
              )}
            </li>
            <li className="chain-part" data-part="user">
              <span className="chain-kind">User</span>
              {data.user ? (
                <Part here={kind === "user"}>
                  {/* Every role reads the username; an Admin opens the user's page. */}
                  {admin ? (
                    <Link to={`/admin/users/${encodeURIComponent(data.user.hid)}`}>
                      {data.user.username}
                    </Link>
                  ) : (
                    <span className="mono">{data.user.username}</span>
                  )}
                  {userState(data.user) !== "Active" && (
                    <span className="badge">{userState(data.user)}</span>
                  )}
                </Part>
              ) : (
                <span className="people-gap">no user</span>
              )}
            </li>
          </ol>
        </nav>
      )}
    </>
  );
}
