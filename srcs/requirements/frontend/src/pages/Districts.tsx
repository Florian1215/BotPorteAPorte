import type { FeatureCollection } from "geojson";
import L from "leaflet";
import { Bot, ChevronRight, ExternalLink, LandPlot, RefreshCw, SlidersHorizontal, Sparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Marker, useMap, useMapEvents } from "react-leaflet";
import { useNavigate } from "react-router-dom";

import { api, errorMessage } from "../api/client";
import type {
  DistrictDetail,
  DistrictProgress,
  DistrictImport,
  DistrictMap,
  CityPack,
  ScoreCriterionKey,
  ScoreWeights,
} from "../api/types";
import { FitBounds, FlyTo, MapLayers } from "../components/map";
import { BackContext } from "../context/BackContext";
import { Alert, Button, Card, EmptyState, Field, Loading, SectionTitle, Segmented, Sheet, Spinner, inputClass } from "../components/ui";
import { CRITERION_FORMAT, CRITERION_HELP, DONE_STOPS, SCORE_CLASSES, doneColor, formatSocial, scoreColor } from "../lib/constants";

type MapDistrict = DistrictMap["districts"][number];
/** What the colour of the districts tells: their score, or the share of doors done. */
type ColorBy = "score" | "done";

/** Best districts listed in the overview sheet (three visible, the others by scrolling). */
const BEST_LISTED = 20;

/** "50 meilleures": only the best districts by score, on the map and in the count. */
const TOP_N = 50;

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
  const [colorBy, setColorBy] = useState<ColorBy>("score");
  const [topOnly, setTopOnly] = useState(false);

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
        // Live steps of the AI import.
        setData((d) => (d && job ? { ...d, import: job } : d));
        if (job?.status !== "running") {
          window.clearInterval(timer);
          load();
          if (job?.status === "done") setPanel("overview");
        }
      } catch {
        /* keep polling */
      }
    }, 4000);
    return () => window.clearInterval(timer);
  }, [running, load]);

  const allDistricts = data?.districts;
  const districts = useMemo(() => {
    const all = allDistricts ?? [];
    return topOnly ? [...all].sort((a, b) => b.score - a.score).slice(0, TOP_N) : all;
  }, [allDistricts, topOnly]);
  const labelPoints = useMemo(
    () => districts.flatMap((d) => (d.label ? [[d.label.lat, d.label.lon] as [number, number]] : [])),
    [districts],
  );
  const empty = data !== null && data.districts.length === 0;
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
    sheet = (
      <OverviewSheet
        data={data}
        onSelect={setSelectedId}
        onPanel={setPanel}
        colorBy={colorBy}
        onColorBy={setColorBy}
        topOnly={topOnly}
        onTopOnly={setTopOnly}
      />
    );
  }

  return (
    <>
      <MapLayers>
        {districts.length > 0 && (
          <>
            <FitBounds
              points={labelPoints}
              fitKey={`districts-${districts.length}-${data?.import?.id}-${overviewCount}-${topOnly}`}
            />
            <DistrictLayer districts={districts} selectedId={selectedId} onSelect={setSelectedId} colorBy={colorBy} />
            <DistrictLabels districts={districts} colorBy={colorBy} onSelect={setSelectedId} />
            <FlyTo point={selectedLabel ? [selectedLabel.lat, selectedLabel.lon] : null} zoom={15} />
          </>
        )}
      </MapLayers>
      {sheet}
    </>
  );
}

// --------------------------------------------------------------------------- map layers

type DistrictProps = { id: number; score: number; done_pct: number };

function districtStyle(p: DistrictProps, selected: boolean, colorBy: ColorBy): L.PathOptions {
  const fillColor = colorBy === "done" ? doneColor(p.done_pct) : scoreColor(p.score);
  return selected
    ? { fillColor, fillOpacity: 0.9, color: "#18181b", weight: 3, opacity: 1 }
    : { fillColor, fillOpacity: colorBy === "done" ? 0.8 : 0.7, color: "#ffffff", weight: 0.8, opacity: 0.9 };
}

/** All districts in one canvas layer (thousands of polygons: drawn imperatively, restyled on selection). */
function DistrictLayer({
  districts,
  selectedId,
  onSelect,
  colorBy,
}: {
  districts: MapDistrict[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  colorBy: ColorBy;
}) {
  const map = useMap();
  const layer = useRef<L.GeoJSON | null>(null);
  const select = useRef(onSelect);
  select.current = onSelect;
  const mode = useRef(colorBy);
  mode.current = colorBy;

  useEffect(() => {
    const collection: FeatureCollection = {
      type: "FeatureCollection",
      features: districts.map((d) => ({
        type: "Feature",
        properties: { id: d.id, score: d.score, done_pct: d.done_pct } satisfies DistrictProps,
        geometry: d.geometry as never,
      })),
    };
    const geo = L.geoJSON(collection, {
      style: (f) => districtStyle(f?.properties as DistrictProps, false, mode.current),
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
      const path = l as L.Path & { feature?: { properties: DistrictProps } };
      if (!path.feature) return;
      const selected = path.feature.properties.id === selectedId;
      path.setStyle(districtStyle(path.feature.properties, selected, colorBy));
      if (selected) path.bringToFront();
    });
  }, [selectedId, districts, colorBy]);

  return null;
}

const labelIcons = new Map<string, L.DivIcon>();

function cachedIcon(key: string, html: string): L.DivIcon {
  let icon = labelIcons.get(key);
  if (!icon) {
    icon = L.divIcon({ className: "", html: `<div class="district-label">${html}</div>`, iconSize: [0, 0] });
    labelIcons.set(key, icon);
  }
  return icon;
}

/** "Score" mode: score (· % done, when some were). "% fait" mode: French voters, or done / French voters. */
function labelIcon(d: MapDistrict, colorBy: ColorBy): L.DivIcon {
  if (colorBy === "done") {
    const text = d.n_done > 0 ? `${d.n_done}/${d.n_total}` : `${d.n_total}`;
    return cachedIcon(`done|${text}`, text);
  }
  const score = Math.round(d.score);
  const done = Math.round(d.done_pct);
  return cachedIcon(`score|${score}|${done}`, `${score}${done > 0 ? `<small>· ${done} %</small>` : ""}`);
}

/** Label on each district in view, once zoomed in (see `labelIcon`). */
function DistrictLabels({
  districts,
  colorBy,
  onSelect,
}: {
  districts: MapDistrict[];
  colorBy: ColorBy;
  onSelect: (id: number) => void;
}) {
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
          icon={labelIcon(d, colorBy)}
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

/** Light → plain red → almost black, as on the map in "% fait" mode. */
function DoneLegend() {
  return (
    <div>
      <div
        className="h-2.5 rounded-lg"
        style={{ background: `linear-gradient(to right, ${DONE_STOPS.map((s) => `${s.color} ${s.pct}%`).join(", ")})` }}
      />
      <div className="mt-1 flex justify-between text-[11px] text-zinc-500 tabular-nums">
        <span>0 %</span>
        <span>50 %</span>
        <span>100 % fait</span>
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
  colorBy,
  onColorBy,
  topOnly,
  onTopOnly,
}: {
  data: DistrictMap;
  onSelect: (id: number) => void;
  onPanel: (p: "weights" | "import") => void;
  colorBy: ColorBy;
  onColorBy: (c: ColorBy) => void;
  topOnly: boolean;
  onTopOnly: (on: boolean) => void;
}) {
  const best = data.districts.slice(0, BEST_LISTED); // already sorted by score
  const shown = topOnly ? Math.min(TOP_N, data.districts.length) : data.districts.length;
  return (
    <Sheet
      title={`Zones (${shown.toLocaleString("fr")})`}
      subtitle={[data.election || "Bureaux de vote", data.reference_party && `parti de référence : ${data.reference_party}`]
        .filter(Boolean)
        .join(" · ")}
      locate={false}
      action={
        <button
          type="button"
          onClick={() => onTopOnly(!topOnly)}
          aria-pressed={topOnly}
          className={`rounded-full px-2.5 py-1 text-xs font-semibold transition ${
            topOnly ? "bg-brand-600 text-white" : "bg-zinc-100 text-zinc-600 active:bg-zinc-200"
          }`}
        >
          {TOP_N} meilleures
        </button>
      }
    >
      <Segmented
        value={colorBy}
        onChange={onColorBy}
        options={[
          { value: "score", label: "Score" },
          { value: "done", label: "% fait" },
        ]}
      />
      {colorBy === "score" ? <ScoreLegend /> : <DoneLegend />}
      <div className="grid grid-cols-2 gap-2">
        <Button variant="secondary" size="sm" icon={SlidersHorizontal} onClick={() => onPanel("weights")}>
          Pondération
        </Button>
        <Button variant="secondary" size="sm" icon={RefreshCw} onClick={() => onPanel("import")}>
          Réimporter
        </Button>
      </div>


      <SectionTitle>{`${best.length} meilleurs scores`}</SectionTitle>
      {/* Three rows high, scroll for the others. */}
      <div className="-mx-1 max-h-[13.25rem] space-y-2 overflow-y-auto overscroll-contain px-1 py-px">
        {best.map((d) => (
          <button
            key={d.id}
            onClick={() => onSelect(d.id)}
            className="flex w-full items-center gap-3 rounded-2xl bg-white p-3 text-left ring-1 ring-zinc-950/[0.08] active:bg-zinc-50"
          >
            <ScoreBadge score={d.score} />
            <div className="min-w-0 flex-1">
              <p className="truncate font-semibold tracking-tight">{d.name}</p>
              <p className="text-xs text-zinc-500 tabular-nums">
                {d.n_done > 0
                  ? `${d.n_done}/${d.n_total} Français·es faits · ${d.done_pct.toLocaleString("fr")} %`
                  : `${d.n_total} Français·e${d.n_total > 1 ? "s" : ""}`}
              </p>
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
    api<DistrictDetail>(`/manage/districts/${id}/`)
      .then(setDetail)
      .catch((e) => setError(errorMessage(e)));
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
  const isReference = (name: string) => d.reference_party_columns.includes(name);

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
          <SectionTitle>
            Français·es de la zone
            {d.progress_election && <span className="font-normal"> · {d.progress_election}</span>}
          </SectionTitle>
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
        <Metric label={d.reference_party || "Parti de référence"} value={formatPct(d.reference_pct)} />
        <Metric label="Participation" value={formatPct(d.turnout_pct)} />
      </div>
      {d.parties.length > 0 && (
        <Card className="space-y-1.5 p-3.5">
          {d.parties.map((party) => (
            <div key={party.name} className="flex items-center gap-2 text-sm">
              <span className={`w-24 shrink-0 truncate ${isReference(party.name) ? "font-semibold" : "text-zinc-600"}`}>{party.name}</span>
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-zinc-100">
                <div
                  className={`h-full rounded-full ${isReference(party.name) ? "bg-brand-600" : "bg-zinc-400"}`}
                  style={{ width: `${((party.pct ?? 0) / maxPartyPct) * 100}%` }}
                />
              </div>
              <span className="w-14 shrink-0 text-right tabular-nums text-zinc-700">{formatPct(party.pct)}</span>
            </div>
          ))}
        </Card>
      )}

      <SectionTitle>Français·es de la liste</SectionTitle>
      <div className="grid grid-cols-2 gap-2">
        <Metric label="Densité" value={d.density != null ? `${d.density.toLocaleString("fr")} Français·es/km²` : "—"} />
        <Metric label="Vote LFI attendu (âge)" value={formatPct(d.age_lfi_vote != null ? d.age_lfi_vote * 100 : null)} />
        <Metric label="18–29 ans" value={formatPct(d.share_18_29 != null ? d.share_18_29 * 100 : null)} />
        <Metric label="65 ans et plus" value={formatPct(d.share_65_plus != null ? d.share_65_plus * 100 : null)} />
      </div>

      <SectionTitle>Quartier</SectionTitle>
      <div className="grid grid-cols-2 gap-2">
        <Metric label={d.social_label || "Indicateur social"} value={d.social_value != null ? formatSocial(d.social_value) : "—"} />
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
  const [columns, setColumns] = useState<string[]>(data.reference_party_columns);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const total = Object.values(weights).reduce((a, b) => a + b, 0);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const partyChanged = columns.join("|") !== data.reference_party_columns.join("|");
      await api("/manage/score-weights/", {
        method: "PUT",
        body: partyChanged ? { weights, reference_party_columns: columns } : { weights },
      });
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
          <Button onClick={save} loading={busy} disabled={total === 0 || (data.party_options.length > 0 && columns.length === 0)}>
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

      {data.party_options.length > 0 && (
        <>
          <SectionTitle>Parti de référence</SectionTitle>
          <p className="-mt-1 text-xs text-zinc-500">
            Le parti le plus proche de LFI dans le pays. Plusieurs choix si c'était une liste commune : leurs voix s'additionnent.
          </p>
          <div className="flex flex-wrap gap-1.5">
            {data.party_options.map((name) => {
              const on = columns.includes(name);
              return (
                <button
                  key={name}
                  type="button"
                  aria-pressed={on}
                  onClick={() => setColumns(on ? columns.filter((c) => c !== name) : [...columns, name])}
                  className={`rounded-full px-3 py-1.5 text-xs font-semibold ${on ? "bg-brand-600 text-white" : "bg-zinc-100 text-zinc-700"}`}
                >
                  {name}
                </button>
              );
            })}
          </div>
          {columns.length === 0 && <Alert kind="warning">Choisis au moins un parti.</Alert>}
        </>
      )}
    </Sheet>
  );
}

// --------------------------------------------------------------------------- import

const FLAGS: Record<string, string> = { DE: "🇩🇪", AT: "🇦🇹", CZ: "🇨🇿", PL: "🇵🇱", RO: "🇷🇴" };

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
  const [hint, setHint] = useState("");

  const run = async (key: string, body: Record<string, unknown>) => {
    setBusy(key);
    setError(null);
    try {
      await api("/manage/districts/import/", { method: "POST", body });
      onStarted();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  if (job?.status === "running" && job.source === "ai")
    return (
      <Sheet title="L'IA cherche les données" subtitle="Carte des zones, résultats électoraux et indicateur social." locate={false}>
        <div className="flex items-center gap-3 rounded-2xl bg-zinc-50 p-4 text-sm text-zinc-600 ring-1 ring-zinc-950/5">
          <Spinner className="size-5 shrink-0 text-brand-600" />
          Ça prend en général 5 à 20 minutes. Tu peux quitter cette page, l'import continue.
        </div>
        {job.hint && <p className="text-sm text-zinc-500">Ta précision : « {job.hint} »</p>}
        <AiSteps steps={job.progress_log ?? []} running />
      </Sheet>
    );

  if (job?.status === "running")
    return (
      <Sheet title="Import en cours" subtitle="Téléchargement des données officielles et calcul des scores." locate={false}>
        <div className="flex items-center gap-3 rounded-2xl bg-zinc-50 p-4 text-sm text-zinc-600 ring-1 ring-zinc-950/5">
          <Spinner className="size-5 text-brand-600" />
          Ça prend en général une à trois minutes. Tu peux quitter cette page.
        </div>
      </Sheet>
    );

  const [mine, others] = [data.packs.filter((p) => p.recommended), data.packs.filter((p) => !p.recommended)];
  const packButton = (pack: CityPack) => (
    <button
      key={pack.key}
      onClick={() => run(pack.key, { pack: pack.key })}
      disabled={busy !== null}
      className={`flex w-full items-center gap-3 rounded-2xl bg-white p-3.5 text-left ring-1 active:bg-zinc-50 disabled:opacity-60 ${
        pack.recommended ? "ring-2 ring-brand-500" : "ring-zinc-950/[0.08]"
      }`}
    >
      <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-lg">
        {busy === pack.key ? <Spinner className="size-5 text-brand-700" /> : FLAGS[pack.country] ?? <LandPlot className="size-5 text-brand-700" />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-baseline gap-x-2">
          <span className="font-semibold tracking-tight">{pack.city}</span>
          <span className="text-xs text-zinc-500">{pack.election}</span>
        </span>
        <span className="block text-xs text-zinc-500">{pack.description}</span>
      </span>
      <ChevronRight className="size-5 shrink-0 text-zinc-300" />
    </button>
  );

  return (
    <Sheet
      title="Importer les zones"
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
      {job?.status === "failed" && job.source === "ai" && (job.progress_log?.length ?? 0) > 0 && (
        <details className="text-sm text-zinc-600">
          <summary className="cursor-pointer">Étapes de l'IA</summary>
          <AiSteps steps={job.progress_log ?? []} />
        </details>
      )}
      {job?.status === "done" && job.source === "ai" && <AiReport job={job} />}
      {error && <Alert>{error}</Alert>}
      {data.districts.length > 0 && (
        <Alert kind="warning">
          L'import remplace les {data.districts.length.toLocaleString("fr")} zones actuelles. Les tournées passées gardent leurs résultats.
        </Alert>
      )}
      {data.districts.length === 0 && !job && <EmptyState icon={LandPlot} title="Pas encore de zones" />}

      {mine.length > 0 && (
        <>
          <SectionTitle>Ta ville</SectionTitle>
          {mine.map(packButton)}
        </>
      )}
      <SectionTitle>{mine.length > 0 ? "Autres villes" : "Packs des villes"}</SectionTitle>
      <p className="-mt-1 text-xs text-zinc-500">
        Un clic : la carte et les résultats officiels sont téléchargés, puis les scores calculés.
      </p>
      {others.map(packButton)}

      {!data.ai_unavailable && (
        <Card className="space-y-3 p-3.5">
          <div className="flex items-center gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700">
              <Bot className="size-5" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="font-semibold tracking-tight">Importer avec l'IA</p>
              <p className="text-xs text-zinc-500">
                Pour une autre ville : l'IA cherche la carte des bureaux de vote (ou des quartiers), les derniers résultats, un indicateur
                social, et le parti le plus proche de LFI dans le pays.
              </p>
            </div>
          </div>
          <Field label="Précision (facultatif)">
            <textarea
              className={`${inputClass} min-h-16 py-2`}
              value={hint}
              maxLength={1000}
              onChange={(e) => setHint(e.target.value)}
              placeholder="ex. législatives 2024 plutôt que les municipales, ou un lien vers le portail open data"
            />
          </Field>
          <Button className="w-full" icon={Sparkles} loading={busy === "ai"} disabled={busy !== null} onClick={() => run("ai", { ai: true, hint })}>
            Lancer l'import par l'IA
          </Button>
        </Card>
      )}
    </Sheet>
  );
}

/** Steps the AI agent reported, oldest first. */
function AiSteps({ steps, running = false }: { steps: { at: string; message: string }[]; running?: boolean }) {
  if (steps.length === 0) return running ? <p className="text-sm text-zinc-500">L'IA démarre…</p> : null;
  return (
    <ol className="space-y-2">
      {steps.map((step, i) => {
        const current = running && i === steps.length - 1;
        return (
          <li key={`${step.at}-${i}`} className="flex gap-2.5 text-sm">
            <span className={`mt-1.5 size-2 shrink-0 rounded-full ${current ? "animate-pulse bg-brand-600" : "bg-zinc-300"}`} />
            <span className={current ? "font-medium text-zinc-900" : "text-zinc-600"}>{step.message}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** What the last AI import found: election, zones, reference party (and why), social indicator, sources. */
function AiReport({ job }: { job: DistrictImport }) {
  const r = job.report;
  return (
    <Card className="space-y-2 p-3.5 text-sm">
      <p className="font-semibold tracking-tight">Dernier import par l'IA</p>
      <p className="text-zinc-600">
        {r.n_districts?.toLocaleString("fr")} {r.level || "zones"}
        {r.election ? ` · ${r.election}` : ""}
      </p>
      {r.reference_party && (
        <p className="text-zinc-600">
          <span className="font-semibold text-zinc-900">Parti de référence : {r.reference_party}.</span> {r.reference_reason}
        </p>
      )}
      <p className="text-zinc-600">
        {r.social_label
          ? `Indicateur social : ${r.social_label}${r.social_source ? ` (${r.social_source})` : ""}, pour ${r.n_with_social ?? 0} zones.`
          : "Pas d'indicateur social trouvé : le score s'en passe."}
      </p>
      {r.notes && <p className="text-zinc-500">{r.notes}</p>}
      {(r.sources?.length ?? 0) > 0 && (
        <ul className="space-y-1">
          {r.sources!.map((url) => (
            <li key={url} className="flex min-w-0 items-center gap-1.5">
              <ExternalLink className="size-3.5 shrink-0 text-zinc-400" />
              <a href={url} target="_blank" rel="noreferrer noopener" className="truncate text-brand-700 underline">
                {url}
              </a>
            </li>
          ))}
        </ul>
      )}
      {r.cost_usd != null && <p className="text-xs text-zinc-400">Coût de l'import : {r.cost_usd.toLocaleString("fr")} $</p>}
    </Card>
  );
}
