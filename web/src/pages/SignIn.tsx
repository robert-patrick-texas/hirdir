import { type FormEvent, useEffect, useRef, useState } from "react";
import { type ApiError, api, sessions } from "../api";
import { TextField } from "../components/Field";
import { Problem } from "../components/Problem";
import { toApiError, useTitle } from "../lib/hooks";

/** The only page shown without a session. */
export function SignIn() {
  useTitle("Sign in");
  const [username, setUsername] = useState("");
  const [accessCode, setAccessCode] = useState("");
  const [waitUntil, setWaitUntil] = useState(0);
  const [waiting, setWaiting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const first = useRef<HTMLInputElement>(null);
  const ended = sessions.endReason;

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
      if (problem.status === 429 && problem.retryAfter !== null) {
        setWaitUntil(Date.now() + problem.retryAfter * 1000);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="center">
      <h1>Sign in to hirdir</h1>
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
      <form onSubmit={submit} className="stack">
        <Problem error={error} shown={["username", "access_code"]} />
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
    </main>
  );
}
