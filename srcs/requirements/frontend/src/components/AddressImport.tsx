import { Archive, CircleCheck, FileSpreadsheet, MapPinCheck, MapPinOff, MapPinPlus, Truck, Upload, type LucideIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, errorMessage } from "../api/client";
import type { AddressCounts, AddressImportJob, ImportReport } from "../api/types";
import { Alert, Button, Card, Spinner } from "./ui";

const fr = (n: number) => n.toLocaleString("fr");
const plural = (n: number, one: string, many: string) => `${fr(n)} ${n > 1 ? many : one}`;

/** Rough geocoding speed of the movement's Nominatim servers (addresses per second). */
const GEOCODE_PER_SECOND = 25;

function duration(addresses: number): string {
  const minutes = Math.ceil(addresses / GEOCODE_PER_SECOND / 60);
  return minutes <= 1 ? "moins d'une minute" : `environ ${minutes} minutes`;
}

/**
 * Import of the voter list: the consular electoral list (.xls / .xlsx, as sent by the consulate) or a JSON file.
 * The file is first read as a dry run to show what will change; once confirmed, the import runs in the
 * background (new addresses are geocoded) and its progress is shown here.
 */
export default function AddressImport({ voterList }: { voterList: number }) {
  const [counts, setCounts] = useState<AddressCounts | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportReport | null>(null);
  const [job, setJob] = useState<AddressImportJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"preview" | "import" | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const base = `/manage/voter-lists/${voterList}/addresses/`;

  const loadCounts = useCallback(() => {
    api<AddressCounts>(base).then(setCounts).catch(() => setCounts(null));
  }, [base]);
  useEffect(loadCounts, [loadCounts]);
  useEffect(() => {
    api<AddressImportJob | null>(`${base}import/`)
      .then((last) => setJob(last?.status === "running" ? last : null))
      .catch(() => undefined);
  }, [base]);

  // Follow a running import.
  const running = job?.status === "running";
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(async () => {
      try {
        const next = await api<AddressImportJob | null>(`${base}import/`);
        setJob(next);
        if (next?.status !== "running") loadCounts();
      } catch {
        /* keep polling */
      }
    }, 2500);
    return () => window.clearInterval(timer);
  }, [running, base, loadCounts]);

  const send = async <T,>(selected: File, dryRun: boolean) => {
    const body = new FormData();
    body.append("file", selected);
    body.append("dry_run", dryRun ? "1" : "0");
    return api<T>(`${base}import/`, { method: "POST", body });
  };

  const choose = async (selected: File) => {
    setFile(selected);
    setPreview(null);
    setJob(null);
    setError(null);
    setBusy("preview");
    try {
      setPreview(await send<ImportReport>(selected, true));
    } catch (e) {
      setError(errorMessage(e));
      setFile(null);
    } finally {
      setBusy(null);
    }
  };

  const confirm = async () => {
    if (!file) return;
    setBusy("import");
    setError(null);
    try {
      setJob(await send<AddressImportJob>(file, false));
      setPreview(null);
      setFile(null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const cancel = () => {
    setFile(null);
    setPreview(null);
    setError(null);
  };

  const done = job?.status === "done" ? job.report : null;

  return (
    <Card className="space-y-3 p-3.5">
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-2xl font-semibold tracking-tight tabular-nums">{counts ? fr(counts.active) : <Spinner className="size-5 text-zinc-300" />}</p>
          <p className="text-xs text-zinc-500">
            adresses actives
            {counts && counts.disabled > 0 && ` · ${plural(counts.disabled, "désactivée", "désactivées")}`}
          </p>
        </div>
        <input
          ref={input}
          type="file"
          accept=".xls,.xlsx,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,.json,application/json"
          className="hidden"
          onChange={(e) => {
            const selected = e.target.files?.[0];
            if (selected) choose(selected);
            e.target.value = "";
          }}
        />
        {!preview && !running && (
          <Button variant="secondary" size="sm" icon={Upload} loading={busy === "preview"} onClick={() => input.current?.click()}>
            Importer la liste
          </Button>
        )}
      </div>

      {error && <Alert>{error}</Alert>}

      {running && job && <Progress job={job} />}

      {job?.status === "failed" && <Alert>L'import a échoué : {job.message}</Alert>}

      {done && (
        <Alert kind="success">
          <p className="font-semibold">Import terminé</p>
          <p className="mt-0.5">
            {plural(done.new ?? 0, "nouvelle personne", "nouvelles personnes")}, {plural(done.existing ?? 0, "déjà connue", "déjà connues")}
            {done.moved ? ` (dont ${plural(done.moved, "déménagement", "déménagements")})` : ""},{" "}
            {plural(done.disabled ?? 0, "personne sortie de la liste", "personnes sorties de la liste")}.
          </p>
          {(done.reactivated ?? 0) > 0 && <p className="mt-0.5">{plural(done.reactivated!, "personne réactivée", "personnes réactivées")}.</p>}
        </Alert>
      )}
      {done && (done.not_geocoded ?? 0) > 0 && <NotGeocoded count={done.not_geocoded!} examples={done.not_geocoded_examples ?? []} warnings={done.geocoding_warnings ?? []} />}

      {preview && file && (
        <div className="space-y-3 rounded-2xl bg-zinc-50 p-3 ring-1 ring-zinc-950/5">
          <p className="flex items-center gap-2 text-sm font-semibold">
            <FileSpreadsheet className="size-4 shrink-0 text-zinc-400" />
            <span className="truncate">{file.name}</span>
            <span className="shrink-0 font-normal text-zinc-400">· {plural(preview.total, "personne", "personnes")}</span>
          </p>
          <div className="space-y-1.5">
            <Line icon={MapPinPlus} tone="text-emerald-600" value={preview.new} label="nouvelles personnes" />
            <Line
              icon={MapPinCheck}
              tone="text-sky-600"
              value={preview.existing}
              label="déjà connues"
              hint={preview.reactivated ? `dont ${fr(preview.reactivated)} réactivées` : undefined}
            />
            <Line icon={Truck} tone="text-violet-600" value={preview.moved} label="ont déménagé" hint="nouvelle adresse" />
            <Line icon={Archive} tone="text-amber-600" value={preview.disabled} label="ne sont plus sur la liste" hint="seront désactivées" />
          </div>
          {preview.to_geocode > 0 && (
            <Alert kind="info">
              {plural(preview.to_geocode, "adresse à localiser", "adresses à localiser")} sur la carte : {duration(preview.to_geocode)}. L'import
              continue en arrière-plan, tu peux quitter la page.
            </Alert>
          )}
          {preview.invalid > 0 && (
            <Alert kind="warning">
              <p>{plural(preview.invalid, "ligne ignorée", "lignes ignorées")} :</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs">
                {preview.errors.map((e) => (
                  <li key={e}>{e}</li>
                ))}
                {preview.invalid > preview.errors.length && <li>…</li>}
              </ul>
            </Alert>
          )}
          {counts && preview.disabled > 0 && preview.disabled >= counts.active / 2 && (
            <Alert kind="warning">
              Plus de la moitié des adresses actuelles seraient désactivées. Vérifie que c'est bien la liste complète.
            </Alert>
          )}
          <div className="grid grid-cols-2 gap-2">
            <Button variant="secondary" size="sm" onClick={cancel} disabled={busy !== null}>
              Annuler
            </Button>
            <Button size="sm" icon={CircleCheck} loading={busy === "import"} onClick={confirm}>
              Importer
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}

function Progress({ job }: { job: AddressImportJob }) {
  const total = job.geocode_total;
  const pct = total ? Math.min(100, (100 * job.geocode_done) / total) : 0;
  return (
    <div className="space-y-2 rounded-2xl bg-zinc-50 p-3 ring-1 ring-zinc-950/5">
      <p className="flex items-center gap-2 text-sm font-semibold">
        <Spinner className="size-4 text-brand-600" />
        Import en cours
      </p>
      {total > 0 ? (
        <>
          <div className="h-2 overflow-hidden rounded-full bg-zinc-200">
            <div className="h-full rounded-full bg-brand-600 transition-all" style={{ width: `${pct}%` }} />
          </div>
          <p className="text-xs text-zinc-500 tabular-nums">
            {fr(job.geocode_done)} / {fr(total)} adresses localisées · encore {duration(total - job.geocode_done)}
          </p>
        </>
      ) : (
        <p className="text-xs text-zinc-500">Lecture de la liste…</p>
      )}
    </div>
  );
}

function NotGeocoded({ count, examples, warnings }: { count: number; examples: string[]; warnings: string[] }) {
  return (
    <Alert kind="warning">
      <p className="flex items-center gap-1.5">
        <MapPinOff className="size-4 shrink-0" />
        {plural(count, "adresse n'a pas pu être localisée", "adresses n'ont pas pu être localisées")} (pas de numéro de rue, adresse inconnue de la carte…) :
        ces personnes ne sont pas sur la carte.
      </p>
      {warnings.map((w) => (
        <p key={w} className="mt-1 text-xs font-semibold">
          {w}
        </p>
      ))}
      {examples.length > 0 && (
        <details className="mt-1 text-xs">
          <summary className="cursor-pointer">Voir des exemples</summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {examples.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </details>
      )}
    </Alert>
  );
}

function Line({ icon: Icon, tone, value, label, hint }: { icon: LucideIcon; tone: string; value: number; label: string; hint?: string }) {
  if (value === 0 && Icon === Truck) return null;
  return (
    <div className="flex items-center gap-2.5 text-sm">
      <Icon className={`size-[18px] shrink-0 ${tone}`} />
      <span className="w-14 shrink-0 text-right font-semibold tabular-nums">{fr(value)}</span>
      <span className="min-w-0 text-zinc-700">
        {label}
        {hint && value > 0 && <span className="text-zinc-400"> · {hint}</span>}
      </span>
    </div>
  );
}
