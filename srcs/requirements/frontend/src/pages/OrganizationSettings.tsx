import { ArrowRightLeft, ChevronRight, FileSpreadsheet, ImagePlus, Save, Trash2, Users } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, Navigate, useParams } from "react-router-dom";

import { api, errorMessage } from "../api/client";
import type { CityFields, OrganizationAdmin, User } from "../api/types";
import CityPicker from "../components/CityPicker";
import VoterListPicker, { type VoterListChoice } from "../components/VoterListPicker";
import { OrgLogo } from "../components/organization";
import { Alert, Button, Card, Field, IconTile, inputClass, Loading, SectionTitle, Sheet } from "../components/ui";
import { useAuth } from "../context/AuthContext";

/** Name, country and logo of an organization (its responsable, or a site admin). */
export default function OrganizationSettings() {
  const { user, refresh, setUser } = useAuth();
  const params = useParams();
  const code = params.code ?? user?.organization?.code;
  const [organization, setOrganization] = useState<OrganizationAdmin | null>(null);
  const [form, setForm] = useState<{ name: string } & CityFields>({ name: "", city: "", city_lat: null, city_lon: null, country_code: "" });
  const [lec, setLec] = useState<VoterListChoice>({ voter_list: null, radius_km: 30 });
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!code) return;
    setOrganization(null);
    api<OrganizationAdmin>(`/manage/organizations/${code}/`)
      .then((o) => {
        setOrganization(o);
        setForm({ name: o.name, city: o.city, city_lat: o.city_lat, city_lon: o.city_lon, country_code: o.country_code });
        setLec({ voter_list: o.voter_list, radius_km: o.radius_km });
      })
      .catch((e) => setError(errorMessage(e)));
  }, [code]);

  if (!code) return <Navigate to="/organizations" replace />;

  const isCurrent = user?.organization?.code === code;

  const run = async (key: string, action: () => Promise<OrganizationAdmin>, message: string) => {
    setBusy(key);
    setError(null);
    setSaved(null);
    try {
      const updated = await action();
      setOrganization((o) => ({ ...o, ...updated }));
      setSaved(message);
      if (isCurrent) await refresh(); // name / logo shown in the menu
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const save = (e: FormEvent) => {
    e.preventDefault();
    // City fields only once a city was picked (older organizations may not have one yet).
    const body = form.city ? form : { name: form.name };
    run("save", () => api(`/manage/organizations/${code}/`, { method: "PATCH", body }), "Modifications enregistrées.");
  };

  const saveLec = (e: FormEvent) => {
    e.preventDefault();
    run("lec", () => api(`/manage/organizations/${code}/`, { method: "PATCH", body: lec }), "LEC enregistrée.");
  };

  const upload = (file: File) => {
    if (file.size > 20 * 1024 * 1024) {
      setError("Image trop lourde (20 Mo maximum).");
      return;
    }
    const body = new FormData();
    body.append("logo", file);
    run("logo", () => api(`/manage/organizations/${code}/logo/`, { method: "POST", body }), "Logo mis à jour.");
  };

  const removeLogo = () =>
    run("remove", () => api(`/manage/organizations/${code}/logo/`, { method: "DELETE" }), "Logo supprimé.");

  const enter = async () => {
    setBusy("enter");
    setError(null);
    try {
      setUser(await api<User>(`/manage/organizations/${code}/enter/`, { method: "POST" }));
      setSaved(`Tu es maintenant dans « ${organization?.name} ».`);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Sheet
      title={organization?.name ?? "Organisation"}
      subtitle={organization?.city || undefined}
      action={organization && <OrgLogo organization={organization} className="size-11 text-lg" />}
      locate={false}
    >
      {error && <Alert>{error}</Alert>}
      {saved && <Alert kind="success">{saved}</Alert>}
      {!organization && !error && (
<Loading />
      )}

      {organization && (
        <>
          <Link
            to={user?.is_site_admin && !isCurrent ? `/organizations/${code}/members` : "/members"}
            className="flex items-center gap-3 rounded-2xl bg-white p-3.5 ring-1 ring-zinc-950/[0.08] active:bg-zinc-50"
          >
            <IconTile icon={Users} />
            <div className="min-w-0 flex-1">
              <p className="font-semibold tracking-tight">Gérer les membres</p>
              <p className="text-sm text-zinc-500">
                {organization.n_members ?? 0} membre{(organization.n_members ?? 0) > 1 ? "s" : ""}
                {organization.n_pending ? ` · ${organization.n_pending} inscription${organization.n_pending > 1 ? "s" : ""} à valider` : ""}
              </p>
            </div>
            <ChevronRight className="size-5 text-zinc-300" />
          </Link>

          <SectionTitle>Logo</SectionTitle>
          <Card className="space-y-3 p-3.5">
            <div className="flex items-center gap-4">
              <OrgLogo organization={organization} className="size-20 rounded-2xl text-3xl" />
              <div className="flex flex-1 flex-col gap-2">
                <input
                  ref={fileInput}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) upload(file);
                    e.target.value = "";
                  }}
                />
                <Button variant="secondary" size="sm" icon={ImagePlus} onClick={() => fileInput.current?.click()} loading={busy === "logo"}>
                  {organization.logo_url ? "Changer le logo" : "Ajouter un logo"}
                </Button>
                {organization.logo_url && (
                  <Button variant="ghost" size="sm" icon={Trash2} onClick={removeLogo} loading={busy === "remove"}>
                    Retirer
                  </Button>
                )}
              </div>
            </div>
          </Card>

          <SectionTitle>Adresses à visiter</SectionTitle>
          {user?.is_site_admin ? (
            <form onSubmit={saveLec} className="space-y-3">
              <VoterListPicker value={lec} onChange={setLec} />
              <p className="text-xs text-zinc-500">
                Les adresses de la LEC à moins de {lec.radius_km} km de la ville. La liste s'importe depuis le menu « LEC ».
              </p>
              <Button type="submit" variant="secondary" className="w-full" icon={Save} loading={busy === "lec"}>
                Enregistrer la LEC
              </Button>
            </form>
          ) : (
            <Card className="flex items-center gap-3 p-3.5">
              <IconTile icon={FileSpreadsheet} />
              <div className="min-w-0 flex-1">
                <p className="truncate font-semibold tracking-tight">{organization.voter_list_name ?? "Aucune LEC"}</p>
                <p className="text-sm text-zinc-500">
                  {organization.voter_list_name
                    ? `Adresses à moins de ${organization.radius_km} km de ${organization.city || "la ville"}. Gérée par les admins du site.`
                    : "Un·e admin du site doit rattacher l'organisation à une LEC."}
                </p>
              </div>
            </Card>
          )}

          <SectionTitle>Informations</SectionTitle>
          <form onSubmit={save} className="space-y-4">
            <Field label="Nom de l'organisation">
              <input className={inputClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} maxLength={128} required />
            </Field>
            <CityPicker value={form} onChange={(city) => setForm({ ...form, ...city })} />
            <Button type="submit" className="w-full" icon={Save} loading={busy === "save"}>
              Enregistrer
            </Button>
          </form>

          {user?.is_site_admin && !isCurrent && (
            <Button variant="dark" className="w-full" icon={ArrowRightLeft} onClick={enter} loading={busy === "enter"}>
              Basculer vers cette organisation
            </Button>
          )}
        </>
      )}
    </Sheet>
  );
}
