import { Check, ChevronDown, Plus, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { api, errorMessage } from "../api/client";
import type { Election, SiteElections } from "../api/types";
import { Alert, Button, Card, Loading, Sheet, Spinner, inputClass } from "../components/ui";

const fr = (n: number) => n.toLocaleString("fr");

/** "Élection consulaire 2026" → "Consulaire 2026". */
function shortName(name: string) {
  const rest = name.trim().replace(/^[ée]lection\s+/i, "");
  return rest ? rest[0].toUpperCase() + rest.slice(1) : name;
}

/** Administration of the whole site (administrateur·rices du site). Other settings will come here. */
export default function SiteAdmin() {
  const [data, setData] = useState<SiteElections | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [confirming, setConfirming] = useState<Election | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    api<SiteElections>("/site/elections/").then(setData).catch((e) => setError(errorMessage(e)));
  }, []);
  useEffect(load, [load]);

  const run = async (key: string, action: () => Promise<string | void>) => {
    setBusy(key);
    setError(null);
    setNotice(null);
    try {
      const message = await action();
      if (message) setNotice(message);
      load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const add = (e: FormEvent) => {
    e.preventDefault();
    run("add", async () => {
      await api("/site/elections/", { method: "POST", body: { name } });
      setName("");
      setAdding(false);
    });
  };

  const activate = (election: Election) =>
    run(`activate-${election.id}`, async () => {
      const result = await api<{ reset: number }>(`/site/elections/${election.id}/activate/`, { method: "POST" });
      setConfirming(null);
      setOpen(false);
      return `${shortName(election.name)} : ${fr(result.reset)} adresse${result.reset > 1 ? "s" : ""} à revisiter.`;
    });

  const remove = (election: Election) => run(`remove-${election.id}`, () => api(`/site/elections/${election.id}/`, { method: "DELETE" }));

  const current = data?.elections.find((e) => e.is_current);

  return (
    <Sheet title="Admin" locate={false}>
      {error && <Alert>{error}</Alert>}
      {notice && <Alert kind="success">{notice}</Alert>}
      {!data && !error && <Loading />}

      {data && (
        <Card className="overflow-hidden">
          <button
            type="button"
            aria-expanded={open}
            className="flex w-full items-center gap-2 p-3.5 text-left hover:bg-zinc-50 active:bg-zinc-100"
            onClick={() => {
              setOpen(!open);
              setConfirming(null);
              setAdding(false);
            }}
          >
            <p className="min-w-0 flex-1 truncate">
              <span className="text-zinc-500">Élection : </span>
              <span className="font-semibold tracking-tight">{current ? shortName(current.name) : "aucune"}</span>
            </p>
            <ChevronDown className={`size-5 shrink-0 text-zinc-500 transition ${open ? "rotate-180" : ""}`} />
          </button>

          {open && (
            <div className="space-y-1 border-t border-zinc-950/[0.06] p-2">
              {data.elections.map((election) =>
                confirming?.id === election.id ? (
                  <div key={election.id} className="space-y-2.5 rounded-xl bg-amber-50 p-3 text-sm text-amber-950 ring-1 ring-amber-200/70">
                    <p>
                      Passer à <span className="font-semibold">{shortName(election.name)}</span> ? {fr(data.to_reset)} adresse
                      {data.to_reset > 1 ? "s" : ""} à revisiter.
                    </p>
                    <div className="grid grid-cols-2 gap-2">
                      <Button variant="secondary" size="sm" onClick={() => setConfirming(null)} disabled={busy !== null}>
                        Annuler
                      </Button>
                      <Button size="sm" loading={busy === `activate-${election.id}`} onClick={() => activate(election)}>
                        Confirmer
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div
                    key={election.id}
                    className={`flex items-center rounded-xl ${election.is_current ? "bg-brand-50 ring-1 ring-brand-200" : ""}`}
                  >
                    <button
                      type="button"
                      className={`flex min-w-0 flex-1 items-center gap-3 rounded-xl p-2.5 text-left disabled:opacity-50 ${
                        election.is_current ? "cursor-default" : "hover:bg-zinc-50 active:bg-zinc-100"
                      }`}
                      disabled={busy !== null && !election.is_current}
                      onClick={() => !election.is_current && setConfirming(election)}
                    >
                      <span
                        className={`flex size-5 shrink-0 items-center justify-center rounded-full ${
                          election.is_current ? "bg-brand-600 text-white" : "ring-2 ring-zinc-300"
                        }`}
                      >
                        {election.is_current && <Check className="size-3.5" strokeWidth={3} />}
                      </span>
                      <span className={`truncate ${election.is_current ? "font-semibold text-brand-900" : "font-medium"}`}>
                        {shortName(election.name)}
                      </span>
                    </button>
                    {!election.is_current && election.n_visits === 0 && (
                      <button
                        type="button"
                        aria-label={`Supprimer ${election.name}`}
                        className="mr-1 flex size-9 shrink-0 items-center justify-center rounded-xl text-zinc-400 hover:bg-zinc-100 hover:text-red-600"
                        disabled={busy !== null}
                        onClick={() => remove(election)}
                      >
                        {busy === `remove-${election.id}` ? <Spinner className="size-4" /> : <Trash2 className="size-4" />}
                      </button>
                    )}
                  </div>
                ),
              )}

              {adding ? (
                <form onSubmit={add} className="flex gap-2 pt-1">
                  <input
                    autoFocus
                    className={inputClass}
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Ex. Élection présidentielle 2027"
                    maxLength={128}
                  />
                  <Button type="submit" disabled={!name.trim()} loading={busy === "add"} className="shrink-0">
                    Ajouter
                  </Button>
                  <Button type="button" variant="ghost" icon={X} aria-label="Annuler" className="shrink-0 px-3" onClick={() => setAdding(false)} />
                </form>
              ) : (
                <button
                  type="button"
                  className="flex w-full items-center gap-3 rounded-xl p-2.5 text-left font-medium text-brand-700 hover:bg-zinc-50 active:bg-zinc-100"
                  onClick={() => {
                    setAdding(true);
                    setConfirming(null);
                    setName("");
                  }}
                >
                  <Plus className="size-5 shrink-0" strokeWidth={2.25} />
                  Ajouter une élection
                </button>
              )}
            </div>
          )}
        </Card>
      )}
    </Sheet>
  );
}
