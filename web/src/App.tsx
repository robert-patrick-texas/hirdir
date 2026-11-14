import { lazy, useEffect } from "react";
import { BrowserRouter, Route, Routes } from "react-router";
import { AuthGate } from "./auth";
import { Shell } from "./components/Shell";
import { routerBasename } from "./lib/base";
import { About } from "./pages/About";
import { Home } from "./pages/Home";
import { AdminStart, NotFound, RequireRole } from "./pages/Misc";

// The sign-in page and the first page are in the file the browser loads first. Every
// other page is a file of its own, so that signing in never waits for the grid.
const pages = {
  audit: () => import("./pages/Audit"),
  catalog: () => import("./pages/Catalog"),
  choices: () => import("./pages/Choices"),
  deviceGroups: () => import("./pages/DeviceGroups"),
  groups: () => import("./pages/Groups"),
  import: () => import("./pages/Import"),
  itemDetail: () => import("./pages/ItemDetail"),
  items: () => import("./pages/Items"),
  lifecycleRules: () => import("./pages/LifecycleRules"),
  networks: () => import("./pages/Networks"),
  owners: () => import("./pages/Owners"),
  reports: () => import("./pages/Reports"),
  roles: () => import("./pages/Roles"),
  settings: () => import("./pages/Settings"),
  tags: () => import("./pages/Tags"),
  userDetail: () => import("./pages/UserDetail"),
  users: () => import("./pages/Users"),
  vendors: () => import("./pages/Vendors"),
};

const AllAddresses = lazy(() => pages.networks().then((page) => ({ default: page.AllAddresses })));
const Audit = lazy(() => pages.audit().then((page) => ({ default: page.Audit })));
const Catalog = lazy(() => pages.catalog().then((page) => ({ default: page.Catalog })));
const CatalogEntryDetail = lazy(() =>
  pages.catalog().then((page) => ({ default: page.CatalogEntryDetail })),
);
const Choices = lazy(() => pages.choices().then((page) => ({ default: page.Choices })));
const DeviceGroupDetail = lazy(() =>
  pages.deviceGroups().then((page) => ({ default: page.DeviceGroupDetail })),
);
const DeviceGroups = lazy(() =>
  pages.deviceGroups().then((page) => ({ default: page.DeviceGroups })),
);
const Duplicates = lazy(() => pages.reports().then((page) => ({ default: page.Duplicates })));
const GroupDetail = lazy(() => pages.groups().then((page) => ({ default: page.GroupDetail })));
const Groups = lazy(() => pages.groups().then((page) => ({ default: page.Groups })));
const Import = lazy(() => pages.import().then((page) => ({ default: page.Import })));
const ItemDetail = lazy(() => pages.itemDetail().then((page) => ({ default: page.ItemDetail })));
const Items = lazy(() => pages.items().then((page) => ({ default: page.Items })));
const LifecycleRules = lazy(() =>
  pages.lifecycleRules().then((page) => ({ default: page.LifecycleRules })),
);
const Networks = lazy(() => pages.networks().then((page) => ({ default: page.Networks })));
const OwnerDetail = lazy(() => pages.owners().then((page) => ({ default: page.OwnerDetail })));
const Owners = lazy(() => pages.owners().then((page) => ({ default: page.Owners })));
const Roles = lazy(() => pages.roles().then((page) => ({ default: page.Roles })));
const Summary = lazy(() => pages.reports().then((page) => ({ default: page.Summary })));
const Settings = lazy(() => pages.settings().then((page) => ({ default: page.Settings })));
const Tags = lazy(() => pages.tags().then((page) => ({ default: page.Tags })));
const UserDetail = lazy(() => pages.userDetail().then((page) => ({ default: page.UserDetail })));
const Users = lazy(() => pages.users().then((page) => ({ default: page.Users })));
const VendorDetail = lazy(() => pages.vendors().then((page) => ({ default: page.VendorDetail })));
const Vendors = lazy(() => pages.vendors().then((page) => ({ default: page.Vendors })));

// How long after the first page is shown the other pages are fetched, in milliseconds.
const WARM_AFTER = 400;

/**
 * Fetch every other page while the reader looks at the first one, so that opening the
 * grid, or anything else, does not wait for its code. A page that could not be fetched
 * ahead is fetched again when it is opened, and says so then if it still cannot be.
 */
function Warm() {
  useEffect(() => {
    const timer = window.setTimeout(() => {
      for (const load of Object.values(pages)) load().catch(() => undefined);
    }, WARM_AFTER);
    return () => window.clearTimeout(timer);
  }, []);
  return null;
}

/**
 * The whole page. The router's base is the URL prefix the server wrote into the <base>
 * tag, so the same build works at `/` and under any prefix.
 */
export function App() {
  return (
    <BrowserRouter basename={routerBasename(document.baseURI)}>
      <AuthGate>
        <Warm />
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
              path="groups"
              element={
                <RequireRole needs="viewer">
                  <DeviceGroups />
                </RequireRole>
              }
            />
            <Route
              path="groups/:hid"
              element={
                <RequireRole needs="viewer">
                  <DeviceGroupDetail />
                </RequireRole>
              }
            />
            <Route
              path="addresses"
              element={
                <RequireRole needs="viewer">
                  <AllAddresses />
                </RequireRole>
              }
            />
            <Route
              path="networks"
              element={
                <RequireRole needs="viewer">
                  <Networks />
                </RequireRole>
              }
            />
            <Route
              path="reports"
              element={
                <RequireRole needs="viewer">
                  <Summary />
                </RequireRole>
              }
            />
            <Route
              path="reports/duplicates"
              element={
                <RequireRole needs="viewer">
                  <Duplicates />
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
              path="import/:hid?"
              element={
                <RequireRole needs="viewer">
                  <Import />
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
