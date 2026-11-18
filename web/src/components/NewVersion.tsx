// 0.9.7: a page older than the server says that a new version is installed (P-231).

import { useEffect, useRef, useSyncExternalStore } from "react";
import { useLocation } from "react-router";
import { api, sessions } from "../api";
import { useSite } from "../lib/product";
import { BUILT_AS, VersionStore } from "../lib/version";

/** What this page knows of the version the server runs. */
export const versionStore = new VersionStore(BUILT_AS, {
  ask: () => api.request("get", "/api/v1/about"),
  signedIn: () => sessions.get() !== null,
  now: () => Date.now(),
});

/**
 * Ask the server what runs on coming back to the tab, and at a change of page where the
 * last question is more than five minutes old. Part of the frame, so only while signed in.
 */
export function VersionWatch() {
  const { pathname } = useLocation();

  useEffect(() => {
    const back = () => {
      if (document.visibilityState === "visible") void versionStore.check();
    };
    document.addEventListener("visibilitychange", back);
    return () => document.removeEventListener("visibilitychange", back);
  }, []);

  const shown = useRef(pathname);
  useEffect(() => {
    if (shown.current === pathname) return;
    shown.current = pathname;
    versionStore.checkIfDue();
  }, [pathname]);

  return null;
}

/**
 * The notice that a new version has been installed. It stands in the frame of every page
 * until the page is loaded again, is no dialog and takes no focus; the page never loads
 * again by itself, so that nothing typed into a form is lost.
 */
export function NewVersionNotice() {
  const running = useSyncExternalStore(versionStore.subscribe, versionStore.get);
  const { productName } = useSite();
  if (running === null) return null;
  return (
    <div className="new-version" role="status" data-testid="new-version">
      <p>
        A new version of {productName} has been installed: {running}, where this page is {BUILT_AS}.
        Load the page again to use it, once what you are typing is saved.
      </p>
      <button type="button" onClick={() => window.location.reload()}>
        Load again
      </button>
    </div>
  );
}
