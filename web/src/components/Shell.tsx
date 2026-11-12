import { useEffect, useRef } from "react";
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
              <li>
                <NavLink to="/audit">Audit</NavLink>
              </li>
            )}
            {allows(user.role, "admin") && (
              <li>
                <NavLink to="/admin">Admin</NavLink>
              </li>
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
        <Outlet />
      </main>
    </>
  );
}

/** The second row of navigation, on the Admin pages. */
export function AdminNav() {
  return (
    <nav className="sub" aria-label="Admin">
      <ul>
        <li>
          <NavLink to="/admin/users">Users</NavLink>
        </li>
        <li>
          <NavLink to="/admin/groups">Groups</NavLink>
        </li>
        <li>
          <NavLink to="/admin/roles">Roles</NavLink>
        </li>
      </ul>
    </nav>
  );
}
