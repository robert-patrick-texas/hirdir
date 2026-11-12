import type { ApiError } from "../api/client";

/** A sentence as it is shown: a capital first letter and a full stop. */
function sentence(text: string): string {
  const trimmed = text.trim();
  if (trimmed === "") return "";
  const capital = trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
  return /[.!?]$/.test(capital) ? capital : `${capital}.`;
}

interface ProblemProps {
  error: ApiError | null;
  /** The fields whose messages are shown beside their inputs, and so not repeated here. */
  shown?: readonly string[];
  /** Read the record again. Offered when the server says it has changed. */
  onReload?: () => void;
}

/**
 * What the server said went wrong. The region is always in the page, so that a screen
 * reader announces the message when it appears.
 */
export function Problem({ error, shown = [], onReload }: ProblemProps) {
  const visible = error && !error.aborted ? error : null;
  const others = visible
    ? Object.entries(visible.fields).filter(([field]) => !shown.includes(field))
    : [];
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
                <li key={field}>
                  {field}: {message}
                </li>
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
