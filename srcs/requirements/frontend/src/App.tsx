import { Navigate, Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import { MapShell } from "./components/map";
import { OverlaySpinner } from "./components/ui";
import type { User } from "./api/types";
import { useAuth } from "./context/AuthContext";
import Account from "./pages/Account";
import Districts from "./pages/Districts";
import FreeTour from "./pages/FreeTour";
import Home from "./pages/Home";
import Login from "./pages/Login";
import Members from "./pages/Members";
import Nearby from "./pages/Nearby";
import Organizations from "./pages/Organizations";
import OrganizationSettings from "./pages/OrganizationSettings";
import Pending, { AskName } from "./pages/Pending";
import Ranking from "./pages/Ranking";
import PredefinedTour from "./pages/PredefinedTour";
import SiteAdmin from "./pages/SiteAdmin";
import Stats from "./pages/Stats";
import TourPage from "./pages/TourPage";
import VerifyEmail from "./pages/VerifyEmail";
import VerifyLink from "./pages/VerifyLink";
import VoterLists, { VoterListDetail } from "./pages/VoterLists";

function RequireCanvasser({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (!user.first_name) return <AskName />;
  // Site admins get in even without a current organization (to create / pick one).
  if (!user.can_canvass && !user.is_site_admin) return <Pending />;
  return <>{children}</>;
}

function RequireRight({ allowed, children }: { allowed: (user: User) => boolean; children: React.ReactNode }) {
  const { user } = useAuth();
  return user && allowed(user) ? <>{children}</> : <Navigate to="/" replace />;
}

/** Responsables (and site admins inside an organization): zones. */
function RequireManager({ children }: { children: React.ReactNode }) {
  return <RequireRight allowed={(u) => Boolean(u.organization && (u.can_manage_organization || u.is_site_admin))}>{children}</RequireRight>;
}

/** The map is always on screen; every route is an overlay on top of it. */
export default function App() {
  const { user, loading } = useAuth();

  return (
    <MapShell>
      {loading ? (
        <OverlaySpinner />
      ) : (
        <Routes>
          <Route path="/login" element={user ? <Navigate to="/" replace /> : <Login />} />
          <Route path="/login/verify" element={<VerifyLink />} />
          <Route path="/account/verify-email" element={<VerifyEmail />} />
          <Route path="/register" element={<Navigate to="/login" replace />} />
          <Route
            element={
              <RequireCanvasser>
                <Layout />
              </RequireCanvasser>
            }
          >
            <Route index element={<Home />} />
            <Route path="tours/new" element={<Navigate to="/" replace />} />
            <Route path="tours/new/free" element={<FreeTour />} />
            <Route path="tours/new/predefined" element={<PredefinedTour />} />
            <Route path="tours/:id" element={<TourPage />} />
            <Route path="nearby" element={<Nearby />} />
            <Route path="stats" element={<Stats />} />
            <Route path="ranking" element={<Ranking />} />
            <Route path="account" element={<Account />} />
            <Route path="areas" element={<RequireManager><Districts /></RequireManager>} />
            <Route
              path="members"
              element={
                <RequireRight allowed={(u) => u.can_validate || u.is_site_admin}>
                  <Members />
                </RequireRight>
              }
            />
            <Route
              path="organization"
              element={
                <RequireRight allowed={(u) => u.can_manage_organization || u.is_site_admin}>
                  <OrganizationSettings />
                </RequireRight>
              }
            />
            <Route
              path="organizations"
              element={
                <RequireRight allowed={(u) => u.is_site_admin}>
                  <Organizations />
                </RequireRight>
              }
            />
            <Route
              path="organizations/:code"
              element={
                <RequireRight allowed={(u) => u.is_site_admin}>
                  <OrganizationSettings />
                </RequireRight>
              }
            />
            <Route
              path="lec"
              element={
                <RequireRight allowed={(u) => u.is_site_admin}>
                  <VoterLists />
                </RequireRight>
              }
            />
            <Route
              path="lec/:id"
              element={
                <RequireRight allowed={(u) => u.is_site_admin}>
                  <VoterListDetail />
                </RequireRight>
              }
            />
            <Route
              path="site-admin"
              element={
                <RequireRight allowed={(u) => u.is_site_admin}>
                  <SiteAdmin />
                </RequireRight>
              }
            />
            <Route
              path="organizations/:code/members"
              element={
                <RequireRight allowed={(u) => u.is_site_admin}>
                  <Members />
                </RequireRight>
              }
            />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      )}
    </MapShell>
  );
}
