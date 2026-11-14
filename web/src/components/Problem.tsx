import type { ApiError } from "../api/client";
import { fieldErrors, fieldLine, sentence } from "../lib/problems";

interface ProblemProps {
  error: ApiError | null;
  /** The fields whose messages are shown beside their inputs, and so not repeated here. */
  shown?: readonly string[];
  /** Read the record again. Offered when the server says it has changed. */
  onReload?: () => void;
  /**
   * What to call a field that has no input on the page, in place of the name the server
   * knows it by: `parent_region_hid` is "The region it is in". A field named as blank
   * is not named at all, and its message stands as a sentence of its own.
   */
  labels?: Readonly<Record<string, string>>;
}

/**
 * What the server said went wrong. The region is always in the page, so that a screen
 * reader announces the message when it appears.
 */
export function Problem({ error, shown = [], onReload, labels = {} }: ProblemProps) {
  const visible = error && !error.aborted ? error : null;
  // A message about a field the form shows is shown beside its input, not here.
  const others = fieldErrors(visible, shown).rest;
  const heading =
    visible && visible.detail !== "" && visible.status !== 429 && visible.status !== 0
      ? visible.title
      : "";
  return (
    <div className="live" aria-live="assertive" aria-atomic="true">
      {visible && (
        <div className="alert alert-error" data-status={visible.status}>
          {visible.stale ? (
            <p>
              <strong>This record has changed.</strong> Someone changed it after you opened it, so
              your change was not saved. Reload it, then make your change again.
            </p>
          ) : (
            <p>
              {heading && <strong>{sentence(heading)} </strong>}
              {sentence(visible.message)}
            </p>
          )}
          {others.length > 0 && (
            <ul>
              {others.map(([field, message]) => (
                <li key={field}>{fieldLine(field, message, labels)}</li>
              ))}
            </ul>
          )}
          {visible.stale && onReload && (
            <p>
              <button type="button" onClick={onReload}>
                Reload
              </button>
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/** A quiet message that something was done. Always in the page, as Problem is. */
export function Notice({ text }: { text: string }) {
  return (
    <div className="live" role="status" aria-live="polite">
      {text && <p className="alert alert-ok">{text}</p>}
    </div>
  );
}
