// 0.9.13: a colour is chosen from a grid of 64, by a slider of 32, or typed (P-285).
//
// One picker wherever a colour is entered, an operator's and a tag's: the text box, which
// takes any `#rrggbb`; the slider of 32, whose steps move the choice in the grid; and the
// grid of 64, eight hues across and eight shades down, each swatch one press. The three
// are one value. The value is shown on a chip filled with the colour, its text black or
// white, whichever is read better, and beside it the label as the lists will show it.

import { type KeyboardEvent, type PointerEvent, useCallback, useId, useRef, useState } from "react";
import { api, type Schemas } from "../api";
import {
  colourProblem,
  colourWords,
  type Place,
  pasted,
  placeIn,
  restingStep,
  sameColour,
  stepAfterKey,
  stepOf,
  stepWords,
  textOn,
} from "../lib/colour";
import { type Loaded, useLoad } from "../lib/hooks";
import { safeColour } from "../lib/operators";
import { Problem } from "./Problem";

export type Colours = Schemas["ColoursOut"];

/** The one read of `GET /colours` that every picker shares, and when it was begun. */
let shared: { at: number; colours: Promise<Colours> } | null = null;

/**
 * The colours a form offers, read once for every picker on the page: a read begun at
 * `since` or after is shared, and an earlier one is read again. The grid and the slider
 * never change; `next_for_operators` does, as operators are made, so a form that starts
 * from it asks for a read begun after it opened (`useColours(true)`). A read that fails
 * is not kept.
 */
export function readColours(since = 0): Promise<Colours> {
  if (shared === null || shared.at < since) {
    const colours = api.request("get", "/api/v1/colours", {});
    const read = { at: performance.now(), colours };
    shared = read;
    colours.catch(() => {
      if (shared === read) shared = null;
    });
  }
  return shared.colours;
}

/**
 * The colours a form offers (`readColours`). With `fresh`, from a read begun after the
 * component first rendered, so that `next_for_operators` is the colour that is free now.
 */
export function useColours(fresh = false): Loaded<Colours> {
  const [since] = useState(() => (fresh ? performance.now() : 0));
  return useLoad(`colours ${since}`, () => readColours(since));
}

/** The colour the next operator is given, as it is free now, and a way to wait for it. */
export interface NextColour {
  /** `next_for_operators` of a read begun after the form opened; null until it has come. */
  next: string | null;
  /** The same, once it has come: for a Create pressed before it has. Null if it is not read. */
  wait: () => Promise<string | null>;
}

/**
 * The colour a new operator starts with (P-285): `next_for_operators`, from a read of
 * `GET /colours` begun after the form opened, which the pickers on the page share.
 */
export function useNextColour(): NextColour {
  const [since] = useState(() => performance.now());
  const colours = useLoad(`colours ${since}`, () => readColours(since));
  const wait = useCallback(
    () =>
      readColours(since).then(
        (read) => safeColour(read.next_for_operators),
        () => null,
      ),
    [since],
  );
  return { next: safeColour(colours.data?.next_for_operators), wait };
}

/** The words that stand for no colour on a chip, and for one that cannot be shown. */
function noColour(value: string): string {
  return value.trim() === "" ? "No colour" : "Not a colour";
}

interface ColourChipProps {
  value: string;
  testId?: string;
}

/**
 * A colour's value on a chip filled with it, its text black or white, whichever has the
 * greater contrast with it. A value that is not a colour is never put in a style.
 */
export function ColourChip({ value, testId }: ColourChipProps) {
  const colour = safeColour(value.trim());
  if (!colour) {
    return (
      <span className="colour-chip colour-chip-none" data-testid={testId} data-colour="">
        {noColour(value)}
      </span>
    );
  }
  const text = textOn(colour);
  return (
    <span
      className="colour-chip"
      data-testid={testId}
      data-colour={colour.toLowerCase()}
      data-text={text}
      style={{ backgroundColor: colour, color: text }}
    >
      {value.trim()}
    </span>
  );
}

/** A colour as a list or a page shows it: on its chip, or a dash where there is none. */
export function ColourShown({ colour, testId }: { colour: string | null; testId?: string }) {
  if (!safeColour(colour)) return <span className="muted">—</span>;
  return <ColourChip value={colour ?? ""} {...(testId ? { testId } : {})} />;
}

/** What a colour is shown for, as the lists show it: an operator's dot, or a tag's square. */
export type SampleAs = "operator" | "tag";

function Sample({ text, colour, as }: { text: string; colour: string | null; as: SampleAs }) {
  return (
    <span className={as === "operator" ? "colour-sample operator-mark" : "colour-sample"}>
      <span
        className={as === "operator" ? "swatch operator-dot" : "swatch"}
        aria-hidden="true"
        {...(colour ? { style: { backgroundColor: colour } } : {})}
      />
      {as === "tag" && " "}
      {text.trim() || <span className="muted">(the label)</span>}
    </span>
  );
}

export interface ColourPickerProps {
  /** The prefix of the ids of its controls: unique on the page. */
  id: string;
  /** The name of the group, and of its text box. */
  label: string;
  /** "" for no colour, else what is typed or pressed. */
  value: string;
  onChange: (value: string) => void;
  /** The label shown beside the chip, as the lists show it. */
  sample: string;
  /** What the server, or the form, refused: shown at the box. */
  error?: string | undefined;
  /** How the sample is shown: as an operator (the default), or as a tag. */
  sampleAs?: SampleAs;
  hint?: string | undefined;
  /** The name of the text box, as a form's fields are named. */
  name?: string;
  disabled?: boolean | undefined;
}

/**
 * The picker: the text box with the chip and the sample beside it, the slider of 32, and
 * the grid of 64. The slider and the grid come with `GET /colours`; until then, and if
 * that read fails, the text box takes a colour by itself.
 */
export function ColourPicker(props: ColourPickerProps) {
  const { id, label, value, onChange, sample, error, sampleAs = "operator" } = props;
  const { hint, name, disabled } = props;
  const colours = useColours();
  // A value being typed is said to be wrong once it is long enough, or the box is left.
  const [typing, setTyping] = useState(false);
  const own = colourProblem(value);
  const ownShown = own !== null && (!typing || value.trim().length >= 7) ? own : null;
  const said = error || ownShown;
  const ids = { value: `${id}-value`, hint: `${id}-hint`, error: `${id}-error` };
  const describedBy = [hint && ids.hint, said && ids.error].filter(Boolean).join(" ");
  const colour = safeColour(value.trim());

  return (
    <fieldset className="field colour-picker" data-testid={id}>
      <legend>{label}</legend>
      <div className="colour-typed">
        <label htmlFor={ids.value} className="visually-hidden">
          {label}
        </label>
        <input
          id={ids.value}
          type="text"
          {...(name === undefined ? {} : { name })}
          value={value}
          // 0.9.13: no length is set: a paste is taken whole, without the blanks around it,
          // and judged as it is (`pasted`).
          spellCheck={false}
          autoCapitalize="none"
          autoComplete="off"
          placeholder="#rrggbb"
          disabled={disabled}
          aria-invalid={said ? true : undefined}
          aria-describedby={describedBy || undefined}
          onFocus={() => setTyping(true)}
          onBlur={() => setTyping(false)}
          onChange={(event) => onChange(event.target.value)}
          onPaste={(event) => {
            const text = event.clipboardData.getData("text");
            if (text === "") return;
            event.preventDefault();
            const box = event.currentTarget;
            const at = box.selectionStart ?? box.value.length;
            onChange(pasted(box.value, text, at, box.selectionEnd ?? at));
          }}
        />
        <ColourChip value={value} testId={`${id}-chip`} />
        <Sample text={sample} colour={colour} as={sampleAs} />
      </div>
      {said && (
        <p className="field-error" id={ids.error}>
          {said}
        </p>
      )}
      <Problem error={colours.error} />
      {colours.loading && !colours.data && (
        <p className="muted loading-late" role="status">
          Loading the colours to choose from…
        </p>
      )}
      {colours.data && (
        <>
          <Slider
            id={id}
            label={label}
            colours={colours.data}
            value={value}
            onChange={onChange}
            disabled={disabled}
          />
          <Swatches
            id={id}
            label={label}
            grid={colours.data.grid}
            value={value}
            onChange={onChange}
            disabled={disabled}
          />
        </>
      )}
      {hint && (
        <p className="hint" id={ids.hint}>
          {hint}
        </p>
      )}
    </fieldset>
  );
}

/**
 * A picker as a form's field: its ids made unique on the page, as the form's own fields
 * are, so that two forms with a colour can be open at once.
 */
export function ColourField(props: Omit<ColourPickerProps, "id">) {
  const id = `colour${useId().replace(/[^A-Za-z0-9_-]/g, "")}`;
  return <ColourPicker id={id} {...props} />;
}

interface PartProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean | undefined;
}

/**
 * The slider of 32: a range input over a track that shows its steps. A range input always
 * stands at a step. Where the value is none of them, the slider rests at the step nearest
 * to it, its thumb is drawn hollow and dashed, and it says in words that it holds no step;
 * the first move, by a key or a press, takes the value to the step it comes to.
 */
function Slider({
  id,
  label,
  colours,
  value,
  onChange,
  disabled,
}: PartProps & { colours: Colours }) {
  const steps = colours.slider.map((step) => safeColour(step));
  const at = stepOf(colours.slider, value);
  const none = at < 0;
  const resting = none ? restingStep(colours.grid, colours.slider, value) : at;
  const words = stepWords(colours.grid, colours.slider, value);

  function take(step: number) {
    const colour = steps[step];
    if (colour) onChange(colour);
  }

  function key(event: KeyboardEvent<HTMLInputElement>) {
    // Resting, the slider moves from where it rests, and the first key takes the step.
    if (!none) return;
    const to = stepAfterKey(resting, event.key, steps.length);
    if (to === null) return;
    event.preventDefault();
    take(to);
  }

  function released(event: PointerEvent<HTMLInputElement>) {
    // A press at the step it rests at changes nothing for the input: it takes the step.
    const step = Number(event.currentTarget.value);
    const colour = steps[step];
    if (colour && !sameColour(colour, value)) take(step);
  }

  return (
    <div className="colour-part">
      <div className="colour-part-head">
        <label htmlFor={`${id}-slider`}>
          <span className="visually-hidden">{label}, </span>Slider of {steps.length}
        </label>
        <span className="muted" aria-hidden="true" data-testid={`${id}-step`}>
          {words}
        </span>
      </div>
      <div className="colour-slider" data-none={none ? "true" : "false"}>
        <div className="colour-track" aria-hidden="true">
          {colours.slider.map((step) => {
            const shown = safeColour(step);
            return <span key={step} {...(shown ? { style: { backgroundColor: shown } } : {})} />;
          })}
        </div>
        <input
          id={`${id}-slider`}
          type="range"
          min={0}
          max={Math.max(steps.length - 1, 0)}
          step={1}
          value={resting}
          disabled={disabled}
          aria-valuetext={words}
          onChange={(event) => take(Number(event.target.value))}
          onKeyDown={key}
          onPointerUp={released}
        />
      </div>
    </div>
  );
}

const MOVES: Readonly<Record<string, [rows: number, columns: number]>> = {
  ArrowRight: [0, 1],
  ArrowLeft: [0, -1],
  ArrowDown: [1, 0],
  ArrowUp: [-1, 0],
};

/**
 * The grid of 64: a row to each shade, the lightest first, and the hues across. Each
 * swatch is a button named by its hue, its shade and its value; the one chosen is
 * pressed, ringed and ticked. The grid is one stop of Tab, at the swatch chosen or the
 * first; the arrow keys move within it, Home and End to the ends of a row, and with
 * Control to the first and the last; Enter or Space chooses.
 */
function Swatches({
  id,
  label,
  grid,
  value,
  onChange,
  disabled,
}: PartProps & { grid: string[][] }) {
  const host = useRef<HTMLTableElement>(null);
  // The swatch that has the keyboard, while it is in the grid.
  const [cursor, setCursor] = useState<Place | null>(null);
  const chosen = placeIn(grid, value);
  const stop = cursor ?? chosen ?? { row: 0, column: 0 };
  const count = grid.reduce((sum, row) => sum + row.length, 0);

  function move(event: KeyboardEvent<HTMLButtonElement>, from: Place) {
    let to: Place | null = null;
    const by = MOVES[event.key];
    if (by) to = { row: from.row + by[0], column: from.column + by[1] };
    else if (event.key === "Home") {
      to = { row: event.ctrlKey ? 0 : from.row, column: 0 };
    } else if (event.key === "End") {
      const last = event.ctrlKey ? grid.length - 1 : from.row;
      to = { row: last, column: (grid[last]?.length ?? 0) - 1 };
    }
    if (!to) return;
    event.preventDefault();
    if (grid[to.row]?.[to.column] === undefined) return;
    setCursor(to);
    host.current
      ?.querySelector<HTMLButtonElement>(`[data-row="${to.row}"][data-column="${to.column}"]`)
      ?.focus();
  }

  return (
    <div className="colour-part">
      <div className="colour-part-head">
        <span id={`${id}-grid-label`}>
          <span className="visually-hidden">{label}, </span>Grid of {count}
        </span>
      </div>
      <table
        ref={host}
        className="colour-grid"
        aria-labelledby={`${id}-grid-label`}
        aria-describedby={`${id}-grid-how`}
      >
        <tbody>
          {grid.map((swatches, row) => (
            <tr className="colour-grid-row" key={swatches.join(" ")}>
              {swatches.map((swatch, column) => {
                const colour = safeColour(swatch);
                const pressed = chosen?.row === row && chosen.column === column;
                return (
                  <td className="colour-cell" key={swatch}>
                    {colour && (
                      <button
                        type="button"
                        className="colour-swatch"
                        data-row={row}
                        data-column={column}
                        data-colour={colour.toLowerCase()}
                        tabIndex={stop.row === row && stop.column === column ? 0 : -1}
                        aria-pressed={pressed}
                        aria-label={colourWords(grid, colour)}
                        disabled={disabled}
                        style={{ backgroundColor: colour, color: textOn(colour) }}
                        onFocus={() => setCursor({ row, column })}
                        onBlur={(event) => {
                          if (!host.current?.contains(event.relatedTarget)) setCursor(null);
                        }}
                        onKeyDown={(event) => move(event, { row, column })}
                        onClick={() => onChange(colour)}
                      >
                        {pressed && <span aria-hidden="true">✓</span>}
                      </button>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="visually-hidden" id={`${id}-grid-how`}>
        A row to each shade, the lightest first; a column to each hue. Arrow keys move, Enter
        chooses.
      </p>
    </div>
  );
}
