// 0.9.15: Generate, beside the box of a new access code (P-300), on the Profile, on New
// user and under Access code on a user's page. It asks the server for a code made as the
// server makes every code, `GET /auth/new-access-code`, long enough for the setting
// `access_code_min_length`, and hands it to the form, which puts it in its box. Nothing
// is saved until the form's own button is pressed, and the code is sent and checked as a
// typed one is. The server stores nothing and writes nothing for it.

import { type ReactNode, useState } from "react";
import { type ApiError, api } from "../api";
import { toApiError } from "../lib/hooks";
import { Problem } from "./Problem";

interface GenerateCodeProps {
  /** The code the server made, for the form to put in its box. */
  onMade: (code: string) => void;
  disabled?: boolean;
  /** The box of the code, beside which the button stands. */
  children: ReactNode;
}

/** The box of a new access code, with Generate beside it, and why a code was not made. */
export function GenerateCode({ onMade, disabled, children }: GenerateCodeProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      const made = await api.request("get", "/api/v1/auth/new-access-code", {});
      onMade(made.access_code);
    } catch (thrown) {
      setError(toApiError(thrown));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="with-generate" data-testid="generate-code">
      {children}
      <button
        type="button"
        className="generate-code"
        onClick={() => void generate()}
        disabled={disabled || busy}
      >
        Generate
      </button>
      {error && (
        <div className="generate-code-error">
          <Problem error={error} />
        </div>
      )}
    </div>
  );
}
