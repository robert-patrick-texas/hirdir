// Why a record has each value it has from elsewhere, under Values in force on the page of
// an item and of a group (P-176): for each value, a heading with the value in force, the
// row of boxes of its walk, what a value of its own overrides, and the same as a table.

import { Link } from "react-router";
import {
  fieldLabel,
  overridden,
  type Resolution,
  stepPath,
  stepTitle,
  valueText,
  walkBoxes,
} from "../lib/resolution";
import { Walk } from "./BoxWalk";

/** The walks of an answer, one under a heading of its own for each value. */
export function ResolutionWalks({
  resolution,
  level = 3,
}: {
  resolution: Resolution;
  /** The level of the heading of each value: beneath that of the section. */
  level?: 3 | 4;
}) {
  const Heading = level === 3 ? "h3" : "h4";
  return (
    <div className="walks" data-testid="walks">
      {resolution.fields.map((field) => {
        const label = fieldLabel(field.field);
        const over = overridden(field);
        const fromPath = over?.from ? stepPath(over.from) : null;
        return (
          <div
            key={field.field}
            className="walk-field"
            data-testid="walk-field"
            data-field={field.field}
            data-source={field.source}
          >
            <Heading className="walk-heading">
              {label}:{" "}
              <span className="walk-in-force">
                {valueText(field.value, field.label) ?? <span className="muted">none</span>}
              </span>
            </Heading>
            <Walk
              label={label}
              steps={walkBoxes(field)}
              overrides={
                over ? (
                  <>
                    {over.text}
                    {over.from && (
                      <>
                        , from{" "}
                        {fromPath ? (
                          <Link to={fromPath}>{stepTitle(over.from)}</Link>
                        ) : (
                          stepTitle(over.from)
                        )}
                      </>
                    )}
                  </>
                ) : undefined
              }
            />
          </div>
        );
      })}
    </div>
  );
}
