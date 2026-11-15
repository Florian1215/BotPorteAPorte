import { DoorOpen, Flag, Medal, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, errorMessage } from "../api/client";
import type { MyStats } from "../api/types";
import { Alert, Card, Loading, SectionTitle, Sheet, StatTile } from "../components/ui";
import { RESULTS } from "../lib/constants";

export default function Stats() {
  const [stats, setStats] = useState<MyStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<MyStats>("/stats/me/").then(setStats).catch((e) => setError(errorMessage(e)));
  }, []);

  const max = stats ? Math.max(1, ...RESULTS.map((r) => stats.by_result[r.value])) : 1;

  return (
    <Sheet
      title="Mes statistiques"
      subtitle={
        stats &&
        (stats.total_success > 0 ? (
          <span className="inline-flex items-center gap-1.5">
            <Sparkles className="size-3.5 text-amber-500" /> Félicitations pour ton engagement !
          </span>
        ) : (
          "Aucune visite réussie pour l'instant. C'est le moment de s'y mettre !"
        ))
      }
    >
      {error && <Alert>{error}</Alert>}
      {!stats && !error && <Loading />}
      {stats && (
        <>
          <div className="grid grid-cols-3 gap-2">
            <Link to="/ranking" aria-label="Voir le classement" className="block rounded-2xl transition active:scale-[0.97]">
              <StatTile
                value={stats.total_visits > 0 ? `Top #${stats.rank}` : "—"}
                label={`sur ${stats.ranked_members} · voir`}
                icon={Medal}
                accent
              />
            </Link>
            <StatTile value={stats.total_visits} label="portes frappées" icon={DoorOpen} />
            <StatTile value={stats.tours_completed} label="tournées" icon={Flag} />
          </div>
          <SectionTitle>Détail des retours</SectionTitle>
          <Card className="divide-y divide-zinc-950/5">
            {RESULTS.map((r) => (
              <div key={r.value} className="flex items-center gap-3 px-3.5 py-3">
                <span className={`flex size-8 shrink-0 items-center justify-center rounded-full text-white ${r.disc}`}>
                  <r.icon className="size-4" strokeWidth={2.25} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="truncate text-sm">{r.label}</span>
                    <span className="font-semibold tabular-nums">{stats.by_result[r.value]}</span>
                  </div>
                  <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-zinc-100">
                    <div className="h-full rounded-full" style={{ width: `${(stats.by_result[r.value] / max) * 100}%`, background: r.color }} />
                  </div>
                </div>
              </div>
            ))}
          </Card>
        </>
      )}
    </Sheet>
  );
}
