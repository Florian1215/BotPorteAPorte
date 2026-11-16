import type { FeatureCollection } from "geojson";
import L from "leaflet";
import { ChevronRight, FileUp, LandPlot, RefreshCw, SlidersHorizontal, Sparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Marker, useMap, useMapEvents } from "react-leaflet";
import { useNavigate } from "react-router-dom";

import { api, errorMessage } from "../api/client";
import type {
  DistrictDetail,
  DistrictProgress,
  DistrictImport,
  DistrictMap,
  ImportInspection,
  ScoreCriterionKey,
  ScoreWeights,
} from "../api/types";
import { FitBounds, FlyTo, MapLayers } from "../components/map";
import { BackContext } from "../context/BackContext";
import { Alert, Button, Card, EmptyState, Field, Loading, SectionTitle, Sheet, Spinner, inputClass } from "../components/ui";
import { CRITERION_FORMAT, CRITERION_HELP, SCORE_CLASSES, scoreColor } from "../lib/constants";

type MapDistrict = DistrictMap["districts"][number];

/** Labels (score · % doors done) only from this zoom on: below, the colours alone tell the story. */
const LABEL_MIN_ZOOM = 14;
const MAX_LABELS = 300;

/**
 * Polling districts of the organization (responsables): coloured by score, tap one for its details.
 * Districts come from the official electoral map (imported here) and cannot be edited.
 */
export default function Districts() {
  const [data, setData] = useState<DistrictMap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [panel, setPanel] = useState<"overview" | "weights" | "import">("overview");
  // Bumped when leaving a district: the map zooms back out on all the zones.
  const [overviewCount, setOverviewCount] = useState(0);

  const load = useCallback(() => {
    api<DistrictMap>("/manage/districts/")
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(errorMessage(e)));
  }, []);
  useEffect(load, [load]);

  // While an import runs, poll its status, then reload the map.
  const running = data?.import?.status === "running";
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(async () => {
      try {
        const job = await api<DistrictImport | null>("/manage/districts/import/");
        if (job?.status !== "running") {
          window.clearInterval(timer);
          load();
          if (job?.status === "done") setPanel("overview");
        }
      } catch {
        /* keep polling */
      }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [running, load]);

  const districts = data?.districts ?? [];
  const labelPoints = useMemo(
    () => districts.flatMap((d) => (d.label ? [[d.label.lat, d.label.lon] as [number, number]] : [])),
    [districts],
  );
  const empty = data !== null && districts.length === 0;
  const selectedLabel = districts.find((d) => d.id === selectedId)?.label;

  let sheet;
  if (!data) {
    sheet = (
      <Sheet title="Zones" locate={false}>
        {error ? <Alert>{error}</Alert> : <Loading />}
      </Sheet>
    );
  } else if (selectedId !== null) {
    // "Back" closes the district and returns to the list of all zones (instead of leaving the page).
    sheet = (
      <BackContext.Provider
        value={() => {
          setSelectedId(null);
          setOverviewCount((n) => n + 1);
        }}
      >
        <DistrictSheet id={selectedId} />
      </BackContext.Provider>
    );
  } else if (empty || panel === "import" || running) {
    sheet = <ImportSheet data={data} onStarted={load} onCancel={empty ? undefined : () => setPanel("overview")} />;
  } else if (panel === "weights") {
    sheet = (
      <WeightsSheet
        data={data}
        onDone={(changed) => {
          setPanel("overview");
          if (changed) load();
        }}
      />
    );
  } else {
    sheet = <OverviewSheet data={data} onSelect={setSelectedId} onPanel={setPanel} />;
  }

  return (
    <>
      <MapLayers>
        {districts.length > 0 && (
          <>
            <FitBounds points={labelPoints} fitKey={`districts-${districts.length}-${data?.import?.id}-${overviewCount}`} />
            <DistrictLayer districts={districts} selectedId={selectedId} onSelect={setSelectedId} />
            <DistrictLabels districts={districts} onSelect={setSelectedId} />
            <FlyTo point={selectedLabel ? [selectedLabel.lat, selectedLabel.lon] : null} zoom={15} />
          </>
        )}
      </MapLayers>
      {sheet}
    </>
  );
}

// --------------------------------------------------------------------------- map layers

function districtStyle(score: number, selected: boolean): L.PathOptions {
  return selected
    ? { fillColor: scoreColor(score), fillOpacity: 0.7, color: "#18181b", weight: 3, opacity: 1 }
    : { fillColor: scoreColor(score), fillOpacity: 0.5, color: "#ffffff", weight: 0.8, opacity: 0.9 };
}

/** All districts in one canvas layer (thousands of polygons: drawn imperatively, restyled on selection). */
function DistrictLayer({
  districts,
  selectedId,
  onSelect,
}: {
  districts: MapDistrict[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  const map = useMap();
  const layer = useRef<L.GeoJSON | null>(null);
  const select = useRef(onSelect);
  select.current = onSelect;

  useEffect(() => {
    const collection: FeatureCollection = {
      type: "FeatureCollection",
      features: districts.map((d) => ({ type: "Feature", properties: { id: d.id, score: d.score }, geometry: d.geometry as never })),
    };
    const geo = L.geoJSON(collection, {
      style: (f) => districtStyle(f?.properties.score ?? 0, false),
      onEachFeature: (f, l) =>
        l.on("click", (e) => {
          L.DomEvent.stopPropagation(e);
          select.current(f.properties.id);
        }),
    }).addTo(map);
    layer.current = geo;
    return () => {
      geo.remove();
      layer.current = null;
    };
  }, [districts, map]);

  useEffect(() => {
    layer.current?.eachLayer((l) => {
      const path = l as L.Path & { feature?: { properties: { id: number; score: number } } };
      if (!path.feature) return;
      const selected = path.feature.properties.id === selectedId;
      path.setStyle(districtStyle(path.feature.properties.score, selected));
      if (selected) path.bringToFront();
    });
  }, [selectedId, districts]);

  return null;
}

const labelIcons = new Map<string, L.DivIcon>();

function labelIcon(score: number, donePct: number): L.DivIcon {
  const key = `${Math.round(score)}|${Math.round(donePct)}`;
  let icon = labelIcons.get(key);
  if (!icon) {
    const done = donePct > 0 ? `<small>· ${Math.round(donePct)} %</small>` : "";
    icon = L.divIcon({ className: "", html: `<div class="district-label">${Math.round(score)}${done}</div>`, iconSize: [0, 0] });
    labelIcons.set(key, icon);
  }
  return icon;
}

/** Score (and share of doors done, when some were) on each district in view, once zoomed in. */
function DistrictLabels({ districts, onSelect }: { districts: MapDistrict[]; onSelect: (id: number) => void }) {
  const map = useMap();
  const [view, setView] = useState(() => ({ zoom: map.getZoom(), bounds: map.getBounds() }));
  useMapEvents({ moveend: () => setView({ zoom: map.getZoom(), bounds: map.getBounds() }) });

  const visible = useMemo(() => {
    if (view.zoom < LABEL_MIN_ZOOM) return [];
    return districts.filter((d) => d.label && view.bounds.contains([d.label.lat, d.label.lon])).slice(0, MAX_LABELS);
  }, [districts, view]);

  return (
    <>
      {visible.map((d) => (
        <Marker
          key={d.id}
          position={[d.label!.lat, d.label!.lon]}
          icon={labelIcon(d.score, d.done_pct)}
          eventHandlers={{ click: () => onSelect(d.id) }}
        />
      ))}
    </>
  );
}

// --------------------------------------------------------------------------- overview

function ScoreLegend() {
  return (
    <div>
      <div className="flex gap-0.5 overflow-hidden rounded-lg">
        {[...SCORE_CLASSES].reverse().map((c) => (
          <div key={c.min} className="flex-1">
            <div className="h-2.5" style={{ background: c.color }} />
            <p className="mt-1 text-center text-[11px] text-zinc-500 tabular-nums">{c.label}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function ScoreBadge({ score, large = false }: { score: number; large?: boolean }) {
  const dark = score >= 40;
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center rounded-xl font-bold tabular-nums ${
        large ? "h-12 min-w-12 px-2 text-xl" : "h-8 min-w-8 px-1.5 text-sm"
      } ${dark ? "text-white" : "text-zinc-900"}`}
      style={{ background: scoreColor(score) }}
    >
      {Math.round(score)}
    </span>
  );
}

function OverviewSheet({
  data,
  onSelect,
  onPanel,
}: {
  data: DistrictMap;
  onSelect: (id: number) => void;
  onPanel: (p: "weights" | "import") => void;
}) {
  const best = data.districts.slice(0, 3); // already sorted by score
  return (
    <Sheet
      title={`Zones (${data.districts.length.toLocaleString("fr")})`}
      subtitle={data.election || "Bureaux de vote"}
      locate={false}
    >
      <ScoreLegend />
      <div className="grid grid-cols-2 gap-2">
        <Button variant="secondary" size="sm" icon={SlidersHorizontal} onClick={() => onPanel("weights")}>
          Pondération
        </Button>
        <Button variant="secondary" size="sm" icon={RefreshCw} onClick={() => onPanel("import")}>
          Réimporter
        </Button>
      </div>

      <SectionTitle>Meilleurs scores</SectionTitle>
      <div className="space-y-2">
        {best.map((d) => (
          <button
            key={d.id}
            onClick={() => onSelect(d.id)}
            className="flex w-full items-center gap-3 rounded-2xl bg-white p-3 text-left ring-1 ring-zinc-950/[0.08] active:bg-zinc-50"
          >
            <ScoreBadge score={d.score} />
            <div className="min-w-0 flex-1">
              <p className="truncate font-semibold tracking-tight">{d.name}</p>
              {d.done_pct > 0 && <p className="text-xs text-zinc-500 tabular-nums">{d.done_pct.toLocaleString("fr")} % des portes faites</p>}
            </div>
            <ChevronRight className="size-5 shrink-0 text-zinc-300" />
          </button>
        ))}
      </div>
    </Sheet>
  );
}

// --------------------------------------------------------------------------- district details

function formatPct(v: number | null | undefined, digits = 1) {
  return v == null ? "—" : `${v.toLocaleString("fr", { maximumFractionDigits: digits })} %`;
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-zinc-50 px-3 py-2 ring-1 ring-zinc-950/5">
      <p className="text-[15px] font-semibold tracking-tight tabular-nums">{value}</p>
      <p className="text-xs text-zinc-500">{label}</p>
    </div>
  );
}

function DistrictSheet({ id }: { id: number }) {
  const navigate = useNavigate();
  const [detail, setDetail] = useState<DistrictDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDetail(null);
    setError(null);
    api<DistrictDetail>(`/manage/districts/${id}/`).then(setDetail).catch((e) => setError(errorMessage(e)));
  }, [id]);

  if (!detail)
    return (
      <Sheet title="Bureau de vote" locate={false}>
        {error ? <Alert>{error}</Alert> : <Loading />}
      </Sheet>
    );

  const d = detail;
  const p = d.progress;
  const totalWeight = d.score_parts.reduce((sum, part) => sum + (part.rank != null ? part.weight : 0), 0);
  const maxPartyPct = Math.max(1, ...d.parties.map((x) => x.pct ?? 0));

  return (
    <Sheet
      title={d.name}
      subtitle={d.election || undefined}
      locate={false}
      footer={
        <Button
          className="w-full"
          icon={Sparkles}
          disabled={p.to_visit === 0}
          onClick={() => navigate(`/tours/new/predefined?zone=${d.id}`)}
        >
          {p.to_visit > 0 ? `Préparer une tournée ici (${p.to_visit} à visiter)` : "Aucune adresse à visiter ici"}
        </Button>
      }
    >
      <div className="flex items-center gap-3">
        <ScoreBadge score={d.score} large />
        <div className="min-w-0 flex-1">
          <p className="font-semibold tracking-tight">Score {Math.round(d.score)} / 100</p>
          <p className="text-sm text-zinc-500 tabular-nums">
            {p.total > 0
              ? `${p.total.toLocaleString("fr")} Français·e${p.total > 1 ? "s" : ""} · ${formatPct(p.done_pct, 0)} fait`
              : "Aucune adresse de la liste dans ce bureau"}
          </p>
        </div>
      </div>

      {p.total > 0 && (
        <>
          <SectionTitle>Français·es de la zone</SectionTitle>
          <ProgressCard progress={p} />
          <AgePyramid ages={d.ages} />
        </>
      )}

      <SectionTitle>Détail du score</SectionTitle>
      <Card className="divide-y divide-zinc-950/[0.06]">
        {d.score_parts.map((part) => {
          const counts = part.rank != null && part.weight > 0;
          return (
            <div key={part.key} className={`px-3.5 py-2.5 ${counts ? "" : "opacity-60"}`} title={CRITERION_HELP[part.key]}>
              <div className="flex items-baseline justify-between gap-2">
                <p className="text-sm font-semibold">{part.label}</p>
                <p className="text-sm tabular-nums text-zinc-700">
                  {part.value != null ? CRITERION_FORMAT[part.key](part.value) : "Pas de donnée"}
                </p>
              </div>
              <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-zinc-100">
                {part.rank != null && (
                  <div className="h-full rounded-full bg-brand-600" style={{ width: `${Math.max(2, part.rank * 100)}%` }} />
                )}
              </div>
              <p className="mt-1 text-[11px] text-zinc-500 tabular-nums">
                {part.rank == null
                  ? "Ne compte pas : donnée manquante"
                  : `Mieux que ${Math.round(part.rank * 100)} % des bureaux · ${
                      counts ? `pèse ${Math.round((100 * part.weight) / totalWeight)} % du score` : "ne compte pas (poids 0)"
                    }`}
              </p>
            </div>
          );
        })}
      </Card>

      <SectionTitle>Résultats</SectionTitle>
      <div className="grid grid-cols-2 gap-2">
        <Metric label="Die Linke" value={formatPct(d.linke_pct)} />
        <Metric label="Participation" value={formatPct(d.turnout_pct)} />
      </div>
      {d.parties.length > 0 && (
        <Card className="space-y-1.5 p-3.5">
          {d.parties.map((party) => (
            <div key={party.name} className="flex items-center gap-2 text-sm">
              <span className={`w-24 shrink-0 truncate ${party.name === "Die Linke" ? "font-semibold" : "text-zinc-600"}`}>{party.name}</span>
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-zinc-100">
                <div
                  className={`h-full rounded-full ${party.name === "Die Linke" ? "bg-brand-600" : "bg-zinc-400"}`}
                  style={{ width: `${((party.pct ?? 0) / maxPartyPct) * 100}%` }}
                />
              </div>
              <span className="w-14 shrink-0 text-right tabular-nums text-zinc-700">{formatPct(party.pct)}</span>
            </div>
          ))}
        </Card>
      )}

      <SectionTitle>Population (Zensus 2022)</SectionTitle>
      {d.population == null ? (
        <p className="text-sm text-zinc-500">Données du recensement non chargées pour cette zone.</p>
      ) : (
        <div className="grid grid-cols-2 gap-2">
          <Metric label="Habitant·es" value={d.population.toLocaleString("fr")} />
          <Metric label="Densité" value={d.density != null ? `${d.density.toLocaleString("fr")} /km²` : "—"} />
          <Metric label="18–29 ans" value={formatPct(d.share_18_29 != null ? d.share_18_29 * 100 : null)} />
          <Metric label="65 ans et plus" value={formatPct(d.share_65_plus != null ? d.share_65_plus * 100 : null)} />
          <Metric label="Étranger·es" value={formatPct(d.share_foreign != null ? d.share_foreign * 100 : null)} />
          <Metric
            label="Loyer net moyen"
            value={d.rent_m2 != null ? `${d.rent_m2.toLocaleString("fr", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €/m²` : "—"}
          />
        </div>
      )}
      <div className="grid grid-cols-2 gap-2">
        <Metric label="Bas revenus (minima sociaux)" value={formatPct(d.low_income != null ? d.low_income * 100 : null)} />
      </div>
    </Sheet>
  );
}

/** What is left to do among the French voters of the district, as numbers and as one stacked bar. */
function ProgressCard({ progress: p }: { progress: DistrictProgress }) {
  const n = (v: number) => v.toLocaleString("fr");
  const segments = [
    { key: "done", value: p.done, className: "bg-brand-600", label: "fait (personne vue, ou adresse réglée)" },
    { key: "leafleted", value: p.leafleted, className: "bg-brand-200", label: "boîté, personne pas vue" },
    { key: "not_leafleted", value: p.not_leafleted, className: "bg-zinc-200", label: "pas encore boîté" },
  ];
  return (
    <Card className="space-y-3 p-3.5">
      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <p className="text-xl font-semibold tracking-tight tabular-nums">{n(p.total)}</p>
          <p className="text-xs text-zinc-500">Français·es</p>
        </div>
        <div>
          <p className="text-xl font-semibold tracking-tight tabular-nums">{n(p.remaining)}</p>
          <p className="text-xs text-zinc-500">restant à faire</p>
        </div>
        <div>
          <p className="text-xl font-semibold tracking-tight text-brand-700 tabular-nums">{formatPct(p.done_pct, 0)}</p>
          <p className="text-xs text-zinc-500">déjà fait</p>
        </div>
      </div>
      <div className="flex h-2.5 overflow-hidden rounded-full bg-zinc-100">
        {segments.map((seg) => seg.value > 0 && <div key={seg.key} className={seg.className} style={{ width: `${(100 * seg.value) / p.total}%` }} />)}
      </div>
      <ul className="space-y-1 text-sm">
        {segments.map((seg) => (
          <li key={seg.key} className="flex items-center gap-2">
            <span className={`size-2.5 shrink-0 rounded-full ${seg.className}`} />
            <span className="w-10 shrink-0 text-right font-semibold tabular-nums">{n(seg.value)}</span>
            <span className="text-zinc-600">{seg.label}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

/** Age of the French voters of the district: oldest on top, bars centred like a pyramid. */
function AgePyramid({ ages }: { ages: DistrictDetail["ages"] }) {
  const known = ages.groups.reduce((sum, g) => sum + g.count, 0);
  const max = Math.max(1, ...ages.groups.map((g) => g.count));
  return (
    <Card className="space-y-1 p-3.5">
      <p className="pb-1 text-sm font-semibold">Pyramide des âges</p>
      {known === 0 ? (
        <p className="text-sm text-zinc-500">Année de naissance inconnue pour ces personnes.</p>
      ) : (
        [...ages.groups].reverse().map((g) => (
          <div key={g.label} className="flex items-center gap-2 text-xs">
            <span className="w-11 shrink-0 text-zinc-500 tabular-nums">{g.label}</span>
            <div className="flex h-4 flex-1 justify-center">
              <div className="h-full rounded bg-brand-600/80" style={{ width: `${(100 * g.count) / max}%`, minWidth: g.count ? 3 : 0 }} />
            </div>
            <span className="w-16 shrink-0 text-right tabular-nums text-zinc-700">
              {g.count} <span className="text-zinc-400">· {Math.round((100 * g.count) / known)} %</span>
            </span>
          </div>
        ))
      )}
      {ages.unknown > 0 && known > 0 && <p className="pt-1 text-[11px] text-zinc-500">{ages.unknown} sans année de naissance</p>}
    </Card>
  );
}

// --------------------------------------------------------------------------- score weights

function WeightsSheet({ data, onDone }: { data: DistrictMap; onDone: (changed: boolean) => void }) {
  const [weights, setWeights] = useState<ScoreWeights>(data.weights);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const total = Object.values(weights).reduce((a, b) => a + b, 0);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await api("/manage/score-weights/", { method: "PUT", body: weights });
      onDone(true);
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  };

  return (
    <Sheet
      title="Pondération du score"
      subtitle="Ce qui compte le plus pour choisir où faire du porte-à-porte."
      locate={false}
      footer={
        <div className="grid grid-cols-2 gap-2">
          <Button variant="secondary" onClick={() => onDone(false)} disabled={busy}>
            Annuler
          </Button>
          <Button onClick={save} loading={busy} disabled={total === 0}>
            Recalculer
          </Button>
        </div>
      }
    >
      {error && <Alert>{error}</Alert>}
      {data.criteria.map((c) => {
        const share = total ? Math.round((100 * weights[c.key]) / total) : 0;
        return (
          <label key={c.key} className="block">
            <div className="flex items-baseline justify-between">
              <span className="text-sm font-semibold">{c.label}</span>
              <span className="text-sm text-zinc-600 tabular-nums">{share} %</span>
            </div>
            <input
              type="range"
              min={0}
              max={100}
              step={5}
              value={weights[c.key]}
              onChange={(e) => setWeights({ ...weights, [c.key]: Number(e.target.value) })}
              className="mt-1 w-full accent-brand-600"
            />
            <span className="block text-xs text-zinc-500">{CRITERION_HELP[c.key as ScoreCriterionKey]}</span>
          </label>
        );
      })}
      {total === 0 && <Alert kind="warning">Au moins un critère doit compter.</Alert>}
    </Sheet>
  );
}

// --------------------------------------------------------------------------- import

type Mapping = {
  geo_id: string;
  geo_name: string;
  sheet: string;
  res_id: string;
  linke: string;
  valid: string;
  eligible: string;
  voters: string;
  parties: string[];
  election: string;
};

function guess(columns: string[], pattern: RegExp, fallback = ""): string {
  return columns.find((c) => pattern.test(c)) ?? fallback;
}

function guessMapping(info: ImportInspection, previous?: Mapping): Mapping {
  const cols = info.columns;
  const props = info.geometry_properties;
  return {
    geo_id: previous?.geo_id || guess(props, /bezirk|wbz|wahl|stimm|nr|id|code/i, props[0] ?? ""),
    geo_name: previous?.geo_name ?? "",
    sheet: info.sheet ?? "",
    res_id: guess(cols, /bezirk|wbz|stimm|nr|id|code/i, cols[0] ?? ""),
    linke: guess(cols, /linke/i),
    valid: guess(cols, /g(ü|ue)ltig|valid/i),
    eligible: guess(cols, /berechtigt/i),
    voters: guess(cols, /w(ä|ae)hler|w(ä|ae)hlende|votant/i),
    parties: [],
    election: previous?.election ?? "",
  };
}

function ImportSheet({
  data,
  onStarted,
  onCancel,
}: {
  data: DistrictMap;
  onStarted: () => void;
  onCancel?: () => void;
}) {
  const job = data.import;
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [geometry, setGeometry] = useState<File | null>(null);
  const [results, setResults] = useState<File | null>(null);
  const [info, setInfo] = useState<ImportInspection | null>(null);
  const [mapping, setMapping] = useState<Mapping | null>(null);

  const run = async (key: string, action: () => Promise<unknown>) => {
    setBusy(key);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const startPreset = (preset: string) =>
    run(preset, async () => {
      await api("/manage/districts/import/", { method: "POST", body: { preset } });
      onStarted();
    });

  const inspect = (sheet?: string) =>
    run("inspect", async () => {
      let next: ImportInspection;
      if (info && sheet !== undefined) {
        next = await api<ImportInspection>("/manage/districts/import/inspect/", {
          method: "POST",
          body: { import_id: info.import_id, sheet },
        });
      } else {
        const body = new FormData();
        body.append("geometry", geometry!);
        body.append("results", results!);
        next = await api<ImportInspection>("/manage/districts/import/inspect/", { method: "POST", body });
      }
      setInfo(next);
      setMapping(guessMapping(next, mapping ?? undefined));
    });

  const startCustom = () =>
    run("start", async () => {
      await api(`/manage/districts/import/${info!.import_id}/start/`, { method: "POST", body: mapping });
      onStarted();
    });

  if (job?.status === "running")
    return (
      <Sheet title="Import en cours" subtitle="Téléchargement des fichiers, recensement et calcul des scores." locate={false}>
        <div className="flex items-center gap-3 rounded-2xl bg-zinc-50 p-4 text-sm text-zinc-600 ring-1 ring-zinc-950/5">
          <Spinner className="size-5 text-brand-600" />
          Ça prend en général moins d'une minute. Tu peux quitter cette page.
        </div>
      </Sheet>
    );

  const replaceWarning = data.districts.length > 0 && (
    <Alert kind="warning">
      L'import remplace les {data.districts.length.toLocaleString("fr")} bureaux actuels. Les tournées passées gardent leurs résultats.
    </Alert>
  );

  return (
    <Sheet
      title="Importer les bureaux de vote"
      locate={false}
      action={
        onCancel && (
          <Button variant="secondary" size="sm" onClick={onCancel}>
            Retour
          </Button>
        )
      }
    >
      {job?.status === "failed" && <Alert>L'import a échoué : {job.message}</Alert>}
      {error && <Alert>{error}</Alert>}
      {replaceWarning}
      {data.districts.length === 0 && !job && (
        <EmptyState icon={LandPlot} title="Pas encore de zones">
        </EmptyState>
      )}

      {!info && (
        <>
          <SectionTitle>En un clic</SectionTitle>
          {data.presets.map((preset) => (
            <button
              key={preset.key}
              onClick={() => startPreset(preset.key)}
              disabled={busy !== null}
              className="flex w-full items-center gap-3 rounded-2xl bg-white p-3.5 text-left ring-1 ring-zinc-950/[0.08] active:bg-zinc-50 disabled:opacity-60"
            >
              <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700">
                {busy === preset.key ? <Spinner className="size-5" /> : <LandPlot className="size-5" />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block font-semibold tracking-tight">{preset.label}</span>
                <span className="block text-xs text-zinc-500">{preset.description}</span>
              </span>
              <ChevronRight className="size-5 shrink-0 text-zinc-300" />
            </button>
          ))}

          <SectionTitle>Autre ville</SectionTitle>
          <Card className="space-y-3 p-3.5">
            <FilePick
              label="Carte des bureaux (GeoJSON)"
              accept=".geojson,.json,application/geo+json,application/json"
              file={geometry}
              onPick={setGeometry}
            />
            <FilePick label="Résultats par bureau (CSV ou Excel)" accept=".csv,.xlsx,.xls,.txt" file={results} onPick={setResults} />
            <Button
              variant="secondary"
              className="w-full"
              icon={FileUp}
              disabled={!geometry || !results}
              loading={busy === "inspect"}
              onClick={() => inspect()}
            >
              Lire les fichiers
            </Button>
          </Card>
        </>
      )}

      {info && mapping && (
        <MappingForm
          info={info}
          mapping={mapping}
          setMapping={setMapping}
          onSheet={(sheet) => inspect(sheet)}
          busy={busy}
          onStart={startCustom}
          onBack={() => {
            setInfo(null);
            setMapping(null);
          }}
        />
      )}
    </Sheet>
  );
}

function FilePick({ label, accept, file, onPick }: { label: string; accept: string; file: File | null; onPick: (f: File | null) => void }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <div>
      <p className="mb-1.5 text-[13px] font-semibold text-zinc-700">{label}</p>
      <input ref={input} type="file" accept={accept} className="hidden" onChange={(e) => onPick(e.target.files?.[0] ?? null)} />
      <button
        type="button"
        onClick={() => input.current?.click()}
        className="flex min-h-11 w-full items-center gap-2 rounded-xl bg-zinc-100 px-3.5 text-left text-sm active:bg-zinc-200"
      >
        <FileUp className="size-4 shrink-0 text-zinc-500" />
        <span className={`truncate ${file ? "font-medium text-zinc-900" : "text-zinc-500"}`}>{file ? file.name : "Choisir un fichier"}</span>
      </button>
    </div>
  );
}

function ColumnSelect({
  label,
  value,
  options,
  onChange,
  optional = false,
  hint,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
  optional?: boolean;
  hint?: string;
}) {
  return (
    <Field label={`${label}${optional ? " (facultatif)" : ""}`} hint={hint}>
      <select className={inputClass} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{optional ? "— aucune —" : "— choisir —"}</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </Field>
  );
}

function MappingForm({
  info,
  mapping,
  setMapping,
  onSheet,
  busy,
  onStart,
  onBack,
}: {
  info: ImportInspection;
  mapping: Mapping;
  setMapping: (m: Mapping) => void;
  onSheet: (sheet: string) => void;
  busy: string | null;
  onStart: () => void;
  onBack: () => void;
}) {
  const set = (patch: Partial<Mapping>) => setMapping({ ...mapping, ...patch });
  const ready = mapping.geo_id && mapping.res_id && mapping.linke && mapping.valid;
  const partyOptions = info.columns.filter((c) => ![mapping.res_id, mapping.valid, mapping.eligible, mapping.voters].includes(c));
  const sample = (prop: string) =>
    info.geometry_preview
      .map((f) => f[prop])
      .filter((v) => v != null && v !== "")
      .slice(0, 3)
      .join(", ");

  return (
    <>
      <SectionTitle
        action={
          <Button variant="ghost" size="sm" onClick={onBack}>
            Changer de fichiers
          </Button>
        }
      >
        Carte : {info.n_features.toLocaleString("fr")} bureaux
      </SectionTitle>
      <ColumnSelect
        label="Identifiant du bureau"
        value={mapping.geo_id}
        options={info.geometry_properties}
        onChange={(v) => set({ geo_id: v })}
        hint={mapping.geo_id ? `Exemples : ${sample(mapping.geo_id)}` : undefined}
      />
      <ColumnSelect label="Nom du bureau" optional value={mapping.geo_name} options={info.geometry_properties} onChange={(v) => set({ geo_name: v })} />

      <SectionTitle>Résultats : {info.n_rows.toLocaleString("fr")} lignes</SectionTitle>
      {info.sheets.length > 1 && (
        <Field label="Feuille">
          <select className={inputClass} value={mapping.sheet} onChange={(e) => onSheet(e.target.value)} disabled={busy === "inspect"}>
            {info.sheets.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </Field>
      )}
      <div className="-mx-1 overflow-x-auto rounded-xl ring-1 ring-zinc-950/[0.07]">
        <table className="min-w-full text-xs">
          <thead className="bg-zinc-50 text-left text-zinc-500">
            <tr>
              {info.columns.map((c) => (
                <th key={c} className="px-2 py-1.5 font-semibold whitespace-nowrap">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {info.preview.map((row, i) => (
              <tr key={i} className="border-t border-zinc-950/[0.05]">
                {info.columns.map((c) => (
                  <td key={c} className="px-2 py-1 whitespace-nowrap tabular-nums">
                    {row[c]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ColumnSelect
        label="Identifiant du bureau"
        value={mapping.res_id}
        options={info.columns}
        onChange={(v) => set({ res_id: v })}
        hint="Doit correspondre à l'identifiant choisi sur la carte (les zéros en tête sont ignorés)."
      />
      <ColumnSelect label="Voix Die Linke" value={mapping.linke} options={info.columns} onChange={(v) => set({ linke: v })} />
      <ColumnSelect label="Suffrages exprimés" value={mapping.valid} options={info.columns} onChange={(v) => set({ valid: v })} />
      <ColumnSelect
        label="Inscrit·es"
        optional
        value={mapping.eligible}
        options={info.columns}
        onChange={(v) => set({ eligible: v })}
        hint="Avec les votant·es, donne l'abstention."
      />
      <ColumnSelect label="Votant·es" optional value={mapping.voters} options={info.columns} onChange={(v) => set({ voters: v })} />

      <Field label="Partis à afficher dans le détail (facultatif)">
        <div className="flex flex-wrap gap-1.5">
          {partyOptions.map((c) => {
            const on = mapping.parties.includes(c);
            return (
              <button
                key={c}
                type="button"
                onClick={() => set({ parties: on ? mapping.parties.filter((p) => p !== c) : [...mapping.parties, c] })}
                className={`rounded-full px-3 py-1.5 text-xs font-semibold ${on ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-700"}`}
              >
                {c}
              </button>
            );
          })}
        </div>
      </Field>
      <Field label="Nom de l'élection (facultatif)">
        <input
          className={inputClass}
          value={mapping.election}
          placeholder="ex. Bundestag 2025 (2e voix)"
          onChange={(e) => set({ election: e.target.value })}
        />
      </Field>

      <Button className="w-full" icon={Sparkles} disabled={!ready} loading={busy === "start"} onClick={onStart}>
        Importer et calculer les scores
      </Button>
    </>
  );
}
