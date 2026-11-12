interface PagerProps {
  total: number;
  limit: number;
  offset: number;
  /** What is counted, in the plural: "users", "events". */
  noun: string;
  onChange: (offset: number) => void;
}

/** Which part of a list is on show, with buttons for the pages before and after. */
export function Pager({ total, limit, offset, noun, onChange }: PagerProps) {
  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + limit, total);
  return (
    <nav className="pager" aria-label={`Pages of ${noun}`}>
      <p>{total === 0 ? `No ${noun}` : `${first}–${last} of ${total} ${noun}`}</p>
      <button
        type="button"
        disabled={offset <= 0}
        onClick={() => onChange(Math.max(0, offset - limit))}
      >
        Previous
      </button>
      <button type="button" disabled={last >= total} onClick={() => onChange(offset + limit)}>
        Next
      </button>
    </nav>
  );
}

/** An offset from a URL: a whole number, never negative. */
export function toOffset(text: string | null): number {
  const value = Number.parseInt(text ?? "", 10);
  return Number.isFinite(value) && value > 0 ? value : 0;
}
