import { ChartColumn, ChevronRight, Footprints, LoaderCircle, Map as MapIcon, MapPin, MapPinned, NotebookPen, Route } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { CircleMarker } from "react-leaflet";
import { Link, Navigate } from "react-router-dom";

import { api } from "../api/client";
import type { NearbyResponse, OrganizationOverview, Tour } from "../api/types";
import JoinRequest from "../components/JoinRequest";
import { MapLayers, useFlyTo } from "../components/map";
import { IconTile, Sheet } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useGeo } from "../hooks/useGeolocation";
import { RESULTS } from "../lib/constants";
import { usePendingMembers } from "../hooks/usePendingCount";

const SHORTCUTS = [
  { to: "/nearby", icon: MapPinned, label: "Alentours" },
  { to: "/stats", icon: ChartColumn, label: "Mes stats" },
];

export default function Home() {
  const { user } = useAuth();
  const geo = useGeo();
  const flyTo = useFlyTo();
  const [tour, setTour] = useState<Tour | null>(null);
  const [overview, setOverview] = useState<OrganizationOverview | null>(null);
  const [nearby, setNearby] = useState<NearbyResponse | null>(null);
  const centered = useRef(false);
  const { members: pending } = usePendingMembers();

  useEffect(() => {
    api<Tour | null>("/tours/current/").then(setTour).catch(() => setTour(null));
    api<OrganizationOverview>("/stats/organization/").then(setOverview).catch(() => setOverview(null));
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

  const visited = tour ? tour.stops.filter((s) => s.result).length : 0;

  // A site admin who has not picked an organization yet starts on the organization list.
  if (!user?.organization) return <Navigate to="/organizations" replace />;

  const subtitle =
    geo.status === "pending" ? (
      <span className="inline-flex items-center gap-1.5">
        <LoaderCircle className="size-3.5 animate-spin text-sky-600" /> Recherche de ta position…
      </span>
    ) : nearby ? (
      <span className="inline-flex items-center gap-1.5">
        <MapPin className="size-3.5 text-brand-600" />
        {nearby.total.toLocaleString("fr")} porte{nearby.total > 1 ? "s" : ""} à frapper à moins d'1 km
      </span>
    ) : geo.error ? (
      "Position indisponible"
    ) : null;

  return (
    <>
      <MapLayers>
        {nearby?.addresses.map((a) => (
          <CircleMarker
            key={a.id}
            center={[a.lat, a.lon]}
            radius={4.5}
            interactive={false}
            pathOptions={{ color: "white", weight: 1.5, fillColor: "#d1271c", fillOpacity: 0.9 }}
          />
        ))}
      </MapLayers>

      <Sheet
        title={`Salut ${user.first_name || "camarade"}`}
        subtitle={subtitle}
        above={
          pending.length > 0 && (
            <JoinRequest key={pending[0].id} member={pending[0]} organization={user.organization.name} others={pending.length - 1} />
          )
        }
      >
        {tour && (
          <Link
            to={`/tours/${tour.id}`}
            className="flex items-center gap-3 rounded-2xl bg-brand-600 p-4 text-white active:opacity-95"
          >
            <IconTile icon={tour.status === "active" ? Footprints : NotebookPen} tone="inverse" className="size-11" />
            <div className="min-w-0 flex-1">
              <p className="font-semibold">{tour.status === "active" ? "Reprendre ma tournée" : "Tournée en préparation"}</p>
              <div className="mt-1.5 flex items-center gap-2 text-xs text-white/85">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/25">
                  <div className="h-full rounded-full bg-white" style={{ width: `${tour.stops.length ? (visited / tour.stops.length) * 100 : 0}%` }} />
                </div>
                <span className="tabular-nums">
                  {visited}/{tour.stops.length}
                </span>
              </div>
            </div>
            <ChevronRight className="size-5 opacity-80" />
          </Link>
        )}


        <div className="grid grid-cols-2 gap-2">
          <TourCard to="/tours/new/free" icon={Route} title="Tournée libre" />
          <TourCard to="/tours/new/predefined" icon={MapIcon} title="Tournée préparée" />
        </div>

        <div className="grid grid-cols-2 gap-2">
          {SHORTCUTS.map((s) => (
            <Link
              key={s.to}
              to={s.to}
              className="flex flex-col items-center gap-1.5 rounded-2xl bg-zinc-50 py-3 text-xs font-semibold text-zinc-700 ring-1 ring-zinc-950/5 active:bg-zinc-100"
            >
              <s.icon className="size-5 text-zinc-500" strokeWidth={2} />
              {s.label}
            </Link>
          ))}
        </div>

        {overview && overview.total > 0 && <TotalBar overview={overview} />}
      </Sheet>
    </>
  );
}

function TourCard({ to, icon, title }: { to: string; icon: typeof Route; title: string }) {
  return (
    <Link to={to} className="flex items-center gap-2.5 rounded-2xl bg-white p-2.5 ring-1 ring-zinc-950/[0.08] active:bg-zinc-50">
      <IconTile icon={icon} className="size-9" />
      <span className="min-w-0 text-[15px] leading-tight font-semibold tracking-tight">{title}</span>
    </Link>
  );
}

function percent(value: number, total: number): string {
  if (value === 0 || total === 0) return "0 %";
  const p = (value / total) * 100;
  return p < 1 ? "<1 %" : `${Math.round(p)} %`;
}

/** Every door knocked in the organization for the current election = 100 %, one color per feedback. Tap for the details. */
function TotalBar({ overview }: { overview: OrganizationOverview }) {
  const [open, setOpen] = useState(false);
  const knocked = overview.doors_knocked;

  return (
    <div className="pt-1">
      <div className="flex items-baseline justify-between gap-2">
        <span className="min-w-0 truncate text-[13px] font-semibold text-zinc-500">
          Portes frappées{overview.election ? ` · ${overview.election}` : " par toute l'organisation"}
        </span>
        <span className="shrink-0 text-sm font-semibold tabular-nums">{knocked.toLocaleString("fr")}</span>
      </div>

      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label="Détail des retours"
        className="mt-2 flex h-3 w-full overflow-hidden rounded-full bg-zinc-200"
      >
        {RESULTS.map((r) => {
          const value = overview.doors_by_result[r.value];
          if (!value) return null;
          const width = (value / knocked) * 100;
          return (
            <span
              key={r.value}
              className="h-full min-w-[3px] border-r border-white/70 last:border-r-0"
              style={{ width: `${width}%`, background: r.color }}
            />
          );
        })}
      </button>

      {open && (
        <div className="relative mt-2.5 rounded-2xl bg-white p-3 text-xs ring-1 ring-zinc-950/10 shadow-float">
          <span className="absolute -top-1.5 left-6 size-3 rotate-45 border-t border-l border-zinc-950/10 bg-white" aria-hidden />
          <div className="space-y-1.5">
            {RESULTS.map((r) => (
              <DetailRow key={r.value} color={r.color} label={r.label} value={overview.doors_by_result[r.value]} total={knocked} />
            ))}
          </div>
          <p className="mt-2 border-t border-zinc-950/5 pt-2 text-zinc-500 tabular-nums">
            {overview.by_status.to_visit.toLocaleString("fr")} adresses encore à visiter sur {overview.total.toLocaleString("fr")}
          </p>
        </div>
      )}
    </div>
  );
}

function DetailRow({ color, label, value, total }: { color: string; label: string; value: number; total: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className="size-2.5 shrink-0 rounded-sm" style={{ background: color }} />
      <span className="min-w-0 flex-1 truncate text-zinc-600">{label}</span>
      <span className="shrink-0 font-semibold text-zinc-900 tabular-nums">{value.toLocaleString("fr")}</span>
      <span className="w-10 shrink-0 text-right text-zinc-500 tabular-nums">{percent(value, total)}</span>
    </div>
  );
}
