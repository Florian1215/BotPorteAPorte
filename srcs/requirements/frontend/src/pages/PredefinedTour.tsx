import type { Feature } from "geojson";
import { ChevronRight, LocateFixed, MapPinned, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { GeoJSON } from "react-leaflet";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api, errorMessage } from "../api/client";
import ActiveTourAlert, { activeTourId } from "../components/ActiveTourAlert";
import type { Area, LatLon, Tour } from "../api/types";
import LocationStatus from "../components/LocationStatus";
import { FitBounds, MapClick, MapLayers, PinMarker } from "../components/map";
import { Alert, Button, EmptyState, Loading, Sheet } from "../components/ui";
import { useGeo } from "../hooks/useGeolocation";
import { scoreColor } from "../lib/constants";
import { areaPoints } from "../lib/geo";

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

  useEffect(() => {
    api<Area[]>("/areas/", { query: zone ? { zone } : undefined })
      .then((list) => {
        setAreas(list);
        const picked = zone ? list.find((a) => a.id === zone) : undefined;
        if (picked) setSelected(picked);
      })
      .catch((e) => setError(errorMessage(e)));
  }, [zone]);
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
        <FitBounds points={allPoints} fitKey={`${areas?.length}-${selected?.id}`} />
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
        <Sheet title="Tournée préparée">
          {!areas && !error && <Loading />}
          {error && <Alert>{error}</Alert>}
          {areas?.length === 0 && (
            <EmptyState icon={MapPinned} title="Aucune zone préparée">
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
        <Sheet
          title={selected.name}
          subtitle={`${selected.n_to_visit} adresses à visiter · touche la carte pour changer le départ`}
          action={
            <Button variant="secondary" size="sm" onClick={() => select(null)}>
              Changer
            </Button>
          }
          footer={
            <div className="grid grid-cols-2 gap-2">
              <Button variant="secondary" icon={LocateFixed} disabled={!here} onClick={() => here && setStart(here)}>
                Ma position
              </Button>
              <Button icon={Sparkles} disabled={!start} loading={loading} onClick={compute}>
                Calculer
              </Button>
            </div>
          }
        >
          {!start && <LocationStatus geo={geo} onRetry={geo.retry} />}
          {!start && geo.status !== "pending" && <p className="text-sm text-zinc-600">Place ton point de départ sur la carte.</p>}
          {loading && <p className="text-sm text-zinc-500">Calcul des distances réelles pour optimiser la tournée…</p>}
          {activeTour !== null && <ActiveTourAlert tourId={activeTour} onStopped={compute} />}
          {error && <Alert>{error}</Alert>}
        </Sheet>
      )}
    </>
  );
}
