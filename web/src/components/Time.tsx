import { formatTime } from "../lib/format";

/** A moment in the reader's time zone, or a dash when there is none. */
export function Time({ at }: { at: string | null | undefined }) {
  if (!at) return <span className="muted">—</span>;
  return (
    <time dateTime={at} title={at}>
      {formatTime(at)}
    </time>
  );
}
