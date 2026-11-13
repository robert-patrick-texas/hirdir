import { BrowserRouter, Route, Routes } from "react-router";
import { AuthGate } from "./auth";
import { Shell } from "./components/Shell";
import { routerBasename } from "./lib/base";
import { About } from "./pages/About";
import { Audit } from "./pages/Audit";
import { Catalog, CatalogEntryDetail } from "./pages/Catalog";
import { Choices } from "./pages/Choices";
import { GroupDetail, Groups } from "./pages/Groups";
import { Home } from "./pages/Home";
import { ItemDetail } from "./pages/ItemDetail";
import { Items } from "./pages/Items";
import { LifecycleRules } from "./pages/LifecycleRules";
import { AdminStart, NotFound, RequireRole } from "./pages/Misc";
import { OwnerDetail, Owners } from "./pages/Owners";
import { Roles } from "./pages/Roles";
import { Settings } from "./pages/Settings";
import { Tags } from "./pages/Tags";
import { UserDetail } from "./pages/UserDetail";
import { Users } from "./pages/Users";
import { VendorDetail, Vendors } from "./pages/Vendors";

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
            <Route
              path="items"
              element={
                <RequireRole needs="viewer">
                  <Items />
                </RequireRole>
              }
            />
            <Route
              path="items/:hid"
              element={
                <RequireRole needs="viewer">
                  <ItemDetail />
                </RequireRole>
              }
            />
            <Route
              path="catalog"
              element={
                <RequireRole needs="viewer">
                  <Catalog />
                </RequireRole>
              }
            />
            <Route
              path="catalog/:hid"
              element={
                <RequireRole needs="viewer">
                  <CatalogEntryDetail />
                </RequireRole>
              }
            />
            <Route
              path="vendors"
              element={
                <RequireRole needs="viewer">
                  <Vendors />
                </RequireRole>
              }
            />
            <Route
              path="vendors/:hid"
              element={
                <RequireRole needs="viewer">
                  <VendorDetail />
                </RequireRole>
              }
            />
            <Route
              path="owners"
              element={
                <RequireRole needs="viewer">
                  <Owners />
                </RequireRole>
              }
            />
            <Route
              path="owners/:hid"
              element={
                <RequireRole needs="viewer">
                  <OwnerDetail />
                </RequireRole>
              }
            />
            <Route
              path="admin"
              element={
                <RequireRole needs="viewer">
                  <AdminStart />
                </RequireRole>
              }
            />
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
            <Route
              path="admin/settings"
              element={
                <RequireRole needs="admin">
                  <Settings />
                </RequireRole>
              }
            />
            <Route
              path="admin/choices"
              element={
                <RequireRole needs="viewer">
                  <Choices />
                </RequireRole>
              }
            />
            <Route
              path="admin/lifecycle-rules"
              element={
                <RequireRole needs="viewer">
                  <LifecycleRules />
                </RequireRole>
              }
            />
            <Route
              path="admin/tags"
              element={
                <RequireRole needs="viewer">
                  <Tags />
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
