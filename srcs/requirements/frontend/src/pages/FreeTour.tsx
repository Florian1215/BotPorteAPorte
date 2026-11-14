import { useEffect, useRef, useState } from "react";
import { Polyline } from "react-leaflet";
import { useNavigate } from "react-router-dom";

import { api, errorMessage } from "../api/client";
import type { LatLon, Tour } from "../api/types";
import LocationStatus from "../components/LocationStatus";
import { MapClick, MapLayers, PinMarker, useFlyTo } from "../components/map";
import { Alert, Button, Chips, Sheet } from "../components/ui";
import { useGeo } from "../hooks/useGeolocation";
import { RADIUS_OPTIONS_KM, formatKm } from "../lib/constants";

type Step = "start" | "end" | "radius";

const STEPS: [Step, string][] = [
  ["start", "Départ"],
  ["end", "Arrivée"],
  ["radius", "Déviation"],
];

export default function FreeTour() {
  const navigate = useNavigate();
  const geo = useGeo();
  const flyTo = useFlyTo();
  const [step, setStep] = useState<Step>("start");
  const [start, setStart] = useState<LatLon | null>(null);
  const [end, setEnd] = useState<LatLon | null>(null);
  const [radius, setRadius] = useState<number | null>(0.2);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const here = geo.here;

  // Pre-fill the start with the device position (as the bot did with the shared location).
  const prefilled = useRef(false);
  useEffect(() => {
    if (here && !prefilled.current && !start) {
      prefilled.current = true;
      setStart(here);
      flyTo([here.lat, here.lon], 15);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [here]);

  const onMapClick = (p: LatLon) => {
    if (step === "start") setStart(p);
    else if (step === "end") setEnd(p);
  };

  const compute = async () => {
    if (!start || !end || radius == null) return;
    setLoading(true);
    setError(null);
    try {
      const tour = await api<Tour>("/tours/", { method: "POST", body: { kind: "free", start, end, radius_km: radius } });
      navigate(`/tours/${tour.id}`, { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const stepIdx = STEPS.findIndex(([s]) => s === step);
  const prompt = {
    start: "Touche la carte pour placer ton point de départ.",
    end: "Touche la carte pour placer ton point d'arrivée.",
    radius: "Jusqu'où es-tu prêt·e à t'écarter du trajet ? 250 m suffisent souvent en ville.",
  }[step];

  return (
    <>
      <MapLayers>
        <MapClick onClick={onMapClick} />
        {start && end && (
          <Polyline
            positions={[
              [start.lat, start.lon],
              [end.lat, end.lon],
            ]}
            pathOptions={{ color: "#334155", weight: 2, dashArray: "4 6", opacity: 0.7 }}
            interactive={false}
          />
        )}
        {start && <PinMarker point={start} color="#16a34a" label="Départ" />}
        {end && <PinMarker point={end} color="#c8102e" label="Arrivée" />}
      </MapLayers>

      <Sheet
        title="Tournée libre"
        subtitle={prompt}
        footer={
          <div className="grid grid-cols-2 gap-2">
            {step === "start" ? (
              <Button variant="secondary" disabled={!here} onClick={() => here && (setStart(here), flyTo([here.lat, here.lon]))}>
                📍 Ma position
              </Button>
            ) : (
              <Button variant="secondary" onClick={() => setStep(STEPS[stepIdx - 1][0])}>
                Retour
              </Button>
            )}
            {step === "radius" ? (
              <Button loading={loading} onClick={compute}>
                Calculer
              </Button>
            ) : (
              <Button disabled={step === "start" ? !start : !end} onClick={() => setStep(STEPS[stepIdx + 1][0])}>
                Suivant
              </Button>
            )}
          </div>
        }
      >
        <ol className="flex gap-2 text-xs font-semibold">
          {STEPS.map(([s, label], i) => (
            <li
              key={s}
              className={`flex-1 border-t-4 pt-1 ${i <= stepIdx ? "border-brand-600 text-brand-700" : "border-slate-200 text-slate-400"}`}
            >
              {i + 1}. {label}
            </li>
          ))}
        </ol>
        {step === "start" && <LocationStatus geo={geo} onRetry={geo.retry} />}
        {step === "end" && here && (
          <button className="text-sm font-medium text-brand-600" onClick={() => setEnd(here)}>
            Utiliser ma position comme arrivée
          </button>
        )}
        {step === "radius" && <Chips options={RADIUS_OPTIONS_KM} value={radius} onChange={setRadius} format={formatKm} />}
        {error && <Alert>{error}</Alert>}
      </Sheet>
    </>
  );
}
