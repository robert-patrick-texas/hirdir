// The mark of an operator, used wherever one is shown: the label, with a dot in its
// colour beside it, as a link to the page of that operator. The person behind the label
// is said on hover, and beside it where there is room; a label nobody is behind says
// "open". The colour is never all there is: the label is always written out.

import { Link } from "react-router";
import {
  type Mark,
  markOf,
  markTitle,
  type OperatorInForce,
  operatorPath,
  operatorSource,
} from "../lib/operators";

interface OperatorMarkProps {
  mark: Mark;
  /** Say the person's name beside the label. Left out, it is on hover only. */
  withPerson?: boolean;
  testId?: string;
}

export function OperatorMark({ mark, withPerson = false, testId }: OperatorMarkProps) {
  return (
    <span
      className="operator-mark"
      data-testid={testId}
      data-operator={mark.hid}
      data-open={mark.open ? "true" : "false"}
    >
      <Link to={operatorPath(mark.hid)} title={markTitle(mark) || undefined}>
        <span
          className="swatch operator-dot"
          aria-hidden="true"
          {...(mark.colour ? { style: { backgroundColor: mark.colour } } : {})}
        />
        {mark.label}
      </Link>
      {mark.released ? (
        <span className="badge mark">released</span>
      ) : mark.open ? (
        <span className="badge badge-plain mark">open</span>
      ) : (
        withPerson && mark.person && <span className="muted operator-person">{mark.person}</span>
      )}
    </span>
  );
}

interface OperatorProps {
  /** The operator in force, as the server resolved it. */
  effective: OperatorInForce;
  testId?: string;
}

/**
 * The operator in force of an item or of a device group, with where it came from: the
 * record's own, or inherited from the item, the group or the place that is named and
 * linked, shown lighter and marked in words. Nobody is said plainly.
 */
export function Operator({ effective, testId }: OperatorProps) {
  const mark = markOf(effective);
  if (!mark) {
    return (
      <span className="muted" data-testid={testId} data-source="none">
        Nobody is assigned
      </span>
    );
  }
  const from = operatorSource(effective);
  return (
    <span data-testid={testId} data-source={effective.source}>
      <OperatorMark mark={mark} withPerson />
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

interface OperatorNoteProps {
  effective: OperatorInForce;
  /** What the form is of: "item", "group". */
  what: string;
}

/**
 * What a form says above the operator of a record that has none of its own, so that it
 * is seen what applies before one is chosen: the operator it has from above, with the
 * record that one comes from, or that nobody is assigned.
 */
export function OperatorNote({ effective, what }: OperatorNoteProps) {
  const mark = markOf(effective);
  if (!mark) {
    return (
      <p className="form-note" data-testid="operator-note" data-source="none">
        Nobody is assigned: this {what} has no operator of its own, and none from above.
      </p>
    );
  }
  const from = operatorSource(effective);
  return (
    <p className="form-note inherited" data-testid="operator-note" data-source={effective.source}>
      <span className="badge badge-plain mark">Inherited</span>{" "}
      <OperatorMark mark={mark} withPerson />. Inherited from{" "}
      {from ? <Link to={from.path}>{from.text}</Link> : "above"}. Choose an operator here to give
      this {what} one of its own.
    </p>
  );
}
