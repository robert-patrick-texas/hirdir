import { type ReactNode, useId, useRef, useState } from "react";

interface ConfirmButtonProps {
  /** The text of the button that asks. */
  label: string;
  /** The question, as the heading of the dialog. */
  title: string;
  /** What will happen, in the dialog. */
  children: ReactNode;
  /** The text of the button that goes ahead. */
  confirmLabel: string;
  onConfirm: () => Promise<unknown> | unknown;
  disabled?: boolean;
}

/** A button for something that cannot be undone: it asks first, in a modal dialog. */
export function ConfirmButton(props: ConfirmButtonProps) {
  const { label, title, children, confirmLabel, onConfirm, disabled } = props;
  const id = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);

  async function confirm() {
    setBusy(true);
    try {
      await onConfirm();
    } finally {
      setBusy(false);
      dialog.current?.close();
    }
  }

  return (
    <>
      <button
        type="button"
        className="danger"
        disabled={disabled}
        onClick={() => dialog.current?.showModal()}
      >
        {label}
      </button>
      <dialog ref={dialog} aria-labelledby={`${id}-title`}>
        <h2 id={`${id}-title`}>{title}</h2>
        <div className="dialog-body">{children}</div>
        <p className="actions">
          <button type="button" onClick={() => dialog.current?.close()} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="danger" onClick={confirm} disabled={busy}>
            {confirmLabel}
          </button>
        </p>
      </dialog>
    </>
  );
}
