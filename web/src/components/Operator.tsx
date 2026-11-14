import { Link } from "react-router";
import type { OperatorInForce, OperatorSource } from "../lib/operators";

interface OperatorProps {
  /** The operator in force, as the server resolved it. */
  effective: OperatorInForce;
  /** The record it came from, when it is not the record's own. */
  from: OperatorSource | null;
  testId?: string;
}

/**
 * The operator in force of an item or of a device group, with where it came from: the
 * record's own, or inherited from the item or the group that is named and linked, shown
 * lighter and marked in words. Nobody is said plainly.
 */
export function Operator({ effective, from, testId }: OperatorProps) {
  if (typeof effective.value !== "string") {
    return (
      <span className="muted" data-testid={testId} data-source="none">
        Nobody is assigned
      </span>
    );
  }
  return (
    <span data-testid={testId} data-source={effective.source}>
      <Link to={`/contacts/${encodeURIComponent(effective.value)}`}>
        {effective.label || effective.value}
      </Link>
      {effective.source === "own" ? (
        <span className="muted"> · Set here</span>
      ) : (
        <span className="inherited">
          {" "}
          · <span className="badge badge-plain mark">Inherited</span> from{" "}
          {from ? <Link to={from.path}>{from.text}</Link> : "above"}
        </span>
      )}
    </span>
  );
}

interface OperatorNoteProps extends OperatorProps {
  /** What the form is of: "item", "group". */
  what: string;
}

/**
 * What a form says above the operator of a record that has none of its own, so that it
 * is seen what applies before anybody is chosen: the operator it has from above, with
 * the record that one comes from, or that nobody is assigned.
 */
export function OperatorNote({ effective, from, what }: OperatorNoteProps) {
  if (typeof effective.value !== "string") {
    return (
      <p className="form-note" data-testid="operator-note" data-source="none">
        Nobody is assigned: this {what} has no operator of its own, and none from above.
      </p>
    );
  }
  return (
    <p className="form-note inherited" data-testid="operator-note" data-source={effective.source}>
      <span className="badge badge-plain mark">Inherited</span> {effective.label}. Inherited from{" "}
      {from ? <Link to={from.path}>{from.text}</Link> : "above"}. Choose a contact here to give this{" "}
      {what} an operator of its own.
    </p>
  );
}
