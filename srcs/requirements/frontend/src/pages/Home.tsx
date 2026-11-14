import { useEffect, useRef, useState } from "react";
import { CircleMarker } from "react-leaflet";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { NearbyResponse, ScopeOverview, Tour } from "../api/types";
import { MapLayers, useFlyTo } from "../components/map";
import { Sheet } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useGeo } from "../hooks/useGeolocation";

const SHORTCUTS = [
  { to: "/nearby", emoji: "📍", label: "Alentours" },
  { to: "/manual", emoji: "✍️", label: "Marquer" },
  { to: "/stats", emoji: "📊", label: "Mes stats" },
];

export default function Home() {
  const { user } = useAuth();
  const geo = useGeo();
  const flyTo = useFlyTo();
  const [tour, setTour] = useState<Tour | null>(null);
  const [overview, setOverview] = useState<ScopeOverview | null>(null);
  const [nearby, setNearby] = useState<NearbyResponse | null>(null);
  const centered = useRef(false);

  useEffect(() => {
    api<Tour | null>("/tours/current/").then(setTour).catch(() => setTour(null));
    api<ScopeOverview>("/stats/scope/").then(setOverview).catch(() => setOverview(null));
  }, []);

  // Center on the militant once, then show the doors still to knock around them.
  const here = geo.here;
  const cell = here ? `${here.lat.toFixed(3)},${here.lon.toFixed(3)}` : null;
  useEffect(() => {
    if (!here) return;
    if (!centered.current) {
      centered.current = true;
      flyTo([here.lat, here.lon], 15);
    }
    api<NearbyResponse>("/addresses/nearby/", { query: { lat: here.lat, lon: here.lon, radius_km: 1 } })
      .then(setNearby)
      .catch(() => setNearby(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cell]);

  const done = overview
    ? overview.by_status.commitment_to_vote +
      overview.by_status.good_conversation +
      overview.by_status.do_not_contact +
      overview.by_status.failure
    : 0;
  const pct = overview && overview.total ? Math.round((done / overview.total) * 100) : 0;
  const visited = tour ? tour.stops.filter((s) => s.result).length : 0;

  return (
    <>
      <MapLayers>
        {nearby?.addresses.map((a) => (
          <CircleMarker
            key={a.id}
            center={[a.lat, a.lon]}
            radius={4}
            interactive={false}
            pathOptions={{ color: "white", weight: 1, fillColor: "#c8102e", fillOpacity: 0.85 }}
          />
        ))}
      </MapLayers>

      <Sheet
        title={`Salut ${user?.first_name || user?.username} 👋`}
        subtitle={
          geo.status === "pending"
            ? "📍 Recherche de ta position…"
            : nearby
              ? `${nearby.total.toLocaleString("fr")} porte${nearby.total > 1 ? "s" : ""} à frapper à moins d'1 km`
              : geo.error
                ? "Position indisponible"
                : user?.scope?.name
        }
      >
        {tour && (
          <Link
            to={`/tours/${tour.id}`}
            className="flex items-center gap-3 rounded-2xl bg-brand-600 p-4 text-white shadow-md active:bg-brand-700"
          >
            <span className="text-2xl">{tour.status === "active" ? "🚶" : "📝"}</span>
            <div className="flex-1">
              <p className="font-semibold">{tour.status === "active" ? "Reprendre ma tournée" : "Tournée en préparation"}</p>
              <p className="text-sm opacity-90">
                {visited} / {tour.stops.length} adresses visitées
              </p>
            </div>
            <Chevron />
          </Link>
        )}

        <div className="grid grid-cols-2 gap-2">
          <TourCard to="/tours/new/free" emoji="🧭" title="Tournée libre" text="Départ → arrivée, on choisit les portes sur ton trajet" />
          <TourCard to="/tours/new/predefined" emoji="📋" title="Tournée préparée" text="Une zone préparée par ton groupe d'action" />
        </div>

        <div className="grid grid-cols-3 gap-2">
          {SHORTCUTS.map((s) => (
            <Link
              key={s.to}
              to={s.to}
              className="flex flex-col items-center gap-1 rounded-2xl bg-slate-50 py-3 text-xs font-semibold text-slate-700 ring-1 ring-slate-200 active:bg-slate-100"
            >
              <span className="text-2xl">{s.emoji}</span>
              {s.label}
            </Link>
          ))}
        </div>

        {overview && overview.total > 0 && (
          <div className="pt-1">
            <div className="flex items-baseline justify-between text-sm">
              <span className="font-medium text-slate-700">{user?.scope?.name}</span>
              <span className="text-slate-500">{pct} % visité</span>
            </div>
            <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-slate-100">
              <div className="h-full rounded-full bg-brand-600" style={{ width: `${pct}%` }} />
            </div>
            <p className="mt-1.5 text-xs text-slate-500">
              {overview.by_status.to_visit.toLocaleString("fr")} adresses à visiter ·{" "}
              {overview.by_status.commitment_to_vote.toLocaleString("fr")} promesses de vote
            </p>
          </div>
        )}
      </Sheet>
    </>
  );
}

function TourCard({ to, emoji, title, text }: { to: string; emoji: string; title: string; text: string }) {
  return (
    <Link to={to} className="flex flex-col rounded-2xl bg-brand-50 p-3.5 ring-1 ring-brand-100 active:bg-brand-100">
      <span className="text-2xl">{emoji}</span>
      <span className="mt-1 font-semibold text-brand-700">{title}</span>
      <span className="mt-0.5 text-xs leading-snug text-slate-600">{text}</span>
    </Link>
  );
}

function Chevron() {
  return (
    <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2.5">
      <path d="M9 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
