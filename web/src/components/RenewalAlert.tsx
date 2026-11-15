// The renewal alert: a banner under the header of every page, after signing in, while
// the server says to show it. It says how many contracts have lapsed, have a renewal
// pending, of which overdue, and end within the warning period, each leading to its
// list of the worklist. It is shown while the server says so, which is once a day to each
// person: dismissed, it is not shown again that day, and what was dismissed is kept on
// the server, so another browser does not show it again. A View-only person is never
// shown it, and is not asked for it.

import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router";
import { api } from "../api";
import { useAuth } from "../auth";
import { useReloadOn } from "../lib/hooks";
import {
  type RenewalAlert as Alert,
  alertLines,
  alertShown,
  asksForAlert,
  freshText,
  renewalsPath,
} from "../lib/renewals";

export function RenewalAlert() {
  const { user } = useAuth();
  const { pathname } = useLocation();
  const asks = asksForAlert(user.role);
  const [alert, setAlert] = useState<Alert | undefined>(undefined);
  // Dismissed: hidden at once, until the server answers again whether to show it.
  const [dismissed, setDismissed] = useState(false);
  const [busy, setBusy] = useState(false);
  const reading = useRef<AbortController | null>(null);

  const read = useCallback(() => {
    reading.current?.abort();
    if (!asks) {
      setAlert(undefined);
      return;
    }
    const controller = new AbortController();
    reading.current = controller;
    api.request("get", "/api/v1/renewals/alert", { signal: controller.signal }).then(
      (answer) => {
        if (controller.signal.aborted) return;
        setAlert(answer);
        setDismissed(false);
      },
      () => {
        // The alert is no part of the page: one that cannot be read is not shown.
      },
    );
  }, [asks]);

  // Read after signing in, and again on every page: an answer that nothing could have
  // changed is given again by the server as it was kept.
  useEffect(() => {
    read();
    return () => reading.current?.abort();
  }, [read]);
  useReloadOn(pathname, read);

  // And again when the person comes back to the tab.
  useEffect(() => {
    if (!asks) return;
    const back = () => {
      if (document.visibilityState === "visible") read();
    };
    document.addEventListener("visibilitychange", back);
    return () => document.removeEventListener("visibilitychange", back);
  }, [asks, read]);

  if (!alert || !alertShown(alert, user.role) || dismissed) return null;
  const lines = alertLines(alert);
  if (lines.length === 0) return null;
  const shown = alert;

  async function dismiss() {
    setBusy(true);
    try {
      await api.request("post", "/api/v1/renewals/alert/seen", {
        body: { version: shown.version },
      });
      setDismissed(true);
      read();
    } catch {
      // Not kept: the banner stays as it was, to be dismissed again.
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className="renewal-alert"
      aria-label="Renewals to act on"
      data-testid="renewal-alert"
      data-version={shown.version}
    >
      <p className="renewal-alert-lead">
        <strong>Renewals to act on</strong>
        <span className="muted"> · as of {shown.as_of}</span>
      </p>
      <ul className="renewal-alert-counts">
        {lines.map((line) => (
          <li
            key={line.section}
            data-section={line.section}
            data-count={line.count}
            data-new={line.fresh}
          >
            <Link to={renewalsPath({ section: line.section })}>{line.text}</Link>
            {line.overdue && (
              <>
                {", "}
                <Link
                  to={renewalsPath({ section: "overdue" })}
                  data-section="overdue"
                  data-count={line.overdue.count}
                >
                  {line.overdue.text}
                </Link>
              </>
            )}
            {line.fresh > 0 && (
              <span className="badge" data-mark="new">
                {freshText(line.fresh)}
              </span>
            )}
          </li>
        ))}
      </ul>
      <p className="renewal-alert-actions">
        <button type="button" onClick={dismiss} disabled={busy}>
          Dismiss
        </button>
        <span className="hint">Dismissed, it is not shown again today.</span>
      </p>
    </section>
  );
}
