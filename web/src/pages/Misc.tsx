import type { ReactNode } from "react";
import { Link } from "react-router";
import { useAuth } from "../auth";
import { useTitle } from "../lib/hooks";
import { allows, type Role, roleLabel } from "../lib/roles";

/** Show a page only to those whose role allows it. The server checks again on every request. */
export function RequireRole({ needs, children }: { needs: Role; children: ReactNode }) {
  const { user } = useAuth();
  if (allows(user.role, needs)) return children;
  return <NotAllowed needed={needs} />;
}

function NotAllowed({ needed }: { needed: Role }) {
  useTitle("Not allowed");
  return (
    <>
      <h1>Not allowed</h1>
      <p>
        This page needs the {roleLabel(needed)} role. Ask an administrator of hirdir if you should
        have it.
      </p>
      <p>
        <Link to="/">Go to the first page</Link>
      </p>
    </>
  );
}

export function NotFound() {
  useTitle("Not found");
  return (
    <>
      <h1>Not found</h1>
      <p>There is no page at this address.</p>
      <p>
        <Link to="/">Go to the first page</Link>
      </p>
    </>
  );
}
