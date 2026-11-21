import { Building2, ChevronRight, FileSpreadsheet, Globe, House, LandPlot, LogOut, type LucideIcon, Menu, Settings, ShieldCheck, Trophy, UserCheck, Users, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../context/AuthContext";
import { BackContext } from "../context/BackContext";
import { useMapUI } from "../context/MapContext";
import { GeoContext, lastKnownPosition, useGeolocation } from "../hooks/useGeolocation";
import { useIsDesktop } from "../hooks/useIsDesktop";
import { usePendingCount } from "../hooks/usePendingCount";
import { ROLE_LABEL } from "../lib/constants";
import { MapLayers, UserPosition } from "./map";
import { OrgLogo } from "./organization";
import { FloatingButton } from "./ui";

type MenuItem = { to: string; icon: LucideIcon; label: string; badge?: number; external?: boolean };

export const MENU: MenuItem[] = [
  { to: "/", icon: House, label: "Accueil" },
  { to: "/ranking", icon: Trophy, label: "Classement" },
];

/** Signed-in shell: shared geolocation, user dot on the map, floating top bar and side menu. */
export default function Layout() {
  const geo = useGeolocation();
  const { user } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const { pathname, key } = useLocation();
  const navigate = useNavigate();
  const isHome = pathname === "/";
  const pending = usePendingCount();
  const goBack = () => (key === "default" ? navigate("/") : navigate(-1));
  const desktop = useIsDesktop();

  useEffect(() => setMenuOpen(false), [pathname]);

  // Map background: the device position when available (pages fly to it), otherwise the organization's city.
  const { map } = useMapUI();
  const city = user?.organization?.city_lat != null && user.organization.city_lon != null
    ? ([user.organization.city_lat, user.organization.city_lon] as [number, number])
    : null;
  const cityKey = city?.join(",");
  const shownCity = useRef<string | null>(null);
  useEffect(() => {
    if (!map || !city || geo.status === "ok" || shownCity.current === cityKey) return;
    // At startup (no remembered position) or when geolocation is refused / unavailable.
    if (geo.status === "error" || !lastKnownPosition()) {
      shownCity.current = cityKey ?? null;
      map.setView(city, 13, { animate: false });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, cityKey, geo.status]);

  return (
    <GeoContext.Provider value={geo}>
      <MapLayers>
        <UserPosition position={geo.position} />
      </MapLayers>

      {/* Mobile: floating top bar + drawer. Large screens: permanent side menu instead. */}
      <div className="pointer-events-none absolute inset-x-0 top-0 z-[1100] flex items-center gap-2 px-3 pt-[max(0.75rem,env(safe-area-inset-top))] lg:hidden">
        <FloatingButton aria-label="Menu" onClick={() => setMenuOpen(true)} className="relative">
          <Menu className="size-[22px]" strokeWidth={2.25} />
          {pending > 0 && <span className="absolute top-2.5 right-2.5 size-2.5 rounded-full bg-brand-600 ring-2 ring-white" />}
        </FloatingButton>
        {user?.organization && (
          <div className="pointer-events-auto mx-auto flex h-12 min-w-0 items-center gap-2 rounded-full bg-white/90 py-1.5 pr-4 pl-1.5 shadow-float ring-1 ring-zinc-950/5 backdrop-blur-xl">
            <OrgLogo organization={user.organization} className="size-9 rounded-full text-sm" />
            <span className="truncate text-sm font-semibold tracking-tight">{user.organization.name}</span>
          </div>
        )}
        <span className="size-12 shrink-0" aria-hidden />
      </div>

      {/* Back button lives in the sheet header (next to the title), not in the top bar. */}
      {desktop && (
        <aside className="absolute inset-y-0 left-0 z-[1100] flex w-64 flex-col border-r border-zinc-950/5 bg-white shadow-float">
          <NavContent pending={pending} />
        </aside>
      )}

      <BackContext.Provider value={isHome ? null : goBack}>
        {/* --sidebar: the panels dock right of the side menu on large screens. */}
        <div className="contents lg:[--sidebar:16rem]">
          <Outlet />
        </div>
      </BackContext.Provider>

      {menuOpen && !desktop && <Drawer onClose={() => setMenuOpen(false)} pending={pending} />}
    </GeoContext.Provider>
  );
}

function Drawer({ onClose, pending }: { onClose: () => void; pending: number }) {
  return (
    <div className="fixed inset-0 z-[1200] flex" role="dialog" aria-modal>
      <nav className="flex h-full w-[19rem] max-w-[85vw] animate-[slide-in_.22s_cubic-bezier(.2,.8,.2,1)] flex-col bg-white shadow-2xl">
        <NavContent pending={pending} onClose={onClose} />
      </nav>
      <button className="flex-1 animate-[fade-in_.2s_ease-out] bg-zinc-950/40 backdrop-blur-[2px]" aria-label="Fermer le menu" onClick={onClose} />
    </div>
  );
}

/** Menu content: in the mobile drawer (with a close button) or the permanent side menu of large screens. */
function NavContent({ pending, onClose }: { pending: number; onClose?: () => void }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();

  const management = [
    user?.can_validate && !user.can_manage_organization && { to: "/members", icon: UserCheck, label: "Inscriptions à valider", badge: pending },
    user?.can_manage_organization && { to: "/members", icon: Users, label: "Membres", badge: pending },
    user?.can_manage_organization && { to: "/organization", icon: Building2, label: "Mon organisation" },
    user?.organization && (user.can_manage_organization || user.is_site_admin) && { to: "/areas", icon: LandPlot, label: "Zones" },
    user?.is_site_admin && { to: "/organizations", icon: Globe, label: "Toutes les organisations" },
    user?.is_site_admin && { to: "/lec", icon: FileSpreadsheet, label: "LEC" },
    user?.is_site_admin && { to: "/site-admin", icon: ShieldCheck, label: "Admin" },
    user?.is_staff && { to: "/admin/", icon: Settings, label: "Django", external: true },
  ].filter(Boolean) as MenuItem[];
  const items = user?.can_canvass ? MENU : [];
  const initials = (user?.first_name || user?.email || "?").trim().charAt(0).toUpperCase();

  return (
    <>
        <div className="px-4 pt-[max(1rem,env(safe-area-inset-top))] pb-3">
          <div className="flex items-center justify-between">
            <OrgLogo organization={user?.organization ?? null} className="size-11 text-lg" />
            {onClose && (
              <button onClick={onClose} aria-label="Fermer le menu" className="flex size-10 items-center justify-center rounded-full text-zinc-500 active:bg-zinc-100">
                <X className="size-5" />
              </button>
            )}
          </div>
          <p className="mt-3 truncate text-[15px] font-semibold tracking-tight">{user?.organization?.name ?? "Aucune organisation"}</p>
          <Link to="/account" onClick={onClose} className="mt-3 flex items-center gap-3 rounded-2xl bg-zinc-50 p-2.5 ring-1 ring-zinc-950/5 hover:bg-zinc-100 active:bg-zinc-100">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-zinc-900 text-sm font-semibold text-white">{initials}</span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold">{[user?.first_name, user?.last_name].filter(Boolean).join(" ") || user?.email}</p>
              {user && (
                <p className="truncate text-xs text-zinc-500">
                  {ROLE_LABEL[user.role]} · {user.email}
                </p>
              )}
            </div>
            <ChevronRight className="size-4 shrink-0 text-zinc-300" />
          </Link>
        </div>

        <ul className="flex-1 space-y-0.5 overflow-y-auto px-2 py-2">
          {items.map((item) => (
            <MenuLink key={item.to} item={item} active={pathname === item.to} onClick={onClose} />
          ))}
          {management.length > 0 && <li className="px-3 pt-5 pb-1.5 text-xs font-semibold text-zinc-400">Gestion</li>}
          {management.map((item) => (
            <MenuLink key={item.to + item.label} item={item} active={pathname === item.to} onClick={onClose} />
          ))}
        </ul>

        <div className="border-t border-zinc-950/5 px-2 pt-2 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          <button
            onClick={() => logout().then(() => navigate("/login"))}
            className="flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left text-[15px] font-medium text-zinc-600 hover:bg-zinc-100 active:bg-zinc-100"
          >
            <LogOut className="size-5" />
            Déconnexion
          </button>
        </div>
    </>
  );
}

function MenuLink({ item, active, onClick }: { item: MenuItem; active: boolean; onClick?: () => void }) {
  const { to, icon: Icon, label, badge = 0, external } = item;
  const className = `flex items-center gap-3 rounded-xl px-3 py-2.5 text-[15px] font-medium transition ${
    active ? "bg-brand-50 text-brand-700" : "text-zinc-700 hover:bg-zinc-100 active:bg-zinc-100"
  }`;
  const content = (
    <>
      <Icon className={`size-5 ${active ? "text-brand-600" : "text-zinc-400"}`} strokeWidth={2} />
      <span className="flex-1">{label}</span>
      {badge > 0 && (
        <span className="min-w-6 rounded-full bg-brand-600 px-2 py-0.5 text-center text-xs font-semibold text-white tabular-nums">{badge}</span>
      )}
      {external && <ChevronRight className="size-4 text-zinc-300" />}
    </>
  );
  return (
    <li>
      {external ? (
        <a href={to} className={className}>
          {content}
        </a>
      ) : (
        <Link to={to} onClick={onClick} className={className}>
          {content}
        </Link>
      )}
    </li>
  );
}
