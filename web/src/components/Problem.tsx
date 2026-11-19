import { createContext, useContext, useEffect, useEffectEvent, useState } from "react";
import { Link } from "react-router";
import type { ApiError, ExistingRecord } from "../api/client";
import { hearChanges } from "../lib/hooks";
import { existingLead, existingPath, fieldErrors, fieldLine, sentence } from "../lib/problems";
import { runOnItLead } from "../lib/removal";

/**
 * What else than another person may have changed the record a page shows, said where a
 * change of it is refused as stale: the next term of a contract, which moves its version
 * on the day it begins. A page gives it around the forms of that record alone.
 */
export const StaleCause = createContext("");

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
  const cause = useContext(StaleCause);
  // A message about a field the form shows is shown beside its input, not here.
  const others = fieldErrors(visible, shown).rest;
  const heading =
    visible && visible.detail !== "" && visible.status !== 429 && visible.status !== 0
      ? visible.title
      : "";
  // 0.9.6: the record that has the value already, as a link to it (P-207).
  const existing = visible && !visible.stale ? visible.existing : null;
  const existingTo = existing ? existingPath(existing) : null;
  return (
    <div className="live" aria-live="assertive" aria-atomic="true">
      {visible && (
        <div className="alert alert-error" data-status={visible.status}>
          {visible.stale ? (
            <p>
              <strong>This record has changed.</strong>{" "}
              {cause || "Someone changed it after you opened it, so your change was not saved."}{" "}
              Reload it, then make your change again.
            </p>
          ) : (
            <p>
              {heading && <strong>{sentence(heading)} </strong>}
              {sentence(visible.message)}
            </p>
          )}
          {/* 0.9.7: a record that was deleted: the detail says when and by whom (P-227). */}
          {visible.deleted?.reason && (
            <p data-testid="deleted-reason">The reason given: {visible.deleted.reason}</p>
          )}
          {existing && (
            <p>
              {existingLead(existing)}{" "}
              {existingTo ? (
                <Link to={existingTo}>{existing.label}</Link>
              ) : (
                <strong>{existing.label}</strong>
              )}
            </p>
          )}
          {/* 0.9.8: what runs on a stack or a cluster refused retirement, as links (P-247). */}
          {visible.dependsOn.length > 0 && <DependsOn records={visible.dependsOn} />}
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

/**
 * The records a refusal names as standing on the record refused: today, the items that
 * run on a stack or a cluster, which the server's words say to give another host, or to
 * retire, first. Each is a link to its page.
 */
function DependsOn({ records }: { records: readonly ExistingRecord[] }) {
  return (
    <div data-testid="problem-depends-on">
      <p>{runOnItLead(records.length)}</p>
      <ul className="removal-refused">
        {records.map((record) => {
          const to = existingPath(record);
          return (
            <li key={`${record.record_type} ${record.hid}`}>
              {to ? <Link to={to}>{record.label}</Link> : <strong>{record.label}</strong>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/**
 * A quiet message that something was done. Always in the page, as Problem is.
 *
 * It is taken away when the next change is sent from the page (P-182), so that the page
 * never says done and refused at once, and comes back when that change is done: with
 * what the page says of it, which may be the very words it said before, as after a
 * second save of the same record.
 */
export function Notice({
  text,
  link,
  parts,
}: {
  text: string;
  link?: { to: string; text: string };
  /**
   * 0.9.8: what is said in parts, each words or a record as a link, as a replacement
   * names both of its items (P-242). `text` is then the same words, all of them.
   */
  parts?: ReadonlyArray<string | { to: string; text: string }>;
}) {
  // The words taken away, while they are what the page would say.
  const [away, setAway] = useState<string | null>(null);
  const heard = useEffectEvent((what: "sent" | "done" | "refused") => {
    if (what === "sent") setAway(text);
    else if (what === "done") setAway(null);
  });
  useEffect(() => hearChanges(heard), []);
  const shown = away !== null && away === text ? "" : text;
  return (
    <div className="live" role="status" aria-live="polite">
      {shown && (
        <p className="alert alert-ok">
          {parts ? <Parts parts={parts} /> : shown}
          {/* 0.9.5: what was made, as a link to it (P-192). */}
          {link && (
            <>
              {" "}
              <Link to={link.to}>{link.text}</Link>
            </>
          )}
        </p>
      )}
    </div>
  );
}

/** Words and links in their order, each known by where its words begin. */
function Parts({ parts }: { parts: ReadonlyArray<string | { to: string; text: string }> }) {
  let at = 0;
  const placed = parts.map((part) => {
    const words = typeof part === "string" ? part : part.text;
    const one = { part, key: `${at}` };
    at += words.length + 1;
    return one;
  });
  return (
    <>
      {placed.map(({ part, key }) =>
        typeof part === "string" ? (
          <span key={key}>{part}</span>
        ) : (
          <Link key={key} to={part.to}>
            {part.text}
          </Link>
        ),
      )}
    </>
  );
}
