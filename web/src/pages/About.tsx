import { useEffect } from "react";
import { Link } from "react-router";
import { api } from "../api";
import { useAuth } from "../auth";
import { Problem } from "../components/Problem";
import { HelpList } from "../components/WhomToAsk";
import { useLoad, useTitle } from "../lib/hooks";
import { helpOf, site, siteOfAbout } from "../lib/product";
import { allows } from "../lib/roles";

/**
 * What is running: the product, by the name the site gives it, and the software, which is
 * hirdir whatever the site calls it; and whom to ask, the team that runs it (P-168, P-169).
 */
export function About() {
  useTitle("About");
  const { user } = useAuth();
  const about = useLoad("about", (signal) => api.request("get", "/api/v1/about", { signal }));
  const data = about.data;

  // What was just read is the name in force: the menu bar and the title follow it.
  useEffect(() => {
    if (data) site.update(siteOfAbout(data));
  }, [data]);

  const help = data ? helpOf(data.help) : null;
  return (
    <>
      <h1>About</h1>
      <Problem error={about.error} />
      {about.loading && !data && <p role="status">Loading…</p>}
      {data && (
        <>
          <dl className="facts" data-testid="about">
            <dt>Product</dt>
            <dd data-testid="about-product">{data.product_name}</dd>
            <dt>Software</dt>
            <dd data-testid="about-software">
              {data.name} {data.version}
            </dd>
            <dt>Python</dt>
            <dd>{data.python}</dd>
            <dt>SQLite</dt>
            <dd>{data.sqlite}</dd>
            <dt>Schema revision</dt>
            <dd>{data.schema_revision ?? <span className="muted">none</span>}</dd>
          </dl>
          <section aria-labelledby="whom-to-ask">
            <h2 id="whom-to-ask">Whom to ask</h2>
            {help ? (
              <>
                <p>For help with {data.product_name}, ask:</p>
                <HelpList help={help} />
              </>
            ) : (
              <p data-testid="nobody-to-ask">
                Nobody has been named yet.
                {allows(user.role, "admin") && (
                  <>
                    {" "}
                    They are set in <Link to="/admin/settings">Admin › Settings</Link>:{" "}
                    <span className="mono">help_organization</span>,{" "}
                    <span className="mono">help_email</span>,{" "}
                    <span className="mono">help_phone</span> and{" "}
                    <span className="mono">help_url</span>.
                  </>
                )}
              </p>
            )}
          </section>
        </>
      )}
    </>
  );
}
