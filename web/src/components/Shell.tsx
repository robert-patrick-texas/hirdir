import { Suspense, useEffect, useRef } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";
import { useAuth } from "../auth";
import { allows, roleLabel } from "../lib/roles";

/** The frame around every page: the product name, the navigation, and who is signed in. */
export function Shell() {
  const { user, signOut } = useAuth();
  const { pathname } = useLocation();
  const main = useRef<HTMLElement>(null);
  const shown = useRef(pathname);

  // After moving to another page, start reading at its content.
  useEffect(() => {
    if (shown.current === pathname) return;
    shown.current = pathname;
    main.current?.focus();
  }, [pathname]);

  return (
    <>
      <button type="button" className="skip" onClick={() => main.current?.focus()}>
        Skip to content
      </button>
      <header className="top">
        <Link className="brand" to="/">
          hirdir
        </Link>
        <nav aria-label="Main">
          <ul>
            <li>
              <NavLink to="/" end>
                Home
              </NavLink>
            </li>
            {allows(user.role, "viewer") && (
              <>
                <li>
                  <NavLink to="/items">Items</NavLink>
                </li>
                <li>
                  <NavLink to="/catalog">Catalog</NavLink>
                </li>
                <li>
                  <NavLink to="/vendors">Vendors</NavLink>
                </li>
                <li>
                  <NavLink to="/owners">Owners</NavLink>
                </li>
                <li>
                  <NavLink to="/audit">Audit</NavLink>
                </li>
                <li>
                  <NavLink to="/admin">Admin</NavLink>
                </li>
              </>
            )}
            <li>
              <NavLink to="/about">About</NavLink>
            </li>
          </ul>
        </nav>
        <p className="who">
          <span className="who-name">{user.username}</span>
          <span className="who-role">{roleLabel(user.role)}</span>
        </p>
        <button type="button" onClick={signOut}>
          Sign out
        </button>
      </header>
      <main ref={main} tabIndex={-1}>
        {/* A page whose code is still on its way. It says so only if that takes a while. */}
        <Suspense
          fallback={
            <p role="status" className="muted loading-late">
              Loading…
            </p>
          }
        >
          <Outlet />
        </Suspense>
      </main>
    </>
  );
}

/**
 * The second row of navigation, on the Admin pages. Accounts and settings are for an
 * Admin. The lists that describe the inventory are there for everyone to read, and for
 * the roles that may change them to change.
 */
export function AdminNav() {
  const { user } = useAuth();
  const admin = allows(user.role, "admin");
  return (
    <nav className="sub" aria-label="Admin">
      <ul>
        {admin && (
          <>
            <li>
              <NavLink to="/admin/users">Users</NavLink>
            </li>
            <li>
              <NavLink to="/admin/groups">Groups</NavLink>
            </li>
            <li>
              <NavLink to="/admin/roles">Roles</NavLink>
            </li>
            <li>
              <NavLink to="/admin/settings">Settings</NavLink>
            </li>
          </>
        )}
        <li>
          <NavLink to="/admin/choices">Choices</NavLink>
        </li>
        <li>
          <NavLink to="/admin/lifecycle-rules">Lifecycle rules</NavLink>
        </li>
        <li>
          <NavLink to="/admin/tags">Tags</NavLink>
        </li>
      </ul>
    </nav>
  );
}
