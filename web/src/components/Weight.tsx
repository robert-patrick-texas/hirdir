// 0.8.0: a support weight in force, and the support weight of a place (P-139, P-155).
// What is the record's own is shown plainly; a default is lighter, marked in words, with
// the setting it came from; a weight raised to the minimum of its kind says so, with what
// it was before. Nothing is resolved here: the server says all of it.

import {
  type EffectiveWeight,
  raisedText,
  type WeightKind,
  weightInherited,
  weightSource,
} from "../lib/weights";

function Dash() {
  return <span className="muted">—</span>;
}

/** That a weight was raised to the minimum, after the weight: nothing where it was not. */
export function Raised({ weight, kind }: { weight: EffectiveWeight; kind: WeightKind }) {
  const text = raisedText(weight, kind);
  if (!text) return null;
  return (
    <span data-testid="weight-raised" data-raised-from={weight.raised_from ?? ""}>
      {" "}
      · <span className="badge mark">Raised</span> {text}
    </span>
  );
}

/**
 * A weight in force: its value, where it came from, and whether it was raised to the
 * minimum of its kind. A default is shown lighter, as every inherited value is.
 */
export function WeightInForce({ weight, kind }: { weight: EffectiveWeight; kind: WeightKind }) {
  const inherited = weightInherited(weight);
  return (
    <span
      data-testid="weight-in-force"
      data-value={weight.value ?? ""}
      data-source={weight.source}
      className={inherited ? "inherited" : undefined}
    >
      {weight.value ?? <Dash />}{" "}
      <span className="muted">
        ·{" "}
        {inherited && (
          <>
            <span className="badge badge-plain mark">Inherited</span>{" "}
          </>
        )}
        <span data-testid="weight-source">{weightSource(weight, kind)}</span>
      </span>
      <Raised weight={weight} kind={kind} />
    </span>
  );
}

/** What the facts of a place need of it to show its weight. */
interface Weighed {
  support_weight: string | null;
  /** A site's weight in force: a region and a location count their own alone. */
  effective?: { support_weight: EffectiveWeight };
}

/**
 * The support weight of a place, among its facts: its own, which the places beneath do
 * not take, and for a site the weight it counts at, its own or the default of a site,
 * raised to the minimum of a site where it was below it.
 */
export function PlaceWeightFacts({ place }: { place: Weighed }) {
  const inForce = place.effective?.support_weight;
  return (
    <>
      <dt>Support weight</dt>
      <dd data-testid="place-weight" data-value={place.support_weight ?? ""}>
        {place.support_weight ?? <span className="muted">None of its own</span>}
        <span className="muted"> · the work the place adds by itself; not passed down</span>
      </dd>
      {inForce && (
        <>
          <dt>Weight it counts at</dt>
          <dd data-testid="place-weight-in-force">
            <WeightInForce weight={inForce} kind="site" />
          </dd>
        </>
      )}
    </>
  );
}
