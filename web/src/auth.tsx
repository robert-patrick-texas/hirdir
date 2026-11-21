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
import { flushSync } from "react-dom";
import { useNavigate } from "react-router";
import { type ApiError, api, type Schemas, sessions } from "./api";
import { Problem } from "./components/Problem";
import { setZone } from "./lib/format";
import { toApiError } from "./lib/hooks";
import { site, siteOfAbout, useSite } from "./lib/product";
import { SignIn } from "./pages/SignIn";

// 0.9.14: the user as `GET /auth/me` answers it, with the contact and the operators that are
// the person's own and the version of each (P-294).
type User = Schemas["MeOut"];

export interface Auth {
  /** The signed-in user, with the role they hold now. */
  user: User;
  /** Forget the session in this browser. */
  signOut: () => void;
  /** End every session of the signed-in user on the server, this one included. */
  signOutEverywhere: () => Promise<void>;
  /** Read the user again, as after a change to roles or groups. */
  refresh: () => void;
  /**
   * 0.9.14: take the user as a route of the person's own has just answered it (P-294),
   * so that the frame and every page show the change at once, with nothing read again.
   */
  took: (user: User) => void;
  /**
   * 0.9.14: keep the session a change of the person's own access code answered, in place
   * of the one in hand, which that change ended (P-295). The page stays as it is: what is
   * on it is not drawn anew, as it is when somebody else signs in.
   */
  adopt: (answer: Schemas["SessionOut"]) => void;
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
  const { productName } = useSite();
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
    // Every time on every page is in the application's time zone, so it is known
    // before the first page is shown. Someone who may not read settings gets the default.
    const zone = api.request("get", "/api/v1/settings", { signal: controller.signal }).then(
      (settings) => settings.find((setting) => setting.key === "time_zone")?.value,
      () => undefined,
    );
    const me = api.request("get", "/api/v1/auth/me", { signal: controller.signal });
    // 0.9.2: the name the site gives the product, which an Admin may have changed since
    // the page was served (P-168). The page shows the name it was served with meanwhile.
    api.request("get", "/api/v1/about", { signal: controller.signal }).then(
      (about) => {
        if (!controller.signal.aborted) site.update(siteOfAbout(about));
      },
      () => undefined,
    );
    Promise.all([me, zone]).then(
      ([user, timeZone]) => {
        if (controller.signal.aborted) return;
        setZone(timeZone);
        setKnown({ token, user });
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

  const took = useCallback((user: User) => {
    const held = sessions.get()?.token ?? null;
    setKnown((was) => (was && was.token === held ? { token: was.token, user } : was));
  }, []);

  const adopt = useCallback((answer: Schemas["SessionOut"]) => {
    // The token and the user it is known for change in one drawing of the page: between
    // the two the gate would know nobody, and would take the page away.
    flushSync(() => {
      setKnown({ token: answer.token, user: answer.user });
      sessions.set(answer);
    });
  }, []);

  const user = known && known.token === token ? known.user : null;
  const auth = useMemo<Auth | null>(
    () => (user ? { user, signOut, signOutEverywhere, refresh, took, adopt } : null),
    [user, signOut, signOutEverywhere, refresh, took, adopt],
  );

  if (token === null) return <SignIn />;
  if (!auth) {
    return (
      <main className="center">
        <h1>{productName}</h1>
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
