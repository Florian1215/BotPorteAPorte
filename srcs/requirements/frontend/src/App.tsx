import { Navigate, Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import { MapShell } from "./components/map";
import { OverlaySpinner } from "./components/ui";
import { useAuth } from "./context/AuthContext";
import FreeTour from "./pages/FreeTour";
import Home from "./pages/Home";
import Login from "./pages/Login";
import ManualMark from "./pages/ManualMark";
import Nearby from "./pages/Nearby";
import Pending from "./pages/Pending";
import PredefinedTour from "./pages/PredefinedTour";
import Register from "./pages/Register";
import Stats from "./pages/Stats";
import TourPage from "./pages/TourPage";

function RequireCanvasser({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (!user.can_canvass) return <Pending />;
  return <>{children}</>;
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
          <Route path="/register" element={user ? <Navigate to="/" replace /> : <Register />} />
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
            <Route path="manual" element={<ManualMark />} />
            <Route path="stats" element={<Stats />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      )}
    </MapShell>
  );
}
