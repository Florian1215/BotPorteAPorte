import type { Feature } from "geojson";
import { ArrowLeft, ArrowRight, Check, LoaderCircle, LocateFixed, MapPin, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { GeoJSON, Polyline } from "react-leaflet";
import { useNavigate } from "react-router-dom";

import { api, errorMessage } from "../api/client";
import ActiveTourAlert, { activeTourId } from "../components/ActiveTourAlert";
import type { FreeTourPreview, LatLon, Tour } from "../api/types";
import LocationStatus from "../components/LocationStatus";
import { FitBounds, MapClick, MapLayers, PinMarker, useFlyTo } from "../components/map";
import { Alert, Button, Chips, Sheet } from "../components/ui";
import { useGeo } from "../hooks/useGeolocation";
import { RADIUS_OPTIONS_KM, formatKm } from "../lib/constants";
import { areaPoints } from "../lib/geo";

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
  const [activeTour, setActiveTour] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [preview, setPreview] = useState<FreeTourPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const here = geo.here;

  // Radius step: show the corridor the tour will cover (around the walking route) and how many doors are in it.
  useEffect(() => {
    if (step !== "radius" || !start || !end || radius == null) return;
    let cancelled = false;
    setPreviewing(true);
    const timer = setTimeout(() => {
      api<FreeTourPreview>("/tours/free/preview/", { method: "POST", body: { start, end, radius_km: radius } })
        .then((p) => !cancelled && setPreview(p))
        .catch(() => !cancelled && setPreview(null))
        .finally(() => !cancelled && setPreviewing(false));
    }, 150);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [step, start, end, radius]);

  const corridorPoints = useMemo(() => (preview ? areaPoints({ geometry: preview.corridor }) : []), [preview]);

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
    setActiveTour(null);
    try {
      const tour = await api<Tour>("/tours/", { method: "POST", body: { kind: "free", start, end, radius_km: radius } });
      navigate(`/tours/${tour.id}`, { replace: true });
    } catch (err) {
      const active = activeTourId(err);
      if (active !== null) setActiveTour(active);
      else setError(errorMessage(err));
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
        {step === "radius" && preview && (
          <>
            <FitBounds points={corridorPoints} fitKey={`corridor-${radius}-${corridorPoints.length}`} />
            <GeoJSON
              key={`corridor-${radius}-${JSON.stringify(preview.corridor).length}`}
              data={{ type: "Feature", properties: {}, geometry: preview.corridor } as Feature}
              interactive={false}
              style={{ color: "#d1271c", weight: 1.5, dashArray: "5 6", fillColor: "#d1271c", fillOpacity: 0.1 }}
            />
            <Polyline positions={preview.route} interactive={false} pathOptions={{ color: "#d1271c", weight: 4, opacity: 0.7, lineCap: "round" }} />
          </>
        )}
        {start && end && !(step === "radius" && preview) && (
          <Polyline
            positions={[
              [start.lat, start.lon],
              [end.lat, end.lon],
            ]}
            pathOptions={{ color: "#18181b", weight: 2.5, dashArray: "2 7", lineCap: "round", opacity: 0.6 }}
            interactive={false}
          />
        )}
        {start && <PinMarker point={start} color="#059669" label="Départ" kind="start" />}
        {end && <PinMarker point={end} color="#18181b" label="Arrivée" kind="end" />}
      </MapLayers>

      <Sheet
        title="Tournée libre"
        subtitle={prompt}
        onLocate={(position) => step === "start" && setStart(position)}
        footer={
          <div className="grid grid-cols-2 gap-2">
            {step === "start" ? (
              <Button variant="secondary" icon={LocateFixed} disabled={!here} onClick={() => here && (setStart(here), flyTo([here.lat, here.lon]))}>
                Ma position
              </Button>
            ) : (
              <Button variant="secondary" icon={ArrowLeft} onClick={() => setStep(STEPS[stepIdx - 1][0])}>
                Retour
              </Button>
            )}
            {step === "radius" ? (
              <Button icon={Sparkles} loading={loading} onClick={compute}>
                Calculer
              </Button>
            ) : (
              <Button disabled={step === "start" ? !start : !end} onClick={() => setStep(STEPS[stepIdx + 1][0])}>
                Suivant <ArrowRight className="size-[18px]" strokeWidth={2.25} />
              </Button>
            )}
          </div>
        }
      >
        <ol className="flex items-center gap-2 text-xs font-semibold">
          {STEPS.map(([s, label], i) => (
            <li key={s} className={`flex flex-1 items-center gap-2 ${i <= stepIdx ? "text-zinc-900" : "text-zinc-400"}`}>
              <span
                className={`flex size-6 shrink-0 items-center justify-center rounded-full text-[11px] tabular-nums ${
                  i < stepIdx ? "bg-brand-600 text-white" : i === stepIdx ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-400"
                }`}
              >
                {i < stepIdx ? <Check className="size-3.5" strokeWidth={3} /> : i + 1}
              </span>
              {label}
              {i < STEPS.length - 1 && <span className={`h-px flex-1 ${i < stepIdx ? "bg-brand-600" : "bg-zinc-200"}`} />}
            </li>
          ))}
        </ol>
        {step === "start" && <LocationStatus geo={geo} onRetry={geo.retry} />}
        {step === "end" && here && (
          <button className="inline-flex items-center gap-1.5 text-sm font-semibold text-brand-600" onClick={() => setEnd(here)}>
            <LocateFixed className="size-4" /> Utiliser ma position comme arrivée
          </button>
        )}
        {step === "radius" && <Chips options={RADIUS_OPTIONS_KM} value={radius} onChange={setRadius} format={formatKm} />}
        {step === "radius" && (
          <p className="flex items-center gap-2 text-sm text-zinc-600">
            {previewing && !preview ? (
              <>
                <LoaderCircle className="size-4 animate-spin text-zinc-400" /> Calcul du périmètre…
              </>
            ) : preview ? (
              <>
                <MapPin className="size-4 shrink-0 text-brand-600" />
                <span>
                  <strong className="font-semibold text-zinc-900 tabular-nums">{preview.n_addresses.toLocaleString("fr")}</strong> porte
                  {preview.n_addresses > 1 ? "s" : ""} à frapper dans ce périmètre
                  {preview.n_addresses > preview.max_stops && ` (on gardera les ${preview.max_stops} plus proches du trajet)`}
                  {preview.route_approximate && <span className="text-zinc-400"> · trajet à vol d'oiseau</span>}
                </span>
              </>
            ) : null}
          </p>
        )}
        {activeTour !== null && <ActiveTourAlert tourId={activeTour} onStopped={compute} />}
        {error && <Alert>{error}</Alert>}
      </Sheet>
    </>
  );
}
