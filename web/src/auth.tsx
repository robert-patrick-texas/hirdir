// Who is signed in. Nothing below AuthGate is shown without a session.

import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
} from "react";
import { useNavigate } from "react-router";
import { type ApiError, api, type Schemas, sessions } from "./api";
import { Problem } from "./components/Problem";
import { toApiError } from "./lib/hooks";
import { SignIn } from "./pages/SignIn";

type User = Schemas["UserOut"];

export interface Auth {
  /** The signed-in user, with the role they hold now. */
  user: User;
  /** Forget the session in this browser. */
  signOut: () => void;
  /** End every session of the signed-in user on the server, this one included. */
  signOutEverywhere: () => Promise<void>;
  /** Read the user again, as after a change to roles or groups. */
  refresh: () => void;
}

const AuthContext = createContext<Auth | null>(null);

export function useAuth(): Auth {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error("useAuth is used outside AuthGate");
  return auth;
}

// Timers cannot wait longer than this many milliseconds.
const LONGEST_TIMER = 2 ** 31 - 1;

export function AuthGate({ children }: { children: ReactNode }) {
  const session = useSyncExternalStore(sessions.subscribe, sessions.get);
  const token = session?.token ?? null;
  const expiresAt = session?.expires_at ?? null;
  const navigate = useNavigate();
  const [known, setKnown] = useState<{ token: string; user: User } | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [turn, setTurn] = useState(0);
  const wanted = useMemo(() => ({ token, turn }), [token, turn]);

  // A session past its expiry is no session: show the sign-in page when the time comes.
  useEffect(() => {
    if (expiresAt === null) return;
    const wait = Math.max(0, Date.parse(expiresAt) - Date.now());
    const timer = window.setTimeout(() => sessions.clear("ended"), Math.min(wait, LONGEST_TIMER));
    return () => window.clearTimeout(timer);
  }, [expiresAt]);

  useEffect(() => {
    const { token } = wanted;
    setError(null);
    if (token === null) {
      setKnown(null);
      return;
    }
    const controller = new AbortController();
    api.request("get", "/api/v1/auth/me", { signal: controller.signal }).then(
      (user) => {
        if (!controller.signal.aborted) setKnown({ token, user });
      },
      (thrown: unknown) => {
        if (!controller.signal.aborted) setError(toApiError(thrown));
      },
    );
    return () => controller.abort();
  }, [wanted]);

  const signOut = useCallback(() => {
    // The next person to sign in here starts at the first page, not where this one was.
    navigate("/", { replace: true });
    sessions.clear("signed-out");
  }, [navigate]);

  const signOutEverywhere = useCallback(async () => {
    await api.request("post", "/api/v1/auth/sign-out-everywhere");
    signOut();
  }, [signOut]);

  const refresh = useCallback(() => setTurn((count) => count + 1), []);

  const user = known && known.token === token ? known.user : null;
  const auth = useMemo<Auth | null>(
    () => (user ? { user, signOut, signOutEverywhere, refresh } : null),
    [user, signOut, signOutEverywhere, refresh],
  );

  if (token === null) return <SignIn />;
  if (!auth) {
    return (
      <main className="center">
        <h1>hirdir</h1>
        {error && error.status !== 401 ? (
          <>
            <Problem error={error} />
            <p className="actions">
              <button type="button" onClick={refresh}>
                Try again
              </button>
              <button type="button" onClick={signOut}>
                Sign out
              </button>
            </p>
          </>
        ) : (
          <p role="status">Loading…</p>
        )}
      </main>
    );
  }
  return <AuthContext.Provider value={auth}>{children}</AuthContext.Provider>;
}
