import { useCallback, useEffect, useMemo, useState } from "react";
import { Marker, Polyline } from "react-leaflet";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, errorMessage } from "../api/client";
import type { ResultValue, Stop, Tour } from "../api/types";
import { FitBounds, FlyTo, MapLayers, PinMarker, stopIcon } from "../components/map";
import { Alert, Button, OverlaySpinner, ResultButtons, Sheet } from "../components/ui";
import { RESULT_BY_VALUE, formatDistance, formatDuration, navigationUrl } from "../lib/constants";

export default function TourPage() {
  const { id } = useParams();
  const [tour, setTour] = useState<Tour | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Tour>(`/tours/${id}/`).then(setTour).catch((e) => setError(errorMessage(e)));
  }, [id]);
  useEffect(load, [load]);

  if (error && !tour)
    return (
      <Sheet title="Tournée introuvable">
        <Alert>{error}</Alert>
      </Sheet>
    );
  if (!tour) return <OverlaySpinner />;
  if (tour.status === "completed")
    return (
      <>
        <TourLayers tour={tour} />
        <TourSummary tour={tour} />
      </>
    );
  return <TourControls tour={tour} setTour={setTour} />;
}

function TourLayers({
  tour,
  current,
  onSelect,
}: {
  tour: Tour;
  current?: Stop;
  onSelect?: (id: number) => void;
}) {
  const allPoints = useMemo<[number, number][]>(
    () => [
      [tour.start.lat, tour.start.lon],
      ...(tour.end ? [[tour.end.lat, tour.end.lon] as [number, number]] : []),
      ...tour.stops.map((s) => [s.address.lat, s.address.lon] as [number, number]),
    ],
    [tour.id], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const stopsLine = useMemo<[number, number][]>(
    () => [[tour.start.lat, tour.start.lon], ...tour.stops.map((s) => [s.address.lat, s.address.lon] as [number, number])],
    [tour.stops, tour.start],
  );
  const isActive = tour.status === "active";

  return (
    <MapLayers>
      <FitBounds points={allPoints} fitKey={`${tour.id}-${tour.status}`} />
      {tour.route && (
        <Polyline positions={tour.route} interactive={false} pathOptions={{ color: "#d946ef", weight: 6, opacity: 0.5 }} />
      )}
      <Polyline positions={stopsLine} interactive={false} pathOptions={{ color: "#334155", weight: 2, dashArray: "4 6", opacity: 0.6 }} />
      <PinMarker point={tour.start} color="#16a34a" label="Départ" />
      {tour.end && <PinMarker point={tour.end} color="#0f172a" label="Arrivée" />}
      {tour.stops.map((stop) => {
        const isCurrent = isActive && stop.id === current?.id;
        const color = stop.result ? RESULT_BY_VALUE[stop.result].color : isCurrent ? "#c8102e" : "#2563eb";
        return (
          <Marker
            key={`${stop.id}-${stop.result}-${isCurrent}`}
            position={[stop.address.lat, stop.address.lon]}
            icon={stopIcon(stop.position + 1, color, isCurrent, isCurrent ? 34 : 28)}
            zIndexOffset={isCurrent ? 1000 : 0}
            interactive={!!onSelect}
            eventHandlers={onSelect ? { click: () => onSelect(stop.id) } : {}}
          />
        );
      })}
    </MapLayers>
  );
}

function TourControls({ tour, setTour }: { tour: Tour; setTour: (t: Tour) => void }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmStop, setConfirmStop] = useState(false);
  const [showList, setShowList] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const isDraft = tour.status === "draft";
  const remaining = tour.stops.filter((s) => !s.result);
  const current: Stop | undefined = tour.stops.find((s) => s.id === selectedId) ?? remaining[0];
  const visitedCount = tour.stops.length - remaining.length;

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const startTour = () => run("start", async () => setTour(await api<Tour>(`/tours/${tour.id}/start/`, { method: "POST" })));
  const cancelDraft = () =>
    run("cancel", async () => {
      await api(`/tours/${tour.id}/`, { method: "DELETE" });
      navigate("/", { replace: true });
    });
  const finish = () => run("finish", async () => setTour(await api<Tour>(`/tours/${tour.id}/finish/`, { method: "POST" })));
  const record = (stop: Stop, result: ResultValue) =>
    run(result, async () => {
      const updated = await api<Tour>(`/tours/${tour.id}/stops/${stop.id}/result/`, { method: "POST", body: { result } });
      setSelectedId(null);
      if (updated.stops.every((s) => s.result)) {
        setTour(await api<Tour>(`/tours/${tour.id}/finish/`, { method: "POST" }));
      } else {
        setTour(updated);
      }
    });

  const layers = (
    <>
      <TourLayers
        tour={tour}
        current={current}
        onSelect={isDraft ? undefined : (id) => (setSelectedId(id), setShowList(false))}
      />
      {!isDraft && current && (
        <MapLayers>
          <FlyTo point={[current.address.lat, current.address.lon]} />
        </MapLayers>
      )}
    </>
  );

  if (isDraft)
    return (
      <>
        {layers}
        <Sheet
          title={`${tour.stops.length} adresse${tour.stops.length > 1 ? "s" : ""} à visiter`}
          subtitle={
            <>
              {tour.area ? `${tour.area.name} · ` : ""}
              {formatDistance(tour.route_distance_m)} · ~{formatDuration(tour.route_duration_s)} de marche
              {tour.route_approximate && " (à vol d'oiseau)"}
            </>
          }
          footer={
            <div className="grid grid-cols-[auto_1fr] gap-2">
              <Button variant="secondary" loading={busy === "cancel"} onClick={cancelDraft}>
                Annuler
              </Button>
              <Button loading={busy === "start"} onClick={startTour}>
                🚶 Démarrer la tournée
              </Button>
            </div>
          }
        >
          {tour.too_many_addresses && (
            <Alert kind="warning">
              C'est beaucoup d'adresses : on a gardé les {tour.stops.length} plus proches. Tu peux arrêter avant la fin, mais
              elles seront bloquées pour les autres pendant ta tournée.
              {tour.kind === "free" && " Pense à réduire la déviation (250 m suffisent souvent en ville)."}
            </Alert>
          )}
          {error && <Alert>{error}</Alert>}
        </Sheet>
      </>
    );

  if (showList)
    return (
      <>
        {layers}
        <Sheet
          title="Adresses de la tournée"
          subtitle={`${visitedCount} / ${tour.stops.length} visitées`}
          action={
            <button className="text-sm font-semibold text-brand-600" onClick={() => setShowList(false)}>
              Fermer
            </button>
          }
          footer={<StopTourButton confirm={confirmStop} setConfirm={setConfirmStop} busy={busy === "finish"} onStop={finish} />}
        >
          <ul className="-mx-2 divide-y divide-slate-100">
            {tour.stops.map((s) => (
              <li key={s.id}>
                <button
                  className="flex w-full items-center gap-3 rounded-xl px-2 py-3 text-left active:bg-slate-50"
                  onClick={() => {
                    setSelectedId(s.id);
                    setShowList(false);
                  }}
                >
                  <span
                    className="flex size-7 shrink-0 items-center justify-center rounded-full text-xs font-bold text-white"
                    style={{ background: s.result ? RESULT_BY_VALUE[s.result].color : s.id === current?.id ? "#c8102e" : "#2563eb" }}
                  >
                    {s.position + 1}
                  </span>
                  <span className="min-w-0 flex-1 text-sm">
                    <span className="block truncate font-semibold">{s.address.name}</span>
                    <span className="block truncate text-slate-500">{s.address.address}</span>
                  </span>
                  {s.result && <span className="text-lg">{RESULT_BY_VALUE[s.result].emoji}</span>}
                </button>
              </li>
            ))}
          </ul>
        </Sheet>
      </>
    );

  if (!current) return layers;

  return (
    <>
      {layers}
      <Sheet
        title={
          <>
            {current.address.first_name} {current.address.name}
          </>
        }
        subtitle={current.address.label}
        action={
          <a
            href={navigationUrl(current.address.lat, current.address.lon)}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 rounded-full bg-sky-600 px-4 py-2.5 text-sm font-semibold text-white active:bg-sky-700"
          >
            🧭 Y aller
          </a>
        }
        footer={<StopTourButton confirm={confirmStop} setConfirm={setConfirmStop} busy={busy === "finish"} onStop={finish} />}
      >
        <div className="flex items-center gap-3">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full bg-brand-600 transition-all" style={{ width: `${(visitedCount / tour.stops.length) * 100}%` }} />
          </div>
          <span className="text-xs font-semibold text-slate-500 tabular-nums">
            #{current.position + 1} · {visitedCount}/{tour.stops.length}
          </span>
          <button className="text-sm font-semibold text-brand-600" onClick={() => setShowList(true)}>
            Liste
          </button>
        </div>
        {current.result && (
          <p className="text-sm text-slate-500">
            Déjà marquée : {RESULT_BY_VALUE[current.result].emoji} {RESULT_BY_VALUE[current.result].label}
          </p>
        )}
        {error && <Alert>{error}</Alert>}
        <ResultButtons busy={busy} onPick={(r) => record(current, r)} />
        {selectedId !== null && (
          <Button variant="ghost" className="w-full" onClick={() => setSelectedId(null)}>
            Revenir à la prochaine adresse
          </Button>
        )}
      </Sheet>
    </>
  );
}

function StopTourButton({
  confirm,
  setConfirm,
  busy,
  onStop,
}: {
  confirm: boolean;
  setConfirm: (v: boolean) => void;
  busy: boolean;
  onStop: () => void;
}) {
  if (!confirm)
    return (
      <button className="w-full py-1.5 text-sm font-semibold text-red-700" onClick={() => setConfirm(true)}>
        🛑 Arrêter la tournée
      </button>
    );
  return (
    <div className="space-y-2">
      <p className="text-sm text-red-900">Arrêter ? Les adresses non visitées seront libérées pour les autres militant·es.</p>
      <div className="grid grid-cols-2 gap-2">
        <Button variant="secondary" onClick={() => setConfirm(false)}>
          Continuer
        </Button>
        <Button loading={busy} onClick={onStop}>
          Arrêter
        </Button>
      </div>
    </div>
  );
}

function TourSummary({ tour }: { tour: Tour }) {
  const s = tour.summary;
  const notReached = s.do_not_contact + s.address_to_retry + s.address_failure;
  return (
    <Sheet
      title="Tournée terminée 💖✊"
      subtitle="Les militant·es te remercient pour cette tournée de porte-à-porte, camarade !"
      footer={
        <div className="grid grid-cols-2 gap-2">
          <Link to="/" className="flex min-h-12 items-center justify-center rounded-2xl font-semibold text-slate-700 ring-1 ring-slate-300">
            Accueil
          </Link>
          <Link to="/tours/new/free" className="flex min-h-12 items-center justify-center rounded-2xl bg-brand-600 font-semibold text-white">
            Nouvelle tournée
          </Link>
        </div>
      }
    >
      <div className="grid grid-cols-3 gap-2 text-center">
        <Big value={s.total_success} label="succès" accent />
        <Big value={s.commitment_to_vote} label="🤝 promesses" />
        <Big value={s.good_conversation} label="👍 conversations" />
      </div>
      <div className="divide-y divide-slate-100 rounded-2xl ring-1 ring-slate-200">
        <Row label="Autres retours (absent, stérile, introuvable)" value={notReached} />
        <Row label="Adresses non visitées (libérées)" value={s.not_visited} />
      </div>
    </Sheet>
  );
}

function Big({ value, label, accent = false }: { value: number; label: string; accent?: boolean }) {
  return (
    <div className={`rounded-2xl py-3 ${accent ? "bg-brand-600 text-white" : "bg-slate-50 ring-1 ring-slate-200"}`}>
      <p className="text-2xl font-bold tabular-nums">{value}</p>
      <p className={`text-xs ${accent ? "opacity-90" : "text-slate-500"}`}>{label}</p>
    </div>
  );
}

function Row({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center justify-between gap-3 px-4 py-3 text-sm text-slate-600">
      <span>{label}</span>
      <span className="font-semibold text-slate-900 tabular-nums">{value}</span>
    </div>
  );
}
