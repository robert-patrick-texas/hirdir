// The health of a row of the scoreboard in one cell (P-178): one bar split into four parts,
// good, degraded, failed and unknown, each as long as its share of the row's components and
// drawn in the colour of its health mark; beside it the four numbers, each with its mark.
// A screen reader hears the four once, in words; the bar and the marks are for the eye.

import type { CSSProperties } from "react";
import { HEALTHS } from "../lib/health";
import { type HealthCounts, healthParts, healthWords } from "../lib/scoreboard";
import { countText } from "../lib/summary";

export function HealthSplit({ counts }: { counts: HealthCounts }) {
  const parts = healthParts(counts);
  return (
    <span className="health-split" data-testid="health-split">
      <span className="health-bar" aria-hidden="true">
        {parts.map((part) => {
          const size: CSSProperties = { inlineSize: `${(part.share * 100).toFixed(2)}%` };
          return (
            <span
              key={part.health}
              className={`health-part health-part-${part.health}`}
              data-health={part.health}
              style={size}
            />
          );
        })}
      </span>
      <span className="health-figures" aria-hidden="true">
        {HEALTHS.map((health) => (
          <span
            key={health.value}
            className={`health health-${health.value} health-figure`}
            data-health={health.value}
            title={health.label}
          >
            <span className="health-dot" />
            {countText(counts[health.value])}
          </span>
        ))}
      </span>
      <span className="visually-hidden">{healthWords(counts)}</span>
    </span>
  );
}
