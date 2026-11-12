import { api } from "../api";
import { Problem } from "../components/Problem";
import { useLoad, useTitle } from "../lib/hooks";

/** What is running. */
export function About() {
  useTitle("About");
  const about = useLoad("about", (signal) => api.request("get", "/api/v1/about", { signal }));
  return (
    <>
      <h1>About</h1>
      <Problem error={about.error} />
      {about.loading && !about.data && <p role="status">Loading…</p>}
      {about.data && (
        <dl className="facts">
          <dt>Product</dt>
          <dd>{about.data.name}</dd>
          <dt>Version</dt>
          <dd>{about.data.version}</dd>
          <dt>Python</dt>
          <dd>{about.data.python}</dd>
          <dt>SQLite</dt>
          <dd>{about.data.sqlite}</dd>
          <dt>Schema revision</dt>
          <dd>{about.data.schema_revision ?? <span className="muted">none</span>}</dd>
        </dl>
      )}
    </>
  );
}
