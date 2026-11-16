// A picture of a record's references, shown within the page (P-159). The content is
// fetched with the session's token, as everything is, and shown from a `blob:` address
// of the page's own in an <img>, which runs nothing whatever the picture holds. The
// address is let go when another picture is shown and when the viewer closes.

import { type KeyboardEvent, useEffect, useId, useRef, useState } from "react";
import type { ApiError } from "../api";
import { toApiError } from "../lib/hooks";
import type { Listed } from "../lib/references";
import { Problem } from "./Problem";
import { pictureOf } from "./referenceFiles";

interface PictureViewerProps {
  /** The pictures of the section, in its order. */
  pictures: readonly Listed[];
  /** The one on show, by its place among them; null while the viewer is closed. */
  at: number | null;
  onMove: (at: number) => void;
  onClose: () => void;
}

/** The viewer: a dialog with the picture, its title, the one before and the one after. */
export function PictureViewer({ pictures, at, onMove, onClose }: PictureViewerProps) {
  const id = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const open = at !== null;
  const picture = at === null ? undefined : pictures[at];
  const [shown, setShown] = useState<{ hid: string; url: string } | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);

  useEffect(() => {
    if (picture === undefined) return;
    const controller = new AbortController();
    let address: string | null = null;
    setShown(null);
    setError(null);
    pictureOf(picture, controller.signal).then(
      (blob) => {
        if (controller.signal.aborted) return;
        address = URL.createObjectURL(blob);
        setShown({ hid: picture.hid, url: address });
      },
      (thrown: unknown) => {
        if (!controller.signal.aborted) setError(toApiError(thrown));
      },
    );
    return () => {
      controller.abort();
      if (address !== null) URL.revokeObjectURL(address);
    };
  }, [picture]);

  const before = at !== null && at > 0 ? at - 1 : null;
  const after = at !== null && at < pictures.length - 1 ? at + 1 : null;

  function keyDown(event: KeyboardEvent<HTMLDialogElement>) {
    if (event.key === "ArrowLeft" && before !== null) onMove(before);
    if (event.key === "ArrowRight" && after !== null) onMove(after);
  }

  return (
    <dialog
      ref={dialog}
      className="picture-viewer"
      aria-labelledby={`${id}-title`}
      data-testid="picture-viewer"
      onClose={onClose}
      onKeyDown={keyDown}
    >
      {picture && (
        <>
          <h2 id={`${id}-title`}>{picture.title}</h2>
          <p className="muted">
            {at !== null && pictures.length > 1 && `${at + 1} of ${pictures.length} · `}
            {picture.file_name}
          </p>
          <Problem error={error} />
          <div className="picture-frame">
            {shown && shown.hid === picture.hid ? (
              <img src={shown.url} alt={picture.title} />
            ) : (
              !error && (
                <p role="status" className="muted loading-late">
                  Loading…
                </p>
              )
            )}
          </div>
          {picture.notes && <p>{picture.notes}</p>}
        </>
      )}
      <p className="actions">
        <button
          type="button"
          disabled={before === null}
          onClick={() => before !== null && onMove(before)}
        >
          Previous
        </button>
        <button
          type="button"
          disabled={after === null}
          onClick={() => after !== null && onMove(after)}
        >
          Next
        </button>
        <button type="button" onClick={() => dialog.current?.close()}>
          Close
        </button>
      </p>
    </dialog>
  );
}
