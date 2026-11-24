import { ArrowRightLeft, ChevronRight, FileSpreadsheet, ImagePlus, MapPin, Trash2, Users } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";

import { api, errorMessage } from "../api/client";
import type { OrganizationAdmin, User } from "../api/types";
import { OrgLogo } from "../components/organization";
import { Alert, Button, Card, IconTile, Loading, SectionTitle, Sheet } from "../components/ui";
import { useAuth } from "../context/AuthContext";

/** An organization: link to its members, its logo (changeable). Name, city and LEC are fixed at creation and only shown here. */
export default function OrganizationSettings() {
  const { user, setUser, refresh } = useAuth();
  const params = useParams();
  const code = params.code ?? user?.organization?.code;
  const [organization, setOrganization] = useState<OrganizationAdmin | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!code) return;
    setOrganization(null);
    api<OrganizationAdmin>(`/manage/organizations/${code}/`)
      .then(setOrganization)
      .catch((e) => setError(errorMessage(e)));
  }, [code]);

  if (!code) return <Navigate to="/organizations" replace />;

  const isCurrent = user?.organization?.code === code;
  const canEditLogo = Boolean(user?.is_site_admin || (user?.can_manage_organization && isCurrent));

  const saveLogo = async (file: File | null) => {
    if (file && file.size > 20 * 1024 * 1024) return setError("Image trop lourde (20 Mo maximum).");
    setBusy(file ? "logo" : "logo-remove");
    setError(null);
    setSaved(null);
    try {
      let body: FormData | undefined;
      if (file) {
        body = new FormData();
        body.append("logo", file);
      }
      const updated = await api<OrganizationAdmin>(`/manage/organizations/${code}/logo/`, { method: file ? "PUT" : "DELETE", body });
      setOrganization((current) => (current ? { ...current, logo_url: updated.logo_url } : updated));
      setSaved(file ? "Logo mis à jour." : "Logo retiré.");
      if (isCurrent) await refresh(); // header logo
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

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

          {canEditLogo && (
            <>
              <SectionTitle>Logo</SectionTitle>
              <Card className="flex items-center gap-3 p-3.5">
                <OrgLogo organization={organization} className="size-14 text-xl" />
                <input
                  ref={fileInput}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) saveLogo(file);
                    e.target.value = "";
                  }}
                />
                <div className="flex flex-1 flex-wrap items-center justify-end gap-2">
                  <Button variant="secondary" size="sm" icon={ImagePlus} loading={busy === "logo"} onClick={() => fileInput.current?.click()}>
                    {organization.logo_url ? "Changer" : "Ajouter un logo"}
                  </Button>
                  {organization.logo_url && (
                    <Button variant="ghost" size="sm" icon={Trash2} loading={busy === "logo-remove"} onClick={() => saveLogo(null)} aria-label="Retirer le logo" />
                  )}
                </div>
              </Card>
            </>
          )}

          <SectionTitle>Informations</SectionTitle>
          <Card className="divide-y divide-zinc-950/5">
            <div className="flex items-center gap-3 p-3.5">
              <IconTile icon={MapPin} />
              <div className="min-w-0 flex-1">
                <p className="truncate font-semibold tracking-tight">{organization.city || "Ville non renseignée"}</p>
                <p className="text-sm text-zinc-500">Ville de l'organisation</p>
              </div>
            </div>
            <div className="flex items-center gap-3 p-3.5">
              <IconTile icon={FileSpreadsheet} />
              <div className="min-w-0 flex-1">
                <p className="truncate font-semibold tracking-tight">{organization.voter_list_name ?? "Aucune LEC"}</p>
                <p className="text-sm text-zinc-500">
                  {organization.voter_list_name
                    ? `Adresses à moins de ${organization.radius_km} km de ${organization.city || "la ville"}`
                    : "Aucune liste d'adresses rattachée"}
                </p>
              </div>
            </div>
          </Card>

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
