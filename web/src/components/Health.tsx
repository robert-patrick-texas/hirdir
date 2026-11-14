// Health on a page: a mark in its colour with its word, never the colour alone, and the
// reasons the server gave. And the form that says what is seen of an item or of a group:
// set it, state it again with the present moment, or clear it.

import { useState } from "react";
import type { ApiError } from "../api";
import {
  type Health,
  type HealthCount,
  healthCounts,
  healthLabel,
  healthTone,
  OBSERVED_CHOICES,
  type ObservationPatch,
  observationPatch,
  observedLabel,
  observedWhen,
} from "../lib/health";
import { countText } from "../lib/summary";
import { SelectField } from "./Field";
import { Problem } from "./Problem";
import { Time } from "./Time";

/**
 * A health as a mark in its colour, green, amber, red or grey, with its word beside it:
 * the word is what a screen reader says, and what is read by somebody who does not see
 * the colour.
 */
export function HealthMark({ value, testId }: { value: string; testId?: string }) {
  return (
    <span className={`health health-${healthTone(value)}`} data-health={value} data-testid={testId}>
      <span className="health-dot" aria-hidden="true" />
      {healthLabel(value)}
    </span>
  );
}

/** A health with its reasons written out beneath it, as a record's own page shows it. */
export function HealthWithReasons({ health, testId }: { health: Health; testId?: string }) {
  return (
    <div data-testid={testId} data-health={health.value}>
      <HealthMark value={health.value} />
      {health.reasons.length > 0 && (
        <ul className="plain-list health-reasons">
          {health.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The components of each health, each count beside the mark of its health. */
export function HealthCounts({ counts }: { counts: HealthCount }) {
  return (
    <dl className="totals health-counts" data-testid="totals-by-health">
      {healthCounts(counts).map((health) => (
        <div key={health.value} data-health={health.value}>
          <dt>
            <HealthMark value={health.value} />
          </dt>
          <dd data-testid={`total-health-${health.value}`}>{countText(health.count)}</dd>
        </div>
      ))}
    </dl>
  );
}

/** What is seen, in words: the status, who saw it when that is a person, and the moment. */
export function ObservedText({
  status,
  at,
}: {
  status: string | null | undefined;
  at: string | null | undefined;
}) {
  if (!status) return <span className="muted">Nobody has looked</span>;
  return (
    <>
      {observedLabel(status)}
      {status === "present" && (
        <span className="muted"> · a person saw it, in place and in order</span>
      )}
      <span className="muted"> · {observedWhen(status)} </span>
      <Time at={at} />
    </>
  );
}

interface ObservationProps {
  /** What it is that is seen, in a sentence: "this item", the name of a group. */
  whose: string;
  status: string | null;
  busy: boolean;
  error: ApiError | null;
  /** Send the change. The page reads the record again when it was taken. */
  onChange: (patch: ObservationPatch, done: string) => void;
  onReload: () => void;
}

/**
 * Say what is seen: choose a status and record it, state the one on record again with
 * the present moment, or clear it. `present` is what a person saw of something that is
 * never on the network, and the form says so.
 */
export function Observation({ whose, status, busy, error, onChange, onReload }: ObservationProps) {
  const [chosen, setChosen] = useState(status ?? "");
  const set = observationPatch("set", chosen);
  const again = observationPatch("again", status);

  return (
    <form
      className="stack"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (set) onChange(set, `What is seen of ${whose} was recorded.`);
      }}
    >
      <Problem error={error} shown={["observed_status"]} onReload={onReload} />
      <div className="inline">
        <SelectField
          label="Observed status"
          name="observed_status"
          value={chosen}
          onChange={setChosen}
          disabled={busy}
          hint="Online, Degraded and Unreachable are seen on the network. Present is what a person saw of something that is never on the network, such as a fibre tester, a power unit with no management connection or a spare on a shelf: it is where it should be and in order, and the moment says when it was last checked."
        >
          <option value="">Choose what is seen</option>
          {OBSERVED_CHOICES.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </SelectField>
      </div>
      <p className="actions">
        <button type="submit" className="primary" disabled={busy || !set || chosen === status}>
          Record what is seen
        </button>
        {again && (
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              // Read as the button is pressed: the moment is this one.
              const now = observationPatch("again", status);
              if (now) onChange(now, `${observedLabel(status)} was seen again, now.`);
            }}
          >
            Seen now
          </button>
        )}
        {status && (
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              const clear = observationPatch("clear", status);
              if (clear) onChange(clear, `What was seen of ${whose} was cleared.`);
            }}
          >
            Clear what is seen
          </button>
        )}
      </p>
    </form>
  );
}
