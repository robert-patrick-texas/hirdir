import { useId, useState } from "react";
import type { ApiError } from "../api/client";
import { fieldErrors } from "../lib/problems";
import { LocationField } from "./LocationField";

/**
 * True when a record was not brought back because of where it was: the server names
 * `record_status`, and says to give the record another location, or none, with the change.
 */
export function refusedForItsPlace(error: ApiError | null): boolean {
  return fieldErrors(error, ["record_status"]).shown.record_status !== undefined;
}

interface BringBackElsewhereProps {
  /** What is brought back, as the page calls it: "item", "group". */
  what: string;
  /** What having no location of its own means for the record: "No location". */
  blank: string;
  busy: boolean;
  /** Bring the record back with this location, or with none. */
  onBringBack: (locationHid: string | null) => void;
}

/**
 * The way on for an item or a device group that was not brought back because its
 * location was retired after it: another location is chosen, or none, and the record is
 * brought back with that change, as one request.
 */
export function BringBackElsewhere({ what, blank, busy, onBringBack }: BringBackElsewhereProps) {
  const id = useId();
  const [location, setLocation] = useState("");
  return (
    <section className="panel" aria-labelledby={id} data-testid="bring-back-elsewhere">
      <h3 id={id}>Bring back in another location</h3>
      <p className="hint">
        The location the {what} was in has been retired since. Choose another location for it, or
        none, and it is brought back with that change. To have it where it was, bring that location
        back first, under Geography.
      </p>
      <div className="fields">
        <LocationField
          label="Another location"
          name="location_hid"
          value={location}
          onChange={setLocation}
          blank={blank}
          disabled={busy}
        />
      </div>
      <p className="actions">
        <button
          type="button"
          className="primary"
          disabled={busy}
          onClick={() => onBringBack(location === "" ? null : location)}
        >
          {location === "" ? "Bring back with none" : "Bring back there"}
        </button>
      </p>
    </section>
  );
}
