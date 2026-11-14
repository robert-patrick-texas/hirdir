import { NavLink } from "react-router";

/** The second row of navigation on the report pages. */
export function ReportsNav() {
  return (
    <nav className="sub" aria-label="Reports">
      <ul>
        <li>
          <NavLink to="/reports/scoreboard">Scoreboard</NavLink>
        </li>
        <li>
          <NavLink to="/reports" end>
            Summary
          </NavLink>
        </li>
        <li>
          <NavLink to="/reports/management">Management</NavLink>
        </li>
        <li>
          <NavLink to="/reports/duplicates">Addresses held more than once</NavLink>
        </li>
      </ul>
    </nav>
  );
}
