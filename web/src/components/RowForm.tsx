// 0.9.3: a form that changes one row of a table opens directly beneath that row, in a row
// of its own whose one cell spans every column, and not below the whole table (P-171).
// The row it changes stays in view above it, and once it closes the page is where it
// was. The focus moves into the form as it opens, and back to the button that opened it
// when it closes. One form is open at a time: the page holds which, and opening another
// closes the first, letting go of what was typed in it.
//
// Admin › Settings, Tags, Lifecycle rules and Files, and the Files and links of a record,
// each open their forms so. The style is `.row-form` in styles.css.

import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";

/**
 * The field a form opens on: the first that takes a value, and in a choice of a few the
 * one that is chosen, where the Tab key would reach it.
 */
export function firstField(form: HTMLElement): HTMLElement | null {
  const first = form.querySelector<HTMLElement>("input, select, textarea");
  if (!(first instanceof HTMLInputElement) || first.type !== "radio") return first;
  const chosen = [...form.querySelectorAll<HTMLInputElement>('input[type="radio"]')].find(
    (radio) => radio.name === first.name && radio.checked,
  );
  return chosen ?? first;
}

interface FormRowProps {
  /** What the row it changes is known by: `data-form-of` holds it. */
  of: string;
  /** How many columns the table has, which the one cell spans. */
  columns: number;
  children: ReactNode;
}

/**
 * The row beneath the row a form changes, holding the form across the table. The focus
 * moves to the form's first field as it opens.
 */
export function FormRow({ of, columns, children }: FormRowProps) {
  const cell = useRef<HTMLTableCellElement>(null);
  useEffect(() => {
    const opened = cell.current;
    if (!opened) return;
    firstField(opened)?.focus();
    // P-186: the whole form, its button to save with it, is brought into the window where
    // it fits with the row it changes above it; where they do not both fit, the window
    // moves no further than keeps that row in view, at the top (P-171).
    const row = opened.parentElement?.previousElementSibling ?? opened;
    const top = row.getBoundingClientRect().top;
    const below = opened.getBoundingClientRect().bottom - window.innerHeight;
    const by = Math.min(below, Math.max(0, top));
    if (by > 0) window.scrollBy(0, by);
  }, []);
  return (
    <tr className="row-form" data-form-of={of}>
      <td colSpan={columns} ref={cell}>
        {children}
      </td>
    </tr>
  );
}

/** What a list was read as: whether it is being read, and what was read last. */
interface Read {
  loading: boolean;
  data: unknown;
}

export interface Openers {
  /** The ref of the button that opens the form of a row, by what the row is known by. */
  opener: (key: string) => (button: HTMLButtonElement | null) => (() => void) | undefined;
  /**
   * The form of a row closed: the focus goes back to the button that opened it. Where
   * the list is being read again after a change, `reading` is true, and the focus goes
   * back once it has been, so that a row the sort moves is in its place.
   */
  closed: (key: string, reading?: boolean) => void;
  /** Another form opened: the focus goes back to no button. */
  forget: () => void;
}

/**
 * The buttons that open the forms of the rows of a list, and the focus given back to one
 * of them when its form closes. `busy` is true while those buttons are disabled.
 */
export function useOpeners(list: Read, busy = false): Openers {
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const [back, setBack] = useState<{ key: string; reading: boolean } | null>(null);
  const { loading, data } = list;

  // The list was read again, or could not be, and what was read last is on show.
  useEffect(() => {
    if (loading || data === undefined) return;
    setBack((was) => (was?.reading ? { ...was, reading: false } : was));
  }, [loading, data]);

  useEffect(() => {
    if (back === null || back.reading || busy) return;
    buttons.current.get(back.key)?.focus();
    setBack(null);
  }, [back, busy]);

  const opener = useCallback(
    (key: string) => (button: HTMLButtonElement | null) => {
      if (!button) return;
      const known = buttons.current;
      known.set(key, button);
      return () => {
        if (known.get(key) === button) known.delete(key);
      };
    },
    [],
  );
  const closed = useCallback((key: string, reading = false) => setBack({ key, reading }), []);
  const forget = useCallback(() => setBack(null), []);
  return { opener, closed, forget };
}
