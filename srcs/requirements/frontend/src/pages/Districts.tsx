import type { FeatureCollection } from "geojson";
import L from "leaflet";
import { ChevronRight, HandCoins, LandPlot, SlidersHorizontal, Sparkles, Upload } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Marker, useMap, useMapEvents } from "react-leaflet";
import { useNavigate } from "react-router-dom";

import { api, errorMessage } from "../api/client";
import type {
  DistrictDetail,
  DistrictImport,
  DistrictMap,
  CityPack,
  ScoreCriterionKey,
  SocialImportReport,
  ScoreWeights,
} from "../api/types";
import { FitBounds, FlyTo, MapLayers } from "../components/map";
import { BackContext } from "../context/BackContext";
import { Alert, Button, Card, EmptyState, Loading, SectionTitle, Segmented, Sheet, Spinner } from "../components/ui";
import { CRITERION_FORMAT, CRITERION_HELP, DONE_STOPS, SCORE_CLASSES, doneColor, scoreColor } from "../lib/constants";

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
    // With zones, the back button of the sheet returns to the overview (without, there is nothing to go back to).
    sheet = empty ? (
      <ImportSheet data={data} onStarted={load} />
    ) : (
      <BackContext.Provider value={() => setPanel("overview")}>
        <ImportSheet data={data} onStarted={load} />
      </BackContext.Provider>
    );
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
        <Button variant="secondary" size="sm" icon={Upload} onClick={() => onPanel("import")}>
          Importer
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

  return (
    <Sheet
      title={d.name}
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
              : "Aucun Français de la liste ici"}
          </p>
        </div>
      </div>

      {p.total > 0 && <AgePyramid ages={d.ages} />}

      <SectionTitle>Détail du score</SectionTitle>
      <Card className="divide-y divide-zinc-950/[0.06]">
        {d.score_parts.map((part) => {
          const counts = part.rank != null && part.weight > 0;
          return (
            <div key={part.key} className={`px-3.5 py-2.5 ${counts ? "" : "opacity-60"}`} title={CRITERION_HELP[part.key]}>
              <div className="flex items-baseline justify-between gap-2">
                <p className="text-sm font-semibold">{part.label}</p>
                <p className="text-sm tabular-nums text-zinc-700">
                  {part.value != null ? CRITERION_FORMAT[part.key](part.value) : "—"}
                </p>
              </div>
              <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-zinc-100">
                {part.rank != null && (
                  <div className="h-full rounded-full bg-brand-600" style={{ width: `${Math.max(2, part.rank * 100)}%` }} />
                )}
              </div>
              <p className="mt-1 text-[11px] text-zinc-500 tabular-nums">
                {part.rank == null
                  ? "Pas de donnée"
                  : `Mieux que ${Math.round(part.rank * 100)} % des zones${
                      counts ? ` · ${Math.round((100 * part.weight) / totalWeight)} % du score` : ""
                    }`}
              </p>
            </div>
          );
        })}
      </Card>

    </Sheet>
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
        <p className="text-sm text-zinc-500">Âges inconnus.</p>
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
      {ages.unknown > 0 && known > 0 && <p className="pt-1 text-[11px] text-zinc-500">{ages.unknown} âge inconnu</p>}
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
            {CRITERION_HELP[c.key as ScoreCriterionKey] && (
              <span className="block text-xs text-zinc-500">{CRITERION_HELP[c.key as ScoreCriterionKey]}</span>
            )}
          </label>
        );
      })}
      {total === 0 && <Alert kind="warning">Au moins un critère doit compter.</Alert>}

      {data.party_options.length > 0 && (
        <>
          <SectionTitle>Parti de référence</SectionTitle>
          <p className="-mt-1 text-xs text-zinc-500">
            Le ou les partis les plus proches de LFI dans ce pays : plus ils ont fait de voix dans une zone, plus elle est prioritaire.
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

function ImportSheet({ data, onStarted }: { data: DistrictMap; onStarted: () => void }) {
  const job = data.import;
  const hasZones = data.districts.length > 0;
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [socialReport, setSocialReport] = useState<SocialImportReport | null>(null);
  const socialInput = useRef<HTMLInputElement>(null);

  const run = async (key: string, body: Record<string, unknown>) => {
    setBusy(key);
    setError(null);
    setSocialReport(null);
    try {
      await api("/manage/districts/import/", { method: "POST", body });
      onStarted();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const uploadSocial = async (file: File) => {
    setBusy("social");
    setError(null);
    setSocialReport(null);
    const body = new FormData();
    body.append("file", file);
    try {
      setSocialReport(await api<SocialImportReport>("/manage/districts/social/", { method: "POST", body }));
      onStarted();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

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
    <ImportRow
      key={pack.key}
      onClick={() => run(pack.key, { pack: pack.key })}
      disabled={busy !== null}
      highlighted={pack.recommended}
      icon={busy === pack.key ? <Spinner className="size-5 text-brand-700" /> : FLAGS[pack.country] ?? <LandPlot className="size-5 text-brand-700" />}
      title={pack.city}
      meta={pack.election}
      description={pack.description}
    />
  );
  const social = data.social_upload;

  return (
    <Sheet title="Importer" locate={false}>
      {job?.status === "failed" && <Alert>L'import a échoué : {job.message}</Alert>}
      {error && <Alert>{error}</Alert>}
      {socialReport && (
        <Alert kind="success">
          Indicateur social importé sur {socialReport.n_with_social.toLocaleString("fr")} des{" "}
          {socialReport.n_districts.toLocaleString("fr")} zones. Les scores sont recalculés.
        </Alert>
      )}
      {!hasZones && !job && <EmptyState icon={LandPlot} title="Pas encore de zones" />}

      {/* Social indicator: one format for every city, a GeoJSON with `bureau_vote` and `minima_sociaux_pct`. */}
      <input
        ref={socialInput}
        type="file"
        accept=".geojson,.json,application/geo+json,application/json"
        className="hidden"
        onChange={(e) => {
          const selected = e.target.files?.[0];
          if (selected) uploadSocial(selected);
          e.target.value = "";
        }}
      />
      <Card className="flex items-center gap-3 p-3.5 ring-0!">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand-50">
          <HandCoins className="size-5 text-brand-700" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block font-semibold tracking-tight">Indicateur social</span>
          {social && (
            <span className="block text-xs text-zinc-500">
              {social.n_values.toLocaleString("fr")} bureaux{social.date ? ` · ${social.date}` : ""}
            </span>
          )}
        </span>
        <Button
          variant="secondary"
          size="sm"
          icon={Upload}
          loading={busy === "social"}
          disabled={busy !== null || !hasZones}
          onClick={() => socialInput.current?.click()}
        >
          Importer JSON
        </Button>
      </Card>

      {mine.length > 0 && (
        <>
          <SectionTitle>Ta ville</SectionTitle>
          {mine.map(packButton)}
        </>
      )}
      <SectionTitle>{mine.length > 0 ? "Autres villes" : "Packs des villes"}</SectionTitle>
      {others.map(packButton)}
      {hasZones && (
        <p className="text-xs text-zinc-500">
          Un pack remplace les {data.districts.length.toLocaleString("fr")} zones actuelles. Les tournées passées gardent leurs
          résultats, et l'indicateur social importé est conservé.
        </p>
      )}
    </Sheet>
  );
}

function ImportRow({
  icon,
  title,
  meta,
  description,
  onClick,
  disabled,
  highlighted = false,
}: {
  icon: ReactNode;
  title: string;
  meta?: string;
  description?: string;
  onClick: () => void;
  disabled?: boolean;
  highlighted?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`flex w-full items-center gap-3 rounded-2xl bg-white p-3.5 text-left ring-1 active:bg-zinc-50 disabled:opacity-60 ${
        highlighted ? "ring-2 ring-brand-500" : "ring-zinc-950/[0.08]"
      }`}
    >
      <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-lg">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-baseline gap-x-2">
          <span className="font-semibold tracking-tight">{title}</span>
          {meta && <span className="text-xs text-zinc-500">{meta}</span>}
        </span>
        {description && <span className="block text-xs text-zinc-500">{description}</span>}
      </span>
      <ChevronRight className="size-5 shrink-0 text-zinc-300" />
    </button>
  );
}
