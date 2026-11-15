import { ArrowRight, CircleStop, Clock, Flag, Footprints, House, Navigation, PartyPopper, Plus, Route as RouteIcon, Undo2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Marker, Polyline } from "react-leaflet";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, errorMessage } from "../api/client";
import type { AbsentDetail, ResultValue, Stop, Tour } from "../api/types";
import { FitBounds, FlyTo, MapLayers, PinMarker, stopIcon } from "../components/map";
import { Alert, Button, Card, OverlaySpinner, ResultButtons, Sheet, StatTile } from "../components/ui";
import { ABSENT_DETAIL_BY_VALUE, RESULT_BY_VALUE, formatDistance, formatDuration, navigationUrl } from "../lib/constants";

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
        <TourLayers tour={tour} groups={groupStops(tour.stops)} />
        <TourSummary tour={tour} />
      </>
    );
  return <TourControls tour={tour} setTour={setTour} />;
}

/** Pause on the chosen feedback before moving on to the next door. */
const ADVANCE_DELAY_MS = 700;

/** People living at the same address are visited together: one marker, one card, individual feedback. */
type Group = { key: string; stops: Stop[] };

function groupStops(stops: Stop[]): Group[] {
  const groups = new Map<string, Group>();
  for (const stop of stops) {
    const a = stop.address;
    const key = `${a.address}|${a.zip_code}|${a.city}`.toLowerCase().replace(/\s+/g, " ");
    const group = groups.get(key) ?? { key, stops: [] };
    group.stops.push(stop);
    groups.set(key, group);
  }
  return [...groups.values()];
}

function groupColor(group: Group, isCurrent: boolean): string {
  const results = new Set(group.stops.map((s) => s.result));
  if (results.has(null)) return isCurrent ? "#c8102e" : "#3f3f46";
  return results.size === 1 ? RESULT_BY_VALUE[group.stops[0].result!].color : "#71717a";
}

/** "Promesse de vote le 12 mai 2026 pour l'élection consulaire 2026", "Didier R. est déjà passé·e le … et a boîté un tract". */
function LastVisit({ visit }: { visit: NonNullable<Stop["last_visit"]> }) {
  const date = new Date(visit.at).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });
  const election = visit.election && !visit.current_election ? ` ${visit.election}` : "";
  if (visit.result === "address_to_retry")
    return (
      <span className="mt-1 block text-xs text-amber-700">
        {visit.by ?? "Quelqu'un"} est déjà passé·e le {date}
        {election} et {visit.detail ? ABSENT_DETAIL_BY_VALUE[visit.detail].past : "la personne était absente"}
      </span>
    );
  const success = visit.result === "commitment_to_vote" || visit.result === "good_conversation";
  return (
    <span className={`mt-1 block text-xs ${success ? "text-emerald-700" : "text-zinc-500"}`}>
      {RESULT_BY_VALUE[visit.result].label} le {date}
      {visit.election ? ` ${visit.election}` : ""}
      {visit.by ? ` (${visit.by})` : ""}
    </span>
  );
}

/** Full name (all first names + usage name): needed to find the right doorbell. */
function personName(stop: Stop) {
  return [stop.address.first_names || stop.address.first_name, stop.address.name].filter(Boolean).join(" ");
}

function TourLayers({
  tour,
  groups,
  currentKey,
  onSelect,
}: {
  tour: Tour;
  groups: Group[];
  currentKey?: string;
  onSelect?: (stopId: number) => void;
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
    () => [[tour.start.lat, tour.start.lon], ...groups.map((g) => [g.stops[0].address.lat, g.stops[0].address.lon] as [number, number])],
    [groups, tour.start],
  );
  const isActive = tour.status === "active";

  return (
    <MapLayers>
      <FitBounds points={allPoints} fitKey={`${tour.id}-${tour.status}`} />
      {tour.route && (
        <Polyline positions={tour.route} interactive={false} pathOptions={{ color: "#c8102e", weight: 5, opacity: 0.55, lineCap: "round", lineJoin: "round" }} />
      )}
      <Polyline positions={stopsLine} interactive={false} pathOptions={{ color: "#18181b", weight: 2, dashArray: "2 7", lineCap: "round", opacity: 0.45 }} />
      <PinMarker point={tour.start} color="#059669" label="Départ" kind="start" />
      {tour.end && <PinMarker point={tour.end} color="#18181b" label="Arrivée" kind="end" />}
      {groups.map((group) => {
        const first = group.stops[0];
        const isCurrent = isActive && group.key === currentKey;
        const color = groupColor(group, isCurrent);
        const target = group.stops.find((s) => !s.result) ?? first;
        return (
          <Marker
            // Leaflet reads `interactive` only when a marker is created: a new key when the tour starts
            // (draft → active), otherwise the markers stay unclickable until the page is reloaded.
            key={`${group.key}-${color}-${isCurrent}-${!!onSelect}`}
            position={[first.address.lat, first.address.lon]}
            icon={stopIcon(first.position + 1, color, isCurrent, isCurrent ? 34 : 28, group.stops.length)}
            zIndexOffset={isCurrent ? 1000 : 0}
            interactive={!!onSelect}
            eventHandlers={onSelect ? { click: () => onSelect(target.id) } : {}}
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
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [browsing, setBrowsing] = useState(false);

  const isDraft = tour.status === "draft";
  const groups = useMemo(() => groupStops(tour.stops), [tour.stops]);
  const remaining = tour.stops.filter((s) => !s.result);
  const current: Stop | undefined = tour.stops.find((s) => s.id === selectedId) ?? remaining[0];
  const group = current ? groups.find((g) => g.stops.some((s) => s.id === current.id)) : undefined;
  const visitedCount = tour.stops.length - remaining.length;

  // People already visited, in the order they were done: what "back" walks through.
  const history = useMemo(
    () =>
      tour.stops
        .filter((st) => st.result && st.visited_at)
        .sort((x, y) => (x.visited_at! === y.visited_at! ? x.position - y.position : x.visited_at! < y.visited_at! ? -1 : 1))
        .map((st) => st.id),
    [tour.stops],
  );

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
  const finish = () =>
    run("finish", async () => {
      if (visitedCount === 0) {
        // No door knocked: the tour is simply cancelled (addresses released, nothing recorded).
        await api(`/tours/${tour.id}/`, { method: "DELETE" });
        navigate("/", { replace: true });
        return;
      }
      setTour(await api<Tour>(`/tours/${tour.id}/finish/`, { method: "POST" }));
    });
  // After a feedback, stay a moment on the person (the chosen button shows as selected), then slide to the next door.
  const advanceTimer = useRef<number | undefined>(undefined);
  const [advancing, setAdvancing] = useState(false);
  useEffect(() => () => window.clearTimeout(advanceTimer.current), []);
  const record = (stopIds: number[], result: ResultValue, absentDetail?: AbsentDetail) =>
    run(absentDetail ? `${result}:${absentDetail}` : result, async () => {
      window.clearTimeout(advanceTimer.current);
      const stay = current?.id ?? null;
      const updated = await api<Tour>(`/tours/${tour.id}/results/`, { method: "POST", body: { stop_ids: stopIds, result, absent_detail: absentDetail ?? "" } });
      setSelectedId(stay);
      setTour(updated);
      setAdvancing(true);
      const building = groupStops(updated.stops).find((g) => g.stops.some((st) => st.id === stay));
      const nextInBuilding = building?.stops.find((st) => !st.result)?.id ?? null;
      advanceTimer.current = window.setTimeout(() => {
        setAdvancing(false);
        setBrowsing(false);
        setSelectedId(nextInBuilding);
      }, ADVANCE_DELAY_MS);
    });
  // Tapping the selected feedback again removes it: stay on the person, to visit again.
  const clear = (stopId: number) =>
    run("clear", async () => {
      window.clearTimeout(advanceTimer.current);
      setAdvancing(false);
      const updated = await api<Tour>(`/tours/${tour.id}/results/`, { method: "DELETE", query: { stop_ids: String(stopId) } });
      setBrowsing(true);
      setSelectedId(stopId);
      setTour(updated);
    });
  // Back to the previous person, their feedback still selected (tap another one to change it).
  const viewedIndex = browsing && current ? history.indexOf(current.id) : -1;
  const backId = viewedIndex > 0 ? history[viewedIndex - 1] : viewedIndex === -1 ? history.at(-1) : undefined;
  const backStop = backId !== undefined ? tour.stops.find((st) => st.id === backId) : undefined;
  const goBack = () => {
    window.clearTimeout(advanceTimer.current);
    if (advancing) {
      setAdvancing(false); // still on the person just marked: simply stay there
      setBrowsing(true);
      return;
    }
    if (backStop) {
      setBrowsing(true);
      setSelectedId(backStop.id);
    }
  };

  const layers = (
    <>
      <TourLayers
        tour={tour}
        groups={groups}
        currentKey={group?.key}
        onSelect={isDraft ? undefined : (id) => (setBrowsing(true), setSelectedId(id))}
      />
      {!isDraft && current && (
        <MapLayers>
          <FlyTo point={[current.address.lat, current.address.lon]} />
        </MapLayers>
      )}
    </>
  );

  // Viewing another door than the next one (picked on the map, or after "back"): offer to resume instead.
  const nextLink = browsing && !advancing && remaining.length > 0 && (
    <button
      type="button"
      onClick={() => (setBrowsing(false), setSelectedId(null))}
      className="flex min-w-0 items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm font-medium text-zinc-500 active:bg-zinc-100"
    >
      <span className="truncate">Aller à la prochaine adresse</span>
      <ArrowRight className="size-4 shrink-0" />
    </button>
  );

  // Discreet "back" next to "stop the tour" (footer of the visit screens).
  const backLink = (backStop || advancing) && (
    <button
      type="button"
      onClick={goBack}
      disabled={busy !== null}
      title={backStop ? `Revenir à ${personName(backStop)}` : undefined}
      className="flex min-w-0 items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm font-medium text-zinc-500 active:bg-zinc-100 disabled:opacity-60"
    >
      <Undo2 className="size-4 shrink-0" />
      <span className="truncate">Revenir au précédent</span>
    </button>
  );

  const backCard = backStop?.result && (
    <button
      type="button"
      onClick={goBack}
      className="flex w-full items-center gap-3 rounded-2xl bg-zinc-50 px-3.5 py-2.5 text-left ring-1 ring-zinc-950/5 transition active:bg-zinc-100"
    >
      <Undo2 className="size-[18px] shrink-0 text-zinc-500" />
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold">Revenir à la dernière porte</span>
        <span className="flex items-center gap-1.5 truncate text-xs text-zinc-500">
          <ResultDot value={backStop.result} small />
          <span className="truncate">
            {personName(backStop)} · {backStop.absent_detail ? ABSENT_DETAIL_BY_VALUE[backStop.absent_detail].label : RESULT_BY_VALUE[backStop.result].label}
          </span>
        </span>
      </span>
    </button>
  );

  if (isDraft)
    return (
      <>
        {layers}
        <Sheet
          title={`${tour.stops.length} personne${tour.stops.length > 1 ? "s" : ""} à visiter`}
          subtitle={`${tour.area?.name ?? "Tournée libre"} · ${groups.length} adresse${groups.length > 1 ? "s" : ""}`}
          footer={
            <div className="grid grid-cols-[auto_1fr] gap-2">
              <Button variant="secondary" icon={X} loading={busy === "cancel"} onClick={cancelDraft}>
                Annuler
              </Button>
              <Button icon={Footprints} loading={busy === "start"} onClick={startTour}>
                Démarrer la tournée
              </Button>
            </div>
          }
        >
          <div className="grid grid-cols-2 gap-2">
            <Metric icon={RouteIcon} label="Distance" value={formatDistance(tour.route_distance_m)} hint={tour.route_approximate ? "à vol d'oiseau" : undefined} />
            <Metric icon={Clock} label="Marche" value={`~${formatDuration(tour.route_duration_s)}`} />
          </div>
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

  // Everybody visited: let them correct the last feedback before closing the tour.
  if (!current || (remaining.length === 0 && selectedId === null))
    return (
      <>
        {layers}
        <Sheet
          title="Toutes les portes sont faites"
          subtitle="Vérifie ton dernier retour puis termine la tournée."
          footer={
            <Button className="w-full" icon={Flag} loading={busy === "finish"} onClick={finish}>
              Terminer la tournée
            </Button>
          }
        >
          {error && <Alert>{error}</Alert>}
          {backCard}
        </Sheet>
      </>
    );

  const people = group?.stops ?? [current];
  const stepKey = String(current.id);
  const several = people.length > 1;

  return (
    <>
      {layers}
      <Sheet
        title={
          // 1. who (the name on the doorbell)
          <span key={stepKey} className="block animate-[step-in_.35s_cubic-bezier(.2,.8,.2,1)] text-[1.6rem] leading-tight font-bold tracking-[-0.025em]">
            {personName(current)}
            {current.address.birth_year && (
              <span className="ml-2 align-middle text-base font-medium tracking-normal text-zinc-400">
                {new Date().getFullYear() - current.address.birth_year} ans
              </span>
            )}
          </span>
        }
        subtitle={
          <span key={stepKey} className="block animate-[step-in_.35s_cubic-bezier(.2,.8,.2,1)]">
            {/* 2. street and number, 3. the rest of the address in small */}
            <span className="mt-0.5 block text-lg leading-snug font-semibold text-zinc-800">{current.address.address}</span>
            <span className="block text-xs text-zinc-400">
              {current.address.zip_code} {current.address.city}
            </span>
            {current.last_visit && <LastVisit visit={current.last_visit} />}
          </span>
        }
        action={
          <a
            href={navigationUrl(current.address.lat, current.address.lon)}
            target="_blank"
            rel="noreferrer"
            className="flex min-h-10 items-center gap-1.5 rounded-xl bg-sky-600 px-3.5 text-sm font-semibold text-white active:bg-sky-700"
          >
            <Navigation className="size-4" strokeWidth={2.25} /> Y aller
          </a>
        }
        footer={<StopTourButton confirm={confirmStop} setConfirm={setConfirmStop} busy={busy === "finish"} onStop={finish} back={nextLink || backLink} empty={visitedCount === 0} />}
      >
        <div className="flex items-center gap-3">
          <span className="flex h-7 items-center rounded-lg bg-zinc-900 px-2 text-xs font-semibold text-white tabular-nums">#{people[0].position + 1}</span>
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-zinc-100">
            <div className="h-full rounded-full bg-brand-600 transition-all" style={{ width: `${(visitedCount / tour.stops.length) * 100}%` }} />
          </div>
          <span className="text-xs font-semibold text-zinc-500 tabular-nums">
            {visitedCount}/{tour.stops.length}
          </span>
        </div>

        <div key={stepKey} className="space-y-3 animate-[step-in_.35s_cubic-bezier(.2,.8,.2,1)]">
          {several && (
            // Same building: one person at a time; tap someone to switch to them.
            <div>
              <p className="mb-1.5 text-[13px] font-semibold text-zinc-500">À cette adresse ({people.length})</p>
              <div className="-mx-1 divide-y divide-zinc-950/[0.06]">
                {people.map((st) => {
                  const on = st.id === current.id;
                  return (
                    <button
                      key={st.id}
                      type="button"
                      onClick={() => {
                        if (on) return;
                        window.clearTimeout(advanceTimer.current);
                        setAdvancing(false);
                        setBrowsing(true);
                        setSelectedId(st.id);
                      }}
                      aria-current={on}
                      className={`flex w-full items-center gap-3 rounded-xl px-2 py-2.5 text-left transition ${on ? "bg-brand-50" : "active:bg-zinc-50"}`}
                    >
                      <span className={`size-4 shrink-0 rounded-full ${on ? "border-[5px] border-brand-600" : "border-2 border-zinc-300"}`} />
                      <span className={`min-w-0 flex-1 truncate text-[15px] ${on ? "font-semibold text-brand-700" : "font-medium"}`}>{personName(st)}</span>
                      {st.result ? <ResultDot value={st.result} /> : <span className="text-xs text-zinc-400">à faire</span>}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {error && <Alert>{error}</Alert>}
          <ResultButtons
            busy={busy}
            selected={current.result}
            selectedDetail={current.absent_detail}
            onPick={(r, d) => record([current.id], r, d)}
            onClear={() => clear(current.id)}
          />
        </div>
      </Sheet>
    </>
  );
}

function StopTourButton({
  confirm,
  setConfirm,
  busy,
  onStop,
  back,
  empty = false,
}: {
  confirm: boolean;
  setConfirm: (v: boolean) => void;
  busy: boolean;
  onStop: () => void;
  back?: ReactNode;
  /** No door knocked yet: stopping cancels the tour without recording anything. */
  empty?: boolean;
}) {
  if (!confirm)
    return (
      <div className="flex items-center justify-between gap-2">
        {back || <span />}
        <button
          className="flex shrink-0 items-center gap-2 rounded-lg px-2 py-1.5 text-sm font-semibold text-red-600 active:bg-red-50"
          onClick={() => setConfirm(true)}
        >
          <CircleStop className="size-4" /> Arrêter la tournée
        </button>
      </div>
    );
  return (
    <div className="space-y-2">
      <p className="text-sm text-zinc-700">
        {empty
          ? "Arrêter ? Aucune porte n'a été frappée : la tournée sera annulée, sans rien enregistrer."
          : "Arrêter ? Les adresses non visitées seront libérées pour les autres militant·es."}
      </p>
      <div className="grid grid-cols-2 gap-2">
        <Button variant="secondary" onClick={() => setConfirm(false)}>
          Continuer
        </Button>
        <Button variant="dark" icon={CircleStop} loading={busy} onClick={onStop}>
          Arrêter
        </Button>
      </div>
    </div>
  );
}

function TourSummary({ tour }: { tour: Tour }) {
  const s = tour.summary;
  const PromiseIcon = RESULT_BY_VALUE.commitment_to_vote.icon;
  return (
    <Sheet
      title={
        <span className="flex items-center gap-2">
          Tournée terminée <PartyPopper className="size-5 text-brand-600" />
        </span>
      }
      subtitle="Les militant·es te remercient pour cette tournée de porte-à-porte, camarade !"
      footer={
        <div className="grid grid-cols-2 gap-2">
          <Link to="/" className="flex min-h-12 items-center justify-center gap-2 rounded-2xl font-semibold text-zinc-800 ring-1 ring-zinc-950/10 active:bg-zinc-50">
            <House className="size-[18px]" /> Accueil
          </Link>
          <Link
            to="/tours/new/free"
            className="flex min-h-12 items-center justify-center gap-2 rounded-2xl bg-brand-600 font-semibold text-white active:bg-brand-700"
          >
            <Plus className="size-[18px]" /> Nouvelle tournée
          </Link>
        </div>
      }
    >
      {/* promesses de vote first (highlighted), then bonnes conversations, then absent·es */}
      <div className="grid grid-cols-3 gap-2">
        <StatTile value={s.commitment_to_vote} label={`promesse${s.commitment_to_vote > 1 ? "s" : ""} de vote`} icon={PromiseIcon} accent />
        <StatTile value={s.good_conversation} label={`bonne${s.good_conversation > 1 ? "s" : ""} conversation${s.good_conversation > 1 ? "s" : ""}`} icon={RESULT_BY_VALUE.good_conversation.icon} />
        <StatTile value={s.address_to_retry} label={`absent·e${s.address_to_retry > 1 ? "s" : ""}`} icon={RESULT_BY_VALUE.address_to_retry.icon} />
      </div>

      {(s.do_not_contact > 0 || s.address_failure > 0 || s.not_visited > 0) && (
        <Card className="divide-y divide-zinc-950/5">
          {s.do_not_contact > 0 && <Row label="Ne pas déranger" value={s.do_not_contact} />}
          {s.address_failure > 0 && <Row label="Adresses introuvables" value={s.address_failure} />}
          {s.not_visited > 0 && <Row label="Adresses non visitées (libérées)" value={s.not_visited} />}
        </Card>
      )}
    </Sheet>
  );
}

function Metric({ icon: Icon, label, value, hint }: { icon: typeof Clock; label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-2xl bg-zinc-50 p-3 ring-1 ring-zinc-950/5">
      <p className="flex items-center gap-1.5 text-xs text-zinc-500">
        <Icon className="size-3.5" /> {label}
      </p>
      <p className="mt-1 text-lg font-semibold tracking-tight tabular-nums">{value}</p>
      {hint && <p className="text-[11px] text-zinc-400">{hint}</p>}
    </div>
  );
}

function ResultDot({ value, small = false }: { value: ResultValue; small?: boolean }) {
  const r = RESULT_BY_VALUE[value];
  return (
    <span className={`flex shrink-0 items-center justify-center rounded-full text-white ${r.disc} ${small ? "size-4" : "size-6"}`} title={r.label}>
      <r.icon className={small ? "size-2.5" : "size-3.5"} strokeWidth={2.5} />
    </span>
  );
}

function Row({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center justify-between gap-3 px-4 py-3 text-sm text-zinc-600">
      <span>{label}</span>
      <span className="font-semibold text-zinc-900 tabular-nums">{value}</span>
    </div>
  );
}
