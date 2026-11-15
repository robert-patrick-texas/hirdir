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
  agreements: () => import("./pages/Agreements"),
  audit: () => import("./pages/Audit"),
  capacity: () => import("./pages/Capacity"),
  catalog: () => import("./pages/Catalog"),
  choices: () => import("./pages/Choices"),
  contacts: () => import("./pages/Contacts"),
  contracts: () => import("./pages/Contracts"),
  deviceGroups: () => import("./pages/DeviceGroups"),
  geography: () => import("./pages/Geography"),
  groups: () => import("./pages/Groups"),
  import: () => import("./pages/Import"),
  itemDetail: () => import("./pages/ItemDetail"),
  items: () => import("./pages/Items"),
  lifecycleReports: () => import("./pages/LifecycleReports"),
  lifecycleRules: () => import("./pages/LifecycleRules"),
  networks: () => import("./pages/Networks"),
  operators: () => import("./pages/Operators"),
  owners: () => import("./pages/Owners"),
  purchases: () => import("./pages/Purchases"),
  // 0.7.0: the renewal worklist (P-127).
  renewals: () => import("./pages/Renewals"),
  reports: () => import("./pages/Reports"),
  roles: () => import("./pages/Roles"),
  scoreboard: () => import("./pages/Scoreboard"),
  settings: () => import("./pages/Settings"),
  systems: () => import("./pages/Systems"),
  tags: () => import("./pages/Tags"),
  userDetail: () => import("./pages/UserDetail"),
  users: () => import("./pages/Users"),
  vendors: () => import("./pages/Vendors"),
};

const AgreementDetail = lazy(() =>
  pages.agreements().then((page) => ({ default: page.AgreementDetail })),
);
const Agreements = lazy(() => pages.agreements().then((page) => ({ default: page.Agreements })));
const AllAddresses = lazy(() => pages.networks().then((page) => ({ default: page.AllAddresses })));
const Capacity = lazy(() => pages.capacity().then((page) => ({ default: page.Capacity })));
const CapacityLineDetail = lazy(() =>
  pages.capacity().then((page) => ({ default: page.CapacityLineDetail })),
);
const ContractDetail = lazy(() =>
  pages.contracts().then((page) => ({ default: page.ContractDetail })),
);
const Contracts = lazy(() => pages.contracts().then((page) => ({ default: page.Contracts })));
const CoverageReport = lazy(() =>
  pages.lifecycleReports().then((page) => ({ default: page.CoverageReport })),
);
const EndOfLifeReport = lazy(() =>
  pages.lifecycleReports().then((page) => ({ default: page.EndOfLifeReport })),
);
const PurchaseDetail = lazy(() =>
  pages.purchases().then((page) => ({ default: page.PurchaseDetail })),
);
const PurchaseLines = lazy(() =>
  pages.purchases().then((page) => ({ default: page.PurchaseLines })),
);
const Purchases = lazy(() => pages.purchases().then((page) => ({ default: page.Purchases })));
// 0.7.0: the renewal worklist, under Contracts (P-127).
const Renewals = lazy(() => pages.renewals().then((page) => ({ default: page.Renewals })));
const Replacements = lazy(() =>
  pages.lifecycleReports().then((page) => ({ default: page.Replacements })),
);
const SystemDetail = lazy(() => pages.systems().then((page) => ({ default: page.SystemDetail })));
const Systems = lazy(() => pages.systems().then((page) => ({ default: page.Systems })));
const Audit = lazy(() => pages.audit().then((page) => ({ default: page.Audit })));
const Catalog = lazy(() => pages.catalog().then((page) => ({ default: page.Catalog })));
const CatalogEntryDetail = lazy(() =>
  pages.catalog().then((page) => ({ default: page.CatalogEntryDetail })),
);
const Choices = lazy(() => pages.choices().then((page) => ({ default: page.Choices })));
const ContactDetail = lazy(() =>
  pages.contacts().then((page) => ({ default: page.ContactDetail })),
);
const Contacts = lazy(() => pages.contacts().then((page) => ({ default: page.Contacts })));
const DeviceGroupDetail = lazy(() =>
  pages.deviceGroups().then((page) => ({ default: page.DeviceGroupDetail })),
);
const DeviceGroups = lazy(() =>
  pages.deviceGroups().then((page) => ({ default: page.DeviceGroups })),
);
const Geography = lazy(() => pages.geography().then((page) => ({ default: page.Geography })));
const Duplicates = lazy(() => pages.reports().then((page) => ({ default: page.Duplicates })));
const GroupDetail = lazy(() => pages.groups().then((page) => ({ default: page.GroupDetail })));
const Groups = lazy(() => pages.groups().then((page) => ({ default: page.Groups })));
const Import = lazy(() => pages.import().then((page) => ({ default: page.Import })));
const ItemDetail = lazy(() => pages.itemDetail().then((page) => ({ default: page.ItemDetail })));
const Items = lazy(() => pages.items().then((page) => ({ default: page.Items })));
const LifecycleRules = lazy(() =>
  pages.lifecycleRules().then((page) => ({ default: page.LifecycleRules })),
);
const ManagementReport = lazy(() =>
  pages.reports().then((page) => ({ default: page.ManagementReport })),
);
const Networks = lazy(() => pages.networks().then((page) => ({ default: page.Networks })));
const OperatorDetail = lazy(() =>
  pages.operators().then((page) => ({ default: page.OperatorDetail })),
);
const Operators = lazy(() => pages.operators().then((page) => ({ default: page.Operators })));
const OwnerDetail = lazy(() => pages.owners().then((page) => ({ default: page.OwnerDetail })));
const Owners = lazy(() => pages.owners().then((page) => ({ default: page.Owners })));
const Scoreboard = lazy(() => pages.scoreboard().then((page) => ({ default: page.Scoreboard })));
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
              path="geography/:level?/:hid?"
              element={
                <RequireRole needs="viewer">
                  <Geography />
                </RequireRole>
              }
            />
            <Route
              path="contacts"
              element={
                <RequireRole needs="viewer">
                  <Contacts />
                </RequireRole>
              }
            />
            <Route
              path="contacts/:hid"
              element={
                <RequireRole needs="viewer">
                  <ContactDetail />
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
              path="reports/scoreboard"
              element={
                <RequireRole needs="viewer">
                  <Scoreboard />
                </RequireRole>
              }
            />
            <Route
              path="reports/management"
              element={
                <RequireRole needs="viewer">
                  <ManagementReport />
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
              path="reports/coverage"
              element={
                <RequireRole needs="viewer">
                  <CoverageReport />
                </RequireRole>
              }
            />
            <Route
              path="reports/end-of-life"
              element={
                <RequireRole needs="viewer">
                  <EndOfLifeReport />
                </RequireRole>
              }
            />
            <Route
              path="reports/replacements"
              element={
                <RequireRole needs="viewer">
                  <Replacements />
                </RequireRole>
              }
            />
            <Route
              path="contracts"
              element={
                <RequireRole needs="viewer">
                  <Contracts />
                </RequireRole>
              }
            />
            {/* 0.7.0: the renewal worklist, under Contracts (P-127). */}
            <Route
              path="contracts/renewals"
              element={
                <RequireRole needs="viewer">
                  <Renewals />
                </RequireRole>
              }
            />
            <Route
              path="contracts/:hid"
              element={
                <RequireRole needs="viewer">
                  <ContractDetail />
                </RequireRole>
              }
            />
            <Route
              path="agreements"
              element={
                <RequireRole needs="viewer">
                  <Agreements />
                </RequireRole>
              }
            />
            <Route
              path="agreements/:hid"
              element={
                <RequireRole needs="viewer">
                  <AgreementDetail />
                </RequireRole>
              }
            />
            <Route
              path="purchases"
              element={
                <RequireRole needs="viewer">
                  <Purchases />
                </RequireRole>
              }
            />
            <Route
              path="purchases/lines"
              element={
                <RequireRole needs="viewer">
                  <PurchaseLines />
                </RequireRole>
              }
            />
            <Route
              path="purchases/:hid"
              element={
                <RequireRole needs="viewer">
                  <PurchaseDetail />
                </RequireRole>
              }
            />
            <Route
              path="systems"
              element={
                <RequireRole needs="viewer">
                  <Systems />
                </RequireRole>
              }
            />
            <Route
              path="systems/:hid"
              element={
                <RequireRole needs="viewer">
                  <SystemDetail />
                </RequireRole>
              }
            />
            <Route
              path="capacity"
              element={
                <RequireRole needs="viewer">
                  <Capacity />
                </RequireRole>
              }
            />
            <Route
              path="capacity/:hid"
              element={
                <RequireRole needs="viewer">
                  <CapacityLineDetail />
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
              path="operators"
              element={
                <RequireRole needs="viewer">
                  <Operators />
                </RequireRole>
              }
            />
            <Route
              path="operators/:hid"
              element={
                <RequireRole needs="viewer">
                  <OperatorDetail />
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
