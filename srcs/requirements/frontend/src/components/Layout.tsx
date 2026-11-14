import { useEffect, useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../context/AuthContext";
import { GeoContext, useGeolocation } from "../hooks/useGeolocation";
import { MapLayers, UserPosition } from "./map";
import { FloatingButton } from "./ui";

export const MENU = [
  { to: "/", emoji: "🏠", label: "Accueil" },
  { to: "/tours/new/free", emoji: "🧭", label: "Tournée libre" },
  { to: "/tours/new/predefined", emoji: "📋", label: "Tournée préparée" },
  { to: "/nearby", emoji: "📍", label: "Adresses alentours" },
  { to: "/manual", emoji: "✍️", label: "Marquer une adresse" },
  { to: "/stats", emoji: "📊", label: "Mes statistiques" },
];

/** Signed-in shell: shared geolocation, user dot on the map, floating top bar and side menu. */
export default function Layout() {
  const geo = useGeolocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const { pathname, key } = useLocation();
  const navigate = useNavigate();
  const isHome = pathname === "/";

  useEffect(() => setMenuOpen(false), [pathname]);

  return (
    <GeoContext.Provider value={geo}>
      <MapLayers>
        <UserPosition position={geo.position} />
      </MapLayers>

      <div className="pointer-events-none absolute inset-x-0 top-0 z-[1100] flex items-center gap-2 px-3 pt-[max(0.75rem,env(safe-area-inset-top))]">
        {isHome ? (
          <FloatingButton aria-label="Menu" onClick={() => setMenuOpen(true)}>
            <MenuIcon />
          </FloatingButton>
        ) : (
          <FloatingButton aria-label="Retour" onClick={() => (key === "default" ? navigate("/") : navigate(-1))}>
            <svg viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M15 18l-6-6 6-6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </FloatingButton>
        )}
        {!isHome && (
          <FloatingButton aria-label="Menu" className="ml-auto" onClick={() => setMenuOpen(true)}>
            <MenuIcon />
          </FloatingButton>
        )}
      </div>

      <Outlet />

      {menuOpen && <Drawer onClose={() => setMenuOpen(false)} />}
    </GeoContext.Provider>
  );
}

function MenuIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2.2">
      <path d="M4 7h16M4 12h16M4 17h16" strokeLinecap="round" />
    </svg>
  );
}

function Drawer({ onClose }: { onClose: () => void }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();

  return (
    <div className="fixed inset-0 z-[1200] flex" role="dialog" aria-modal>
      <nav className="flex h-full w-80 max-w-[85vw] animate-[slide-in_.2s_ease-out] flex-col bg-white shadow-2xl">
        <div className="bg-brand-600 px-5 pt-[max(1.25rem,env(safe-area-inset-top))] pb-5 text-white">
          <p className="text-2xl" aria-hidden>
            🚪
          </p>
          <p className="mt-1 text-lg font-bold">{user?.first_name || user?.username}</p>
          {user?.scope && <p className="text-sm opacity-90">{user.scope.name}</p>}
        </div>
        <ul className="flex-1 overflow-y-auto py-2">
          {MENU.map((item) => (
            <li key={item.to}>
              <Link
                to={item.to}
                onClick={onClose}
                className={`flex items-center gap-4 px-5 py-3.5 text-[15px] font-medium ${
                  pathname === item.to ? "bg-brand-50 text-brand-700" : "text-slate-800 active:bg-slate-100"
                }`}
              >
                <span className="w-6 text-center text-xl">{item.emoji}</span>
                {item.label}
              </Link>
            </li>
          ))}
          {user?.is_staff && (
            <li>
              <a href="/admin/" className="flex items-center gap-4 px-5 py-3.5 text-[15px] font-medium text-slate-800 active:bg-slate-100">
                <span className="w-6 text-center text-xl">⚙️</span>
                Administration
              </a>
            </li>
          )}
        </ul>
        <button
          onClick={() => logout().then(() => navigate("/login"))}
          className="flex items-center gap-4 border-t border-slate-100 px-5 pt-4 pb-[max(1rem,env(safe-area-inset-bottom))] text-left text-[15px] font-medium text-slate-600"
        >
          <span className="w-6 text-center text-xl">👋</span>
          Déconnexion
        </button>
      </nav>
      <button className="flex-1 animate-[fade-in_.2s_ease-out] bg-black/40" aria-label="Fermer le menu" onClick={onClose} />
    </div>
  );
}
