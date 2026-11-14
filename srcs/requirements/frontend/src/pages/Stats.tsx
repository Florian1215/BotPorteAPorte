import { useEffect, useState } from "react";

import { api, errorMessage } from "../api/client";
import type { MyStats } from "../api/types";
import { Alert, Sheet, Spinner } from "../components/ui";
import { RESULTS } from "../lib/constants";

export default function Stats() {
  const [stats, setStats] = useState<MyStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<MyStats>("/stats/me/").then(setStats).catch((e) => setError(errorMessage(e)));
  }, []);

  return (
    <Sheet
      title="Mes statistiques"
      subtitle={
        stats &&
        (stats.total_success > 0
          ? "Félicitations pour ton engagement ! 👏"
          : "Aucune visite réussie pour l'instant. C'est le moment de s'y mettre ! ✊")
      }
    >
      {error && <Alert>{error}</Alert>}
      {!stats && !error && (
        <div className="flex justify-center py-6 text-brand-600">
          <Spinner />
        </div>
      )}
      {stats && (
        <>
          <div className="grid grid-cols-3 gap-2 text-center">
            <Tile value={stats.total_success} label="succès" accent />
            <Tile value={stats.total_visits} label="portes frappées" />
            <Tile value={stats.tours_completed} label="tournées" />
          </div>
          <div className="divide-y divide-slate-100 rounded-2xl ring-1 ring-slate-200">
            {RESULTS.map((r) => (
              <div key={r.value} className="flex items-center gap-3 px-4 py-3">
                <span className="text-xl">{r.emoji}</span>
                <span className="flex-1 text-sm">{r.label}</span>
                <span className="font-semibold tabular-nums">{stats.by_result[r.value]}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </Sheet>
  );
}

function Tile({ value, label, accent = false }: { value: number; label: string; accent?: boolean }) {
  return (
    <div className={`rounded-2xl py-3 ${accent ? "bg-brand-600 text-white" : "bg-slate-50 ring-1 ring-slate-200"}`}>
      <p className="text-2xl font-bold tabular-nums">{value}</p>
      <p className={`text-xs ${accent ? "opacity-90" : "text-slate-500"}`}>{label}</p>
    </div>
  );
}
