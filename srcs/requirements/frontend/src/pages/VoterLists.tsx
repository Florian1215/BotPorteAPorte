import { Building2, ChevronRight, FileSpreadsheet, Plus, Save, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, errorMessage } from "../api/client";
import type { VoterList } from "../api/types";
import AddressImport from "../components/AddressImport";
import { Alert, Button, Card, EmptyState, Field, IconTile, inputClass, Loading, SectionTitle, Sheet } from "../components/ui";

const fr = (n: number) => n.toLocaleString("fr");

/** Site admins: the consular voter lists (LEC). Each organization depends on one of them. */
export default function VoterLists() {
  const [lists, setLists] = useState<VoterList[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    api<VoterList[]>("/manage/voter-lists/")
      .then(setLists)
      .catch((e) => setError(errorMessage(e)));
  }, []);

  return (
    <Sheet
      title="LEC"
      subtitle="Listes électorales consulaires"
      action={
        !creating && (
          <Button size="sm" icon={Plus} onClick={() => setCreating(true)}>
            Nouvelle
          </Button>
        )
      }
      locate={false}
    >
      {creating && (
        <VoterListForm
          onCancel={() => setCreating(false)}
          onSaved={(created) => navigate(`/lec/${created.id}`)}
        />
      )}
      {error && <Alert>{error}</Alert>}
      {!lists && !error && <Loading />}
      {lists?.length === 0 && !creating && (
        <EmptyState icon={FileSpreadsheet} title="Aucune LEC">
          Crée une LEC, importe la liste du consulat, puis rattache-lui les organisations qui en dépendent.
        </EmptyState>
      )}
      {lists?.map((l) => (
        <Link key={l.id} to={`/lec/${l.id}`} className="flex items-center gap-3 rounded-2xl bg-white p-3 ring-1 ring-zinc-950/[0.08] active:bg-zinc-50">
          <IconTile icon={FileSpreadsheet} />
          <div className="min-w-0 flex-1">
            <p className="truncate font-semibold tracking-tight">{l.name}</p>
            <p className="truncate text-sm text-zinc-500">
              {fr(l.n_active)} adresse{l.n_active > 1 ? "s" : ""} ·{" "}
              {l.organizations.length === 0 ? "aucune organisation" : l.organizations.map((o) => o.name).join(", ")}
            </p>
          </div>
          <ChevronRight className="size-5 shrink-0 text-zinc-300" />
        </Link>
      ))}
    </Sheet>
  );
}

/** Name and country (for geocoding the addresses) of a list: creation, or edition when `list` is given. */
function VoterListForm({ list, onCancel, onSaved }: { list?: VoterList; onCancel?: () => void; onSaved: (l: VoterList) => void }) {
  const [form, setForm] = useState({ name: list?.name ?? "", country_code: list?.country_code ?? "DE" });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      onSaved(
        await api<VoterList>(list ? `/manage/voter-lists/${list.id}/` : "/manage/voter-lists/", {
          method: list ? "PATCH" : "POST",
          body: form,
        }),
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={submit} className={list ? "space-y-3" : "space-y-3 rounded-2xl bg-zinc-50 p-4 ring-1 ring-zinc-950/5"}>
      {!list && (
        <p className="flex items-center gap-2 font-semibold tracking-tight">
          <FileSpreadsheet className="size-[18px] text-brand-600" /> Nouvelle LEC
        </p>
      )}
      {error && <Alert>{error}</Alert>}
      <div className="grid grid-cols-[1fr_6rem] gap-2">
        <Field label="Nom">
          <input
            className={inputClass}
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="LEC Berlin"
            maxLength={128}
            required
            autoFocus={!list}
          />
        </Field>
        <Field label="Pays">
          <input
            className={`${inputClass} uppercase`}
            value={form.country_code}
            onChange={(e) => setForm({ ...form, country_code: e.target.value.toUpperCase().slice(0, 2) })}
            placeholder="DE"
            minLength={2}
            maxLength={2}
            required
            title="Code pays à 2 lettres des adresses de la liste (pour les localiser)"
          />
        </Field>
      </div>
      {list ? (
        <Button type="submit" className="w-full" icon={Save} loading={loading}>
          Enregistrer
        </Button>
      ) : (
        <div className="grid grid-cols-2 gap-2">
          <Button type="button" variant="secondary" onClick={onCancel}>
            Annuler
          </Button>
          <Button type="submit" icon={Plus} loading={loading}>
            Créer
          </Button>
        </div>
      )}
    </form>
  );
}

/** One list: its import (same as before: people gone are disabled, addresses not found are left out…),
 * the organizations depending on it, its name. */
export function VoterListDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [list, setList] = useState<VoterList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(() => {
    api<VoterList>(`/manage/voter-lists/${id}/`)
      .then(setList)
      .catch((e) => setError(errorMessage(e)));
  }, [id]);
  useEffect(load, [load]);

  const remove = async () => {
    setDeleting(true);
    setError(null);
    try {
      await api(`/manage/voter-lists/${id}/`, { method: "DELETE" });
      navigate("/lec", { replace: true });
    } catch (e) {
      setError(errorMessage(e));
      setDeleting(false);
    }
  };

  return (
    <Sheet title={list?.name ?? "LEC"} locate={false}>
      {error && <Alert>{error}</Alert>}
      {saved && <Alert kind="success">{saved}</Alert>}
      {!list && !error && <Loading />}
      {list && (
        <>
          <SectionTitle>Liste du consulat</SectionTitle>
          <AddressImport voterList={list.id} />

          <SectionTitle>Organisations rattachées</SectionTitle>
          {list.organizations.length === 0 ? (
            <p className="text-sm text-zinc-500">
              Aucune. Choisis cette LEC à la création d'une organisation, ou dans ses réglages.
            </p>
          ) : (
            <Card className="divide-y divide-zinc-950/5">
              {list.organizations.map((o) => (
                <Link key={o.code} to={`/organizations/${o.code}`} className="flex items-center gap-3 px-3.5 py-3 active:bg-zinc-50">
                  <Building2 className="size-[18px] shrink-0 text-zinc-400" />
                  <span className="min-w-0 flex-1 truncate font-medium">{o.name}</span>
                  {o.city && <span className="shrink-0 text-sm text-zinc-500">{o.city}</span>}
                  <ChevronRight className="size-4 shrink-0 text-zinc-300" />
                </Link>
              ))}
            </Card>
          )}

          <SectionTitle>Informations</SectionTitle>
          <VoterListForm
            key={list.id}
            list={list}
            onSaved={(updated) => {
              setList(updated);
              setSaved("Modifications enregistrées.");
            }}
          />
          {list.n_active + list.n_disabled === 0 && (
            <Button variant="ghost" className="w-full" icon={Trash2} onClick={remove} loading={deleting}>
              Supprimer cette LEC
            </Button>
          )}
        </>
      )}
    </Sheet>
  );
}
