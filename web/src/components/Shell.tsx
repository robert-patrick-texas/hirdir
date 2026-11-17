import { type FormEvent, Suspense, useEffect, useId, useRef, useState } from "react";
import {
  Link,
  NavigationType,
  NavLink,
  Outlet,
  useLocation,
  useNavigate,
  useNavigationType,
} from "react-router";
import { useAuth } from "../auth";
import { itemsPath } from "../lib/filter";
import { useSite } from "../lib/product";
import { allows, roleLabel } from "../lib/roles";
import { RenewalAlert } from "./RenewalAlert";

/**
 * 0.9.5: Find an item, in the menu bar of every page (P-187). What is typed opens the
 * list of items with those words, minor items among them: the list takes words as it
 * takes them in its own filter box, and a condition of the short form as a condition.
 */
function FindItem() {
  const navigate = useNavigate();
  const [typed, setTyped] = useState("");
  const id = useId();

  function find(event: FormEvent) {
    event.preventDefault();
    const words = typed.trim();
    if (words === "") return;
    setTyped("");
    navigate(itemsPath(words));
  }

  return (
    // The search landmark, as `<search>` is: a form of role search, in the element made
    // for it.
    <search aria-label="Find an item" className="find-item">
      <form onSubmit={find}>
        <label htmlFor={id} className="visually-hidden">
          Find an item
        </label>
        <input
          id={id}
          type="search"
          name="find"
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          placeholder="Find an item"
          autoComplete="off"
          enterKeyHint="search"
        />
        <button type="submit">Find</button>
      </form>
    </search>
  );
}

/** The frame around every page: the product name, the navigation, and who is signed in. */
export function Shell() {
  const { user, signOut } = useAuth();
  const { productName } = useSite();
  const { pathname } = useLocation();
  const how = useNavigationType();
  const main = useRef<HTMLElement>(null);
  const shown = useRef(pathname);

  // After moving to another page, start reading at its content, with the page at its
  // top and the menu bar in view (P-167). Focus alone would scroll the content to the
  // top of the window, past the menu bar, on every page taller than the window. Back
  // and Forward leave the window where the browser puts it.
  useEffect(() => {
    if (shown.current === pathname) return;
    shown.current = pathname;
    if (how !== NavigationType.Pop) window.scrollTo(0, 0);
    main.current?.focus({ preventScroll: true });
  }, [pathname, how]);

  return (
    <>
      <button type="button" className="skip" onClick={() => main.current?.focus()}>
        Skip to content
      </button>
      <header className="top">
        {/* 0.9.2: the name the site gives the product (P-168). */}
        <Link className="brand" to="/" data-testid="brand">
          {productName}
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
                  <NavLink to="/groups">Groups</NavLink>
                </li>
                {/* 0.8.0: circuits, and their groups under them (P-154). */}
                <li>
                  <NavLink
                    to="/circuits"
                    className={({ isActive }) =>
                      isActive || pathname.startsWith("/circuit-groups") ? "active" : ""
                    }
                  >
                    Circuits
                  </NavLink>
                </li>
                <li>
                  <NavLink to="/addresses">Addresses</NavLink>
                </li>
                <li>
                  <NavLink to="/geography">Geography</NavLink>
                </li>
                <li>
                  <NavLink to="/catalog">Catalog</NavLink>
                </li>
                <li>
                  <NavLink to="/vendors">Vendors</NavLink>
                </li>
                <li>
                  <NavLink to="/contacts">Contacts</NavLink>
                </li>
                <li>
                  <NavLink to="/operators">Operators</NavLink>
                </li>
                <li>
                  <NavLink to="/owners">Owners</NavLink>
                </li>
                <li>
                  <NavLink
                    to="/contracts"
                    className={({ isActive }) =>
                      isActive || pathname.startsWith("/agreements") ? "active" : ""
                    }
                  >
                    Contracts
                  </NavLink>
                </li>
                <li>
                  <NavLink to="/purchases">Purchases</NavLink>
                </li>
                <li>
                  <NavLink to="/systems">External systems</NavLink>
                </li>
                <li>
                  <NavLink to="/capacity">Capacity</NavLink>
                </li>
                <li>
                  <NavLink to="/reports">Reports</NavLink>
                </li>
                <li>
                  <NavLink to="/import">Import</NavLink>
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
        {allows(user.role, "viewer") && <FindItem />}
      </header>
      {/* The renewal alert of 0.7.0 (D-179), under the header of every page. */}
      <RenewalAlert />
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
        {/* 0.9.0: every reference, for every role to read (P-162). */}
        <li>
          <NavLink to="/admin/files">Files</NavLink>
        </li>
      </ul>
    </nav>
  );
}
