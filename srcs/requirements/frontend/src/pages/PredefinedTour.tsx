import type { Feature } from "geojson";
import { useEffect, useMemo, useState } from "react";
import { GeoJSON } from "react-leaflet";
import { useNavigate } from "react-router-dom";

import { api, errorMessage } from "../api/client";
import type { Area, LatLon, Tour } from "../api/types";
import LocationStatus from "../components/LocationStatus";
import { FitBounds, MapClick, MapLayers, PinMarker } from "../components/map";
import { Alert, Button, Sheet, Spinner } from "../components/ui";
import { useGeo } from "../hooks/useGeolocation";

function areaPoints(area: Area): [number, number][] {
  const pts: [number, number][] = [];
  const walk = (c: unknown) => {
    if (Array.isArray(c) && typeof c[0] === "number") pts.push([c[1] as number, c[0] as number]);
    else if (Array.isArray(c)) c.forEach(walk);
  };
  walk(area.geometry.coordinates);
  return pts;
}

export default function PredefinedTour() {
  const navigate = useNavigate();
  const geo = useGeo();
  const [areas, setAreas] = useState<Area[] | null>(null);
  const [selected, setSelected] = useState<Area | null>(null);
  const [start, setStart] = useState<LatLon | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const here = geo.here;

  useEffect(() => {
    api<Area[]>("/areas/").then(setAreas).catch((e) => setError(errorMessage(e)));
  }, []);

  const select = (area: Area | null) => {
    setSelected(area);
    setStart(area && here ? here : null);
  };

  const allPoints = useMemo(() => (selected ? areaPoints(selected) : (areas ?? []).flatMap(areaPoints)), [areas, selected]);

  const compute = async () => {
    if (!selected || !start) return;
    setLoading(true);
    setError(null);
    try {
      const tour = await api<Tour>("/tours/", { method: "POST", body: { kind: "predefined", area_id: selected.id, start } });
      navigate(`/tours/${tour.id}`, { replace: true });
    } catch (err) {
      setError(errorMessage(err));
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
              color: "#c8102e",
              weight: selected?.id === area.id ? 3 : 2,
              fillOpacity: selected?.id === area.id ? 0.2 : 0.1,
              opacity: selected && selected.id !== area.id ? 0.3 : 1,
            }}
            interactive={!selected}
            eventHandlers={{ click: () => !selected && area.n_to_visit > 0 && select(area) }}
          />
        ))}
        {start && <PinMarker point={start} color="#16a34a" label="Départ" />}
      </MapLayers>

      {!selected ? (
        <Sheet title="Tournée préparée" subtitle="Choisis une zone dans la liste ou sur la carte.">
          {!areas && !error && (
            <div className="flex justify-center py-4 text-brand-600">
              <Spinner />
            </div>
          )}
          {error && <Alert>{error}</Alert>}
          {areas?.length === 0 && <Alert kind="info">Aucune tournée préparée disponible pour le moment.</Alert>}
          <div className="space-y-2">
            {areas?.map((area) => (
              <button
                key={area.id}
                onClick={() => select(area)}
                disabled={area.n_to_visit === 0}
                className="flex w-full items-center gap-3 rounded-2xl bg-slate-50 p-3.5 text-left ring-1 ring-slate-200 active:bg-slate-100 disabled:opacity-50"
              >
                <div className="flex-1">
                  <p className="font-semibold">{area.name}</p>
                  <p className="text-xs text-slate-500">
                    {area.n_to_visit} adresse{area.n_to_visit > 1 ? "s" : ""} à visiter
                  </p>
                </div>
                <span className="text-slate-400" aria-hidden>
                  ›
                </span>
              </button>
            ))}
          </div>
        </Sheet>
      ) : (
        <Sheet
          title={selected.name}
          subtitle={`${selected.n_to_visit} adresses à visiter · touche la carte pour changer le départ`}
          action={
            <button className="text-sm font-semibold text-brand-600" onClick={() => select(null)}>
              Changer
            </button>
          }
          footer={
            <div className="grid grid-cols-2 gap-2">
              <Button variant="secondary" disabled={!here} onClick={() => here && setStart(here)}>
                📍 Ma position
              </Button>
              <Button disabled={!start} loading={loading} onClick={compute}>
                Calculer
              </Button>
            </div>
          }
        >
          {!start && <LocationStatus geo={geo} onRetry={geo.retry} />}
          {!start && geo.status !== "pending" && <p className="text-sm text-slate-600">Place ton point de départ sur la carte.</p>}
          {loading && <p className="text-sm text-slate-500">Calcul des distances réelles pour optimiser la tournée…</p>}
          {error && <Alert>{error}</Alert>}
        </Sheet>
      )}
    </>
  );
}
