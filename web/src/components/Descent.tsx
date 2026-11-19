// A location, or a planned location, that a record has from the record above it: a
// minor item from the item it is in, a member from its group, a group from the group it
// is nested in. It is shown as a place has what is inherited: lighter, marked in words,
// with the record it came from named and linked.

import { Link } from "react-router";
import { api } from "../api";
import {
  isFromAbove,
  membersWithOwn,
  membersWithOwnPath,
  membersWithOwnText,
  type PlaceInForce,
  type PlaceKind,
  placeNoun,
  placeSource,
  type SourceRecord,
} from "../lib/descent";
import { useLoad } from "../lib/hooks";
import { placePath } from "../lib/places";

/**
 * Where a location in force came from, after the location itself: "Set here" for the
 * record's own, or that it is inherited, with the item or the group it came from.
 */
export function FromAbove({ effective }: { effective: PlaceInForce }) {
  if (effective.value === null) return null;
  if (!isFromAbove(effective)) return <span className="muted"> · Set here</span>;
  return <InheritedFrom from={placeSource(effective)} />;
}

/**
 * That a value is inherited, after the value itself: lighter, marked in words, with the
 * item or the group it came from named and linked.
 */
export function InheritedFrom({ from }: { from: SourceRecord | null }) {
  return (
    <span className="inherited">
      {" "}
      · <span className="badge badge-plain mark">Inherited</span> from{" "}
      {from ? <Link to={from.path}>{from.text}</Link> : "above"}
    </span>
  );
}

interface OwnerNoteProps {
  /** The owner in force, which the record has from above. */
  effective: { value: string | boolean | null; label: string | null; source: string };
  from: SourceRecord | null;
  /** What the form is of: "item", "group". */
  what: string;
}

/**
 * What a form says above the owner of a record that has none of its own and has one
 * from above: which, from which record, and that one chosen here overrides it.
 */
export function OwnerNote({ effective, from, what }: OwnerNoteProps) {
  if (typeof effective.value !== "string") return null;
  return (
    <p className="form-note inherited" data-testid="owner-note" data-source={effective.source}>
      <span className="badge badge-plain mark">Inherited</span>{" "}
      <Link to={`/owners/${encodeURIComponent(effective.value)}`}>
        {effective.label ?? effective.value}
      </Link>
      , from {from ? <Link to={from.path}>{from.text}</Link> : "above"}. An owner chosen here is
      this {what}&apos;s own, and overrides that.
    </p>
  );
}

interface PlaceNoteProps {
  kind: PlaceKind;
  effective: PlaceInForce;
  /** What the form is of: "item", "group". */
  what: string;
}

/**
 * What a form says above the location, or the planned location, of a record that has
 * none of its own and has one from above: which, from which record, and that one chosen
 * here overrides it. Nothing where there is none from above.
 */
export function PlaceNote({ kind, effective, what }: PlaceNoteProps) {
  if (!isFromAbove(effective) || typeof effective.value !== "string") return null;
  const from = placeSource(effective);
  return (
    <p className="form-note inherited" data-testid={`${kind}-note`} data-source={effective.source}>
      <span className="badge badge-plain mark">Inherited</span>{" "}
      {kind === "location" ? "It is in" : "It is planned for"}{" "}
      <Link to={placePath("location", effective.value)}>{effective.label ?? effective.value}</Link>,
      from {from ? <Link to={from.path}>{from.text}</Link> : "above"}. A {placeNoun(kind)} chosen
      here is this {what}&apos;s own, and overrides that.
    </p>
  );
}

interface MembersOfTheirOwnProps {
  groupHid: string;
  kind: PlaceKind;
  /** Changes when the group does, so that the number is read again. */
  turn: number;
}

/**
 * How many current members of a group have a location, or a plan, of their own: an
 * override of what the group has. The number is a link to those members in the grid.
 */
export function MembersOfTheirOwn({ groupHid, kind, turn }: MembersOfTheirOwnProps) {
  const own = useLoad(`members-own ${kind} ${groupHid} ${turn}`, (signal) =>
    api.request("get", "/api/v1/items", {
      query: { filter: membersWithOwn(groupHid, kind), limit: 1, include_drafts: true },
      signal,
    }),
  );
  if (!own.data) return null;
  const text = membersWithOwnText(own.data.total, kind);
  return (
    <span className="muted" data-testid={`members-own-${kind}`}>
      {"; "}
      {text.linked && (
        <>
          <Link to={membersWithOwnPath(groupHid, kind)}>{text.linked}</Link>{" "}
        </>
      )}
      {text.after}
    </span>
  );
}
