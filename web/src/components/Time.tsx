import { formatTime, formatTimeLong } from "../lib/format";

/**
 * A moment in the reader's time zone, or a dash when there is none. Pointing at it shows
 * the same moment written out in full, with the name of the zone.
 */
export function Time({ at }: { at: string | null | undefined }) {
  if (!at) return <span className="muted">—</span>;
  return (
    <time dateTime={at} title={formatTimeLong(at)}>
      {formatTime(at)}
    </time>
  );
}
