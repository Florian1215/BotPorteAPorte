import { Building2, ChevronRight, Plus } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { api, errorMessage } from "../api/client";
import type { CityFields, OrganizationAdmin } from "../api/types";
import CityPicker from "../components/CityPicker";
import VoterListPicker, { type VoterListChoice } from "../components/VoterListPicker";
import { OrgLogo } from "../components/organization";
import { Alert, Button, EmptyState, Field, inputClass, Loading, Sheet } from "../components/ui";
import { useAuth } from "../context/AuthContext";

/** Site admin: every organization, and creation of new ones. */
export default function Organizations() {
  const { user } = useAuth();
  const [organizations, setOrganizations] = useState<OrganizationAdmin[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    api<OrganizationAdmin[]>("/manage/organizations/")
      .then(setOrganizations)
      .catch((e) => setError(errorMessage(e)));
  }, []);

  return (
    <Sheet
      title="Organisations"
      subtitle={organizations && `${organizations.length} organisation${organizations.length > 1 ? "s" : ""}`}
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
        <CreateOrganization
          onCancel={() => setCreating(false)}
          onCreated={(o) => {
            setOrganizations((list) => [...(list ?? []), o].sort((a, b) => a.name.localeCompare(b.name)));
            setCreating(false);
          }}
        />
      )}
      {error && <Alert>{error}</Alert>}
      {!organizations && !error && (
<Loading />
      )}
      {organizations?.length === 0 && !creating && (
        <EmptyState icon={Building2} title="Aucune organisation">
          Crée la première pour que les militant·es puissent s'inscrire.
        </EmptyState>
      )}
      {organizations?.map((o) => (
        <Link key={o.code} to={`/organizations/${o.code}`} className="flex items-center gap-3 rounded-2xl bg-white p-3 ring-1 ring-zinc-950/[0.08] active:bg-zinc-50">
          <OrgLogo organization={o} className="size-11 text-lg" />
          <div className="min-w-0 flex-1">
            <p className="flex items-center gap-2 font-semibold tracking-tight">
              <span className="truncate">{o.name}</span>
              {user?.organization?.code === o.code && (
                <span className="shrink-0 rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-semibold text-brand-700">Actuelle</span>
              )}
            </p>
            <p className="text-sm text-zinc-500">
              {o.city ? `${o.city} · ` : ""}
              {o.voter_list_name ? `${o.voter_list_name} · ` : ""}
              {o.n_members ?? 0} membre{(o.n_members ?? 0) > 1 ? "s" : ""}
              {o.n_pending ? <span className="font-semibold text-amber-700"> · {o.n_pending} à valider</span> : null}
            </p>
          </div>
          <ChevronRight className="size-5 shrink-0 text-zinc-300" />
        </Link>
      ))}
    </Sheet>
  );
}

function CreateOrganization({ onCancel, onCreated }: { onCancel: () => void; onCreated: (o: OrganizationAdmin) => void }) {
  const [form, setForm] = useState<{ name: string } & CityFields & VoterListChoice>({
    name: "",
    city: "",
    city_lat: null,
    city_lon: null,
    country_code: "",
    voter_list: null,
    radius_km: 30,
  });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!form.city) return setError("Choisis la ville de l'organisation dans la liste.");
    if (!form.voter_list) return setError("Choisis la LEC dont dépend l'organisation.");
    setLoading(true);
    setError(null);
    try {
      onCreated(await api<OrganizationAdmin>("/manage/organizations/", { method: "POST", body: form }));
    } catch (err) {
      setError(errorMessage(err));
      setLoading(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3 rounded-2xl bg-zinc-50 p-4 ring-1 ring-zinc-950/5">
      <p className="flex items-center gap-2 font-semibold tracking-tight">
        <Building2 className="size-[18px] text-brand-600" /> Nouvelle organisation
      </p>
      {error && <Alert>{error}</Alert>}
      <Field label="Nom">
        <input
          className={inputClass}
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          placeholder="GA Berlin Nord"
          maxLength={128}
          required
          autoFocus
        />
      </Field>
      <CityPicker value={form} onChange={(city) => setForm({ ...form, ...city })} />
      <VoterListPicker value={form} onChange={(choice) => setForm({ ...form, ...choice })} />
      <div className="grid grid-cols-2 gap-2">
        <Button type="button" variant="secondary" onClick={onCancel}>
          Annuler
        </Button>
        <Button type="submit" icon={Plus} loading={loading}>
          Créer
        </Button>
      </div>
    </form>
  );
}
