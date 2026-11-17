// The walk of a value, drawn as a row of boxes joined by arrows (P-176): one box for each
// record the walk looks at, in its order, the one that decides drawn in the accent of the
// theme, one passed over muted with its value struck through, one that holds nothing
// dashed, and each record a link. The same steps as a table follow it, for a screen
// reader and to copy. Nothing is worked out here: the server says what each step is.
//
// The boxes are an ordered list, so that a screen reader reads them in their order and the
// keyboard reaches each link; the arrows are for the eye alone. Each box says what it is
// in words as well as in its drawing, so that colour and a dashed line are never all there
// is. In a narrow window the row scrolls by itself, and the page does not.

import type { ReactNode } from "react";
import { Link } from "react-router";

/** What a step of a walk is: the server's word for it. */
export type StepState = "decides" | "passed_over" | "nothing" | "retired";

/** One step of a walk: the record it looks at, what that holds, and what the step is. */
export interface WalkBox {
  /** Unique within the walk. */
  key: string;
  /** What kind of record it is, small above its name: `Its own`, `Group · stack · 1st`. */
  kind: string;
  /** The record, as people call it. */
  title: string;
  /** The page of the record, where it has one. */
  href?: string | null;
  /** What the record holds, as people read it; null where it holds nothing. */
  value: string | null;
  /** Where the value is from when the record holds none of its own: the group it is nested in. */
  via?: { text: string; href?: string | null } | null;
  state: StepState;
}

/** What a step is, in words, as the box and the table say it. */
export const STATE_WORDS: Readonly<Record<StepState, string>> = {
  decides: "decides",
  passed_over: "passed over",
  nothing: "holds nothing",
  retired: "retired, passed over",
};

function RecordLink({ text, href }: { text: string; href?: string | null | undefined }) {
  return href ? <Link to={href}>{text}</Link> : text;
}

/** What a step holds, struck through when it is passed over. */
function Held({ value, state }: { value: string; state: StepState }) {
  const passed = state === "passed_over" || state === "retired";
  return passed ? <s>{value}</s> : value;
}

/** Where a value held by a group is from, when that group holds none of its own. */
function Via({ step }: { step: WalkBox }) {
  if (!step.via) return null;
  return (
    <>
      {" "}
      <span className="walk-via">
        from <RecordLink text={step.via.text} href={step.via.href} />
      </span>
    </>
  );
}

/** The arrow from one box to the next, for the eye. */
function Arrow() {
  return (
    <span className="walk-arrow" aria-hidden="true">
      <svg viewBox="0 0 24 12" width="24" height="12" focusable="false" aria-hidden="true">
        <line x1="0" y1="6" x2="20" y2="6" />
        <polyline points="15,1 21,6 15,11" />
      </svg>
    </span>
  );
}

interface BoxWalkProps {
  /** What the walk is of, as the page calls it: `Location`. */
  label: string;
  steps: readonly WalkBox[];
  /** What a value of the record's own replaces: the value it would have without it. */
  overrides?: ReactNode;
  testId?: string;
}

/** The row of boxes, joined by arrows in the order of the walk. */
export function BoxWalk({ label, steps, overrides, testId }: BoxWalkProps) {
  return (
    <div className="walk" data-testid={testId}>
      <div className="walk-scroll">
        <ol className="walk-row" aria-label={`The walk of ${label}, in its order`}>
          {steps.map((step, place) => (
            <li
              key={step.key}
              className="walk-step"
              data-state={step.state}
              data-step={place + 1}
              data-testid="walk-step"
            >
              {place > 0 && <Arrow />}
              <div className={`walk-box walk-${step.state}`}>
                <span className="walk-kind">{step.kind}</span>
                <span className="walk-title">
                  <RecordLink text={step.title} href={step.href} />
                </span>
                {/* A step that holds nothing says so once, in its state. */}
                {step.value !== null && (
                  <span className="walk-value" data-testid="walk-value">
                    <Held value={step.value} state={step.state} />
                    <Via step={step} />
                  </span>
                )}
                <span className="walk-state">{STATE_WORDS[step.state]}</span>
              </div>
            </li>
          ))}
        </ol>
      </div>
      {overrides !== undefined && overrides !== null && (
        <p className="walk-overrides" data-testid="walk-overrides">
          <span className="walk-overrides-word">Overrides</span> {overrides}
        </p>
      )}
    </div>
  );
}

/** The same steps as a table: a row for each, in the order of the walk. */
export function WalkTable({ label, steps, testId }: Omit<BoxWalkProps, "overrides">) {
  return (
    <div className="scroll">
      <table className="narrow walk-table" data-testid={testId}>
        <caption className="visually-hidden">The walk of {label}, as a table</caption>
        <thead>
          <tr>
            <th scope="col" className="number">
              Step
            </th>
            <th scope="col">Looks at</th>
            <th scope="col">Holds</th>
            <th scope="col">Outcome</th>
          </tr>
        </thead>
        <tbody>
          {steps.map((step, place) => (
            <tr key={step.key} data-state={step.state} data-step={place + 1}>
              <td className="number">{place + 1}</td>
              <th scope="row">
                <span className="muted">{step.kind}</span>{" "}
                <RecordLink text={step.title} href={step.href} />
              </th>
              <td>
                {step.value ?? <span className="muted">nothing</span>}
                <Via step={step} />
              </td>
              <td className={step.state === "decides" ? "walk-decides-word" : "muted"}>
                {STATE_WORDS[step.state]}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface WalkProps extends BoxWalkProps {
  /** Show the table beneath the boxes at first. Left out, it is folded, and opens on asking. */
  tableOpen?: boolean;
}

/**
 * A walk as boxes, with the same as a table beneath them, folded until it is asked for
 * unless the page says otherwise, so that a page of several walks stays short.
 */
export function Walk({ label, steps, overrides, testId, tableOpen = false }: WalkProps) {
  return (
    <div className="walk-whole" data-testid={testId}>
      <BoxWalk label={label} steps={steps} overrides={overrides} />
      <details className="walk-as-table" open={tableOpen}>
        <summary>
          As a table<span className="visually-hidden">: the walk of {label}</span>
        </summary>
        <WalkTable label={label} steps={steps} />
      </details>
    </div>
  );
}
