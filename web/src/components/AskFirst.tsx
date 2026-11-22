// 0.9.17: a question asked before a change that is otherwise made at once, as a box of a
// group that takes the last role from an account (P-314 (4)). It is open while it is in
// the page, and closes as Cancel does on Escape.

import { type ReactNode, useId, useLayoutEffect, useRef } from "react";

interface AskFirstProps {
  /** The question, as the heading of the dialog. */
  title: string;
  /** What will happen. */
  children: ReactNode;
  /** The text of the button that goes ahead. */
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function AskFirst({ title, children, confirmLabel, onConfirm, onCancel }: AskFirstProps) {
  const id = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  useLayoutEffect(() => {
    // The focus goes back to what had it, the box pressed, when the dialog goes.
    const before = document.activeElement;
    const shown = dialog.current;
    if (shown && !shown.open) shown.showModal();
    return () => {
      shown?.close();
      if (before instanceof HTMLElement) before.focus();
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      aria-labelledby={`${id}-title`}
      data-testid="ask-first"
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
    >
      <h2 id={`${id}-title`}>{title}</h2>
      <div className="dialog-body">{children}</div>
      <p className="actions">
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className="danger" onClick={onConfirm}>
          {confirmLabel}
        </button>
      </p>
    </dialog>
  );
}
