import type { Feature } from "geojson";
import { Check, ChevronDown, ChevronRight, MapPinned, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { GeoJSON } from "react-leaflet";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api, errorMessage } from "../api/client";
import ActiveTourAlert, { activeTourId } from "../components/ActiveTourAlert";
import type { Area, LatLon, Tour } from "../api/types";
import LocationStatus from "../components/LocationStatus";
import { FitBounds, MapClick, MapLayers, PinMarker } from "../components/map";
import { BackContext } from "../context/BackContext";
import { Alert, Button, EmptyState, Loading, Sheet } from "../components/ui";
import { useGeo } from "../hooks/useGeolocation";
import { scoreColor } from "../lib/constants";
import { areaPoints } from "../lib/geo";

const RADII_KM = [1, 3, 5, 10];
const RADIUS_KEY = "predefined-tour-radius-km";

function savedRadius(): number {
  try {
    const value = Number(localStorage.getItem(RADIUS_KEY));
    return RADII_KM.includes(value) ? value : 3;
  } catch {
    return 3;
  }
}

export default function PredefinedTour() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const zone = Number(params.get("zone")) || null;
  const geo = useGeo();
  const [areas, setAreas] = useState<Area[] | null>(null);
  const [selected, setSelected] = useState<Area | null>(null);
  const [start, setStart] = useState<LatLon | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTour, setActiveTour] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const here = geo.here;
  // Where the zones are searched around: the first known position (not refetched as the militant moves),
  // or nowhere (best zones of the whole organization) when the position is unavailable.
  const [origin, setOrigin] = useState<LatLon | null | undefined>(undefined);
  const [radius, setRadius] = useState(savedRadius);
  const pickRadius = (km: number) => {
    setRadius(km);
    try {
      localStorage.setItem(RADIUS_KEY, String(km));
    } catch {
      /* storage unavailable: the choice only lasts for this visit */
    }
  };
  useEffect(() => {
    if (origin !== undefined) return;
    if (here) setOrigin(here);
    else if (geo.status === "error") setOrigin(null);
  }, [here, geo.status, origin]);

  useEffect(() => {
    if (origin === undefined) return;
    const query: Record<string, number> = {};
    if (zone) query.zone = zone;
    if (origin) Object.assign(query, { lat: origin.lat, lon: origin.lon, radius_km: radius });
    let cancelled = false;
    setAreas(null);
    setError(null);
    api<Area[]>("/areas/", { query })
      .then((list) => {
        if (cancelled) return;
        setAreas(list);
        const picked = zone ? list.find((a) => a.id === zone) : undefined;
        if (picked) setSelected(picked);
      })
      .catch((e) => !cancelled && setError(errorMessage(e)));
    return () => {
      cancelled = true;
    };
  }, [zone, origin, radius]);
  // Start point: the device position as soon as it is known (also for a zone picked from the zones map).
  useEffect(() => {
    if (selected && here && !start) setStart(here);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.id, here]);

  const select = (area: Area | null) => {
    setSelected(area);
    setStart(area && here ? here : null);
  };

  const allPoints = useMemo(() => (selected ? areaPoints(selected) : (areas ?? []).flatMap(areaPoints)), [areas, selected]);

  const compute = async () => {
    if (!selected || !start) return;
    setLoading(true);
    setError(null);
    setActiveTour(null);
    try {
      const tour = await api<Tour>("/tours/", { method: "POST", body: { kind: "predefined", area_id: selected.id, start } });
      navigate(`/tours/${tour.id}`, { replace: true });
    } catch (err) {
      const active = activeTourId(err);
      if (active !== null) setActiveTour(active);
      else setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <MapLayers>
        <FitBounds points={allPoints} fitKey={`${radius}-${areas?.length}-${selected?.id}`} />
        {selected && <MapClick onClick={setStart} />}
        {(areas ?? []).map((area) => (
          <GeoJSON
            key={`${area.id}-${selected?.id === area.id}-${!!selected}`}
            data={{ type: "Feature", properties: {}, geometry: area.geometry } as Feature}
            style={{
              color: scoreColor(area.score),
              weight: selected?.id === area.id ? 3 : 2,
              fillOpacity: selected?.id === area.id ? 0.2 : 0.1,
              opacity: selected && selected.id !== area.id ? 0.3 : 1,
            }}
            interactive={!selected}
            eventHandlers={{ click: () => !selected && area.n_to_visit > 0 && select(area) }}
          />
        ))}
        {start && <PinMarker point={start} color="#059669" label="Départ" kind="start" />}
      </MapLayers>

      {!selected ? (
        <Sheet
          half
          title="Tournée préparée"
          subtitle={
            origin === undefined
              ? undefined
              : origin
                ? "Les 10 meilleures zones autour de toi"
                : "Les 10 meilleures zones (position indisponible)"
          }
          action={origin && <RadiusPicker value={radius} onChange={pickRadius} />}
        >
          {origin === undefined && <LocationStatus geo={geo} onRetry={geo.retry} />}
          {origin !== undefined && !areas && !error && <Loading />}
          {error && <Alert>{error}</Alert>}
          {areas?.length === 0 && (
            <EmptyState icon={MapPinned} title={origin ? `Aucune zone à moins de ${radius} km` : "Aucune zone préparée"}>
            </EmptyState>
          )}
          <div className="space-y-2">
            {areas?.map((area) => (
              <button
                key={area.id}
                onClick={() => select(area)}
                disabled={area.n_to_visit === 0}
                className="flex w-full items-center gap-3 rounded-2xl bg-white p-3 text-left ring-1 ring-zinc-950/[0.08] active:bg-zinc-50 disabled:opacity-50"
              >
                <span
                  className={`flex size-10 shrink-0 items-center justify-center rounded-xl text-sm font-bold tabular-nums ${area.score >= 40 ? "text-white" : "text-zinc-900"}`}
                  style={{ background: scoreColor(area.score) }}
                  title="Score de la zone (sur 100)"
                >
                  {Math.round(area.score)}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-semibold tracking-tight">{area.name}</p>
                  <p className="text-xs text-zinc-500 tabular-nums">
                    {area.n_to_visit} adresse{area.n_to_visit > 1 ? "s" : ""} à visiter
                    {area.done_pct > 0 ? ` · ${area.done_pct.toLocaleString("fr")} % des portes faites` : ""}
                  </p>
                </div>
                <ChevronRight className="size-5 text-zinc-300" />
              </button>
            ))}
          </div>
        </Sheet>
      ) : (
        // "Back" returns to the list of zones (instead of leaving the page).
        <BackContext.Provider value={() => select(null)}>
          <Sheet
            title={selected.name}
            subtitle="Touche la carte pour changer le départ"
            footer={
              <Button className="w-full" icon={Sparkles} disabled={!start} loading={loading} onClick={compute}>
                Calculer
              </Button>
            }
          >
            <AreaStats area={selected} />
            {!start && <LocationStatus geo={geo} onRetry={geo.retry} />}
            {!start && geo.status !== "pending" && <p className="text-sm text-zinc-600">Place ton point de départ sur la carte.</p>}
            {loading && <p className="text-sm text-zinc-500">Calcul des distances réelles pour optimiser la tournée…</p>}
            {activeTour !== null && <ActiveTourAlert tourId={activeTour} onStopped={compute} />}
            {error && <Alert>{error}</Alert>}
          </Sheet>
        </BackContext.Provider>
      )}
    </>
  );
}

/** Score, French voters (done / total once some were) and addresses free for a tour. */
function AreaStats({ area }: { area: Area }) {
  return (
    <div className="grid grid-cols-3 gap-2">
      <Stat label="Score" value={Math.round(area.score).toString()} color={scoreColor(area.score)} />
      <Stat
        label={area.n_done > 0 ? `Faits · ${area.done_pct.toLocaleString("fr")} %` : "Français·es"}
        value={area.n_done > 0 ? `${area.n_done}/${area.n_total}` : area.n_total.toLocaleString("fr")}
      />
      <Stat label="À visiter" value={area.n_to_visit.toLocaleString("fr")} />
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="rounded-xl bg-zinc-50 px-3 py-2 ring-1 ring-zinc-950/5">
      <p className="flex items-center gap-1.5 text-[15px] font-semibold tracking-tight tabular-nums">
        {color && <span className="size-2.5 shrink-0 rounded-full" style={{ background: color }} />}
        {value}
      </p>
      <p className="truncate text-xs text-zinc-500">{label}</p>
    </div>
  );
}

/** Search radius: one tag in the corner of the sheet, opening the list of choices. */
function RadiusPicker({ value, onChange }: { value: number; onChange: (km: number) => void }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  // Close when tapping anywhere else.
  useEffect(() => {
    if (!open) return;
    const close = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Rayon de recherche"
        className="flex items-center gap-1 rounded-full bg-brand-600 py-1.5 pr-2 pl-3 text-xs font-semibold text-white tabular-nums active:opacity-90"
      >
        {value} km
        <ChevronDown className={`size-3.5 transition-transform ${open ? "rotate-180" : ""}`} strokeWidth={2.5} />
      </button>
      {open && (
        <ul
          role="listbox"
          aria-label="Rayon de recherche"
          className="absolute top-full right-0 z-10 mt-1.5 w-24 overflow-hidden rounded-2xl bg-white py-1 shadow-float ring-1 ring-zinc-950/10"
        >
          {RADII_KM.map((km) => (
            <li key={km}>
              <button
                type="button"
                role="option"
                aria-selected={km === value}
                onClick={() => {
                  onChange(km);
                  setOpen(false);
                }}
                className={`flex w-full items-center justify-between px-3 py-2 text-sm tabular-nums active:bg-zinc-50 ${
                  km === value ? "font-semibold text-brand-700" : "text-zinc-700"
                }`}
              >
                {km} km
                {km === value && <Check className="size-4" strokeWidth={2.5} />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
