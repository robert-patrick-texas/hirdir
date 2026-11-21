import { type FormEvent, useEffect, useRef, useState } from "react";
import { type ApiError, api, sessions } from "../api";
import { TextField } from "../components/Field";
import { Problem } from "../components/Problem";
import { HelpList } from "../components/WhomToAsk";
import { toApiError, useTitle } from "../lib/hooks";
import { sentence } from "../lib/problems";
import { useSite } from "../lib/product";

/** The only page shown without a session. */
export function SignIn() {
  useTitle("Sign in");
  // 0.9.2: the name the site gives the product, and whom to ask where an Admin shows that
  // here (P-168, P-169), as the page was served with them.
  const { productName, signInHelp } = useSite();
  const [username, setUsername] = useState("");
  const [accessCode, setAccessCode] = useState("");
  const [waitUntil, setWaitUntil] = useState(0);
  const [waiting, setWaiting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const first = useRef<HTMLInputElement>(null);
  const ended = sessions.endReason;
  // 0.9.15: an account that holds no role gave the right code, and is told so plainly,
  // with whom to ask, apart from the refusal of a wrong code (P-299).
  const noRole = error?.status === 403 ? error : null;

  // The page has just replaced whatever was there: put the reader in the form.
  useEffect(() => {
    first.current?.focus();
  }, []);

  // After too many attempts the server says how long to wait. Hold the button until then.
  useEffect(() => {
    const left = waitUntil - Date.now();
    if (left <= 0) {
      setWaiting(false);
      return;
    }
    setWaiting(true);
    const timer = window.setTimeout(() => setWaiting(false), left);
    return () => window.clearTimeout(timer);
  }, [waitUntil]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const answer = await api.request("post", "/api/v1/auth/sign-in", {
        body: { username: username.trim(), access_code: accessCode },
      });
      // Only the token and its expiry are kept.
      sessions.set(answer);
    } catch (thrown) {
      const problem = toApiError(thrown);
      setError(problem);
      // 0.9.15: the right code of an account that holds no role (P-299). Nothing is kept:
      // the code box is emptied, and the username stays as typed.
      if (problem.status === 403) setAccessCode("");
      if (problem.status === 429 && problem.retryAfter !== null) {
        setWaitUntil(Date.now() + problem.retryAfter * 1000);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="center">
      <h1>Sign in to {productName}</h1>
      {ended === "ended" && !error && (
        <p className="alert alert-info" role="status">
          Your session has ended. Sign in again to carry on where you were.
        </p>
      )}
      {ended === "signed-out" && !error && (
        <p className="alert alert-info" role="status">
          You have signed out.
        </p>
      )}
      {noRole && (
        // Announced as it comes, as the refusal of a wrong code is in its live region.
        <section
          className="alert alert-info"
          role="alert"
          aria-labelledby="no-role"
          data-testid="no-role"
        >
          <h2 id="no-role">This account holds no role</h2>
          <p>{sentence(noRole.detail || noRole.message)}</p>
          {/* The server's words name an Admin; where it names a team, it is listed. */}
          {noRole.help && (
            <>
              <p>Ask the team that runs {productName} to give it one:</p>
              <HelpList help={noRole.help} />
            </>
          )}
        </section>
      )}
      <form onSubmit={submit} className="stack">
        <Problem error={noRole ? null : error} shown={["username", "access_code"]} />
        <TextField
          label="Username"
          name="username"
          value={username}
          onChange={setUsername}
          required
          maxLength={64}
          autoComplete="username"
          inputRef={first}
          error={error?.fields.username}
        />
        <TextField
          label="Access code"
          name="access_code"
          type="password"
          value={accessCode}
          onChange={setAccessCode}
          required
          maxLength={200}
          autoComplete="current-password"
          error={error?.fields.access_code}
        />
        <p className="actions">
          <button type="submit" className="primary" disabled={busy || waiting}>
            Sign in
          </button>
        </p>
      </form>
      {/* Whom to ask is said once: in the refusal of an account with no role, while it shows. */}
      {signInHelp && !noRole && (
        <section aria-labelledby="sign-in-help" className="sign-in-help">
          <h2 id="sign-in-help">Whom to ask</h2>
          <p>If you cannot sign in, ask the team that runs {productName}:</p>
          <HelpList help={signInHelp} />
        </section>
      )}
    </main>
  );
}
