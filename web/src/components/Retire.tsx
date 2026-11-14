import type { ReactNode } from "react";
import { useAction } from "../lib/hooks";
import { ConfirmButton } from "./ConfirmButton";
import { Problem } from "./Problem";

interface RetireProps {
  /** What the record is, in a word: "contract", "agreement". */
  what: string;
  /** What the record is called. */
  name: string;
  retired: boolean;
  /** What retiring it does, said before it is done. */
  about: ReactNode;
  /** What it means that it is retired, said once it is. */
  retiredAbout: ReactNode;
  retire: () => Promise<unknown>;
  bringBack: () => Promise<unknown>;
  onChanged: (text: string) => void;
  /** Read the record again, as when someone else has changed it. */
  onReload: () => void;
}

/**
 * Retire a record, or bring a retired one back. Nothing is deleted: a retired record
 * stays on file, is left out of lists unless asked for, and can be brought back.
 */
export function Retire(props: RetireProps) {
  const { what, name, retired, about, retiredAbout, retire, bringBack, onChanged, onReload } =
    props;
  const action = useAction();

  async function run(change: () => Promise<unknown>, done: string) {
    const result = await action.run(change);
    if (result.ok) onChanged(done);
  }

  return (
    <section aria-labelledby="retire">
      <h2 id="retire">{retired ? "Retired" : "Retire"}</h2>
      <Problem error={action.error} onReload={onReload} />
      {retired ? (
        <>
          <p>{retiredAbout}</p>
          <p className="actions">
            <button
              type="button"
              disabled={action.busy}
              onClick={() => run(bringBack, `${name} is back.`)}
            >
              Bring back
            </button>
          </p>
        </>
      ) : (
        <>
          <p>{about}</p>
          <p className="actions">
            <ConfirmButton
              label={`Retire this ${what}`}
              title={`Retire ${name}?`}
              confirmLabel="Retire"
              onConfirm={() => run(retire, `${name} was retired.`)}
              disabled={action.busy}
            >
              <p>
                It stays on file and can be brought back. Lists leave it out unless Include archived
                is on.
              </p>
            </ConfirmButton>
          </p>
        </>
      )}
    </section>
  );
}
