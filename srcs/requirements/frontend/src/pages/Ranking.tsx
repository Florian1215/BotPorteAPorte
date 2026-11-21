import { Medal, Trophy, Users } from "lucide-react";
import { useEffect, useState } from "react";

import { api, errorMessage } from "../api/client";
import type { Leaderboard, MemberRankRow, OrganizationRankRow } from "../api/types";
import { OrgLogo } from "../components/organization";
import { Alert, EmptyState, Loading, Segmented, Sheet } from "../components/ui";
import { useAuth } from "../context/AuthContext";

type Scope = "group" | "organizations" | "all";

const MEDALS = ["text-amber-500", "text-zinc-400", "text-orange-700"];

/** Doors knocked for the current election: within my group, between organizations, or every militant. */
export default function Ranking() {
  const { user } = useAuth();
  const [scope, setScope] = useState<Scope>("group");
  const [board, setBoard] = useState<Leaderboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Kept across tabs, so the subtitle does not flicker while the next one loads.
  const [election, setElection] = useState<string | null | undefined>(undefined);

  useEffect(() => {
    setBoard(null);
    setError(null);
    api<Leaderboard>("/stats/leaderboard/", { query: { scope } })
      .then((b) => {
        setBoard(b);
        setElection(b.election);
      })
      .catch((e) => setError(errorMessage(e)));
  }, [scope]);

  // Ignore a late answer from the previously selected tab.
  const rows = board && board.scope === scope ? board : null;

  return (
    <Sheet
      title="Classement"
      subtitle={election ? `Portes frappées · ${election}` : "Nombre de portes frappées"}
      locate={false}
    >
      <Segmented
        value={scope}
        onChange={setScope}
        options={[
          { value: "group", label: "Mon groupe" },
          { value: "organizations", label: "Organisations" },
          { value: "all", label: "Tout le monde" },
        ]}
      />
      {error && <Alert>{error}</Alert>}
      {!rows && !error && <Loading />}
      {rows && rows.rows.length === 0 && <EmptyState icon={Trophy} title="Pas encore de classement" />}
      {rows && rows.rows.length > 0 && (
        <ol className="-mx-1 divide-y divide-zinc-950/[0.06]">
          {rows.scope === "organizations"
            ? (rows.rows as OrganizationRankRow[]).map((r, i) => <OrganizationRow key={r.id} row={r} gap={gapBefore(rows.rows, i)} />)
            : (rows.rows as MemberRankRow[]).map((r, i) => (
                <MemberRow key={r.id} row={r} showOrganization={rows.scope === "all"} gap={gapBefore(rows.rows, i)} />
              ))}
        </ol>
      )}
      {scope === "group" && user?.organization && rows && (
        <p className="text-center text-xs text-zinc-400">{user.organization.name}</p>
      )}
    </Sheet>
  );
}

/** The user's own row may be appended after the top 100: show "…" before it. */
function gapBefore(rows: { rank: number }[], i: number) {
  return i > 0 && rows[i].rank > rows[i - 1].rank + 1 && i === rows.length - 1 && rows.length > 100;
}

function Rank({ rank }: { rank: number }) {
  return (
    <span className="flex w-8 shrink-0 justify-center text-sm font-semibold text-zinc-400 tabular-nums">
      {rank <= 3 ? <Medal className={`size-5 ${MEDALS[rank - 1]}`} aria-label={`${rank}e`} /> : rank}
    </span>
  );
}

function Gap() {
  return <li className="py-1 text-center text-zinc-300">…</li>;
}

function MemberRow({ row, showOrganization, gap }: { row: MemberRankRow; showOrganization: boolean; gap: boolean }) {
  return (
    <>
      {gap && <Gap />}
      <li className={`flex items-center gap-3 px-1 py-2.5 ${row.is_me ? "rounded-xl bg-brand-50" : ""}`}>
        <Rank rank={row.rank} />
        <div className="min-w-0 flex-1">
          <p className={`truncate text-[15px] ${row.is_me ? "font-semibold text-brand-700" : "font-medium"}`}>
            {row.name} {row.is_me && <span className="text-xs font-normal">(toi)</span>}
          </p>
          {showOrganization && <p className="truncate text-xs text-zinc-500">{row.organization}</p>}
        </div>
        <span className="shrink-0 text-[15px] font-semibold tabular-nums pr-3">{row.doors.toLocaleString("fr")}</span>
      </li>
    </>
  );
}

function OrganizationRow({ row, gap }: { row: OrganizationRankRow; gap: boolean }) {
  return (
    <>
      {gap && <Gap />}
      <li className={`flex items-center gap-3 px-1 py-2.5 ${row.is_me ? "rounded-xl bg-brand-50" : ""}`}>
        <Rank rank={row.rank} />
        <OrgLogo organization={row} className="size-9 text-sm" />
        <div className="min-w-0 flex-1">
          <p className={`truncate text-[15px] ${row.is_me ? "font-semibold text-brand-700" : "font-medium"}`}>{row.name}</p>
          <p className="flex items-center gap-1 truncate text-xs text-zinc-500">
            {row.city && `${row.city} · `}
            <Users className="size-3" /> {row.members}
          </p>
        </div>
        <span className="shrink-0 text-[15px] font-semibold tabular-nums pr-3">{row.doors.toLocaleString("fr")}</span>
      </li>
    </>
  );
}
