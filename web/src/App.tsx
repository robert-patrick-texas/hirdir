import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import { AuthGate } from "./auth";
import { Shell } from "./components/Shell";
import { routerBasename } from "./lib/base";
import { About } from "./pages/About";
import { Audit } from "./pages/Audit";
import { GroupDetail, Groups } from "./pages/Groups";
import { Home } from "./pages/Home";
import { NotFound, RequireRole } from "./pages/Misc";
import { Roles } from "./pages/Roles";
import { UserDetail } from "./pages/UserDetail";
import { Users } from "./pages/Users";

/**
 * The whole page. The router's base is the URL prefix the server wrote into the <base>
 * tag, so the same build works at `/` and under any prefix.
 */
export function App() {
  return (
    <BrowserRouter basename={routerBasename(document.baseURI)}>
      <AuthGate>
        <Routes>
          <Route element={<Shell />}>
            <Route index element={<Home />} />
            <Route
              path="audit"
              element={
                <RequireRole needs="viewer">
                  <Audit />
                </RequireRole>
              }
            />
            <Route path="admin" element={<Navigate to="/admin/users" replace />} />
            <Route
              path="admin/users"
              element={
                <RequireRole needs="admin">
                  <Users />
                </RequireRole>
              }
            />
            <Route
              path="admin/users/:hid"
              element={
                <RequireRole needs="admin">
                  <UserDetail />
                </RequireRole>
              }
            />
            <Route
              path="admin/groups"
              element={
                <RequireRole needs="admin">
                  <Groups />
                </RequireRole>
              }
            />
            <Route
              path="admin/groups/:hid"
              element={
                <RequireRole needs="admin">
                  <GroupDetail />
                </RequireRole>
              }
            />
            <Route
              path="admin/roles"
              element={
                <RequireRole needs="admin">
                  <Roles />
                </RequireRole>
              }
            />
            <Route path="about" element={<About />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </AuthGate>
    </BrowserRouter>
  );
}
