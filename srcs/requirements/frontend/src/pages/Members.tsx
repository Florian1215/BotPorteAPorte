import { Check, ChevronDown, Crown, Mail, PauseCircle, PlayCircle, Search, Settings2, Shield, ShieldCheck, User, UserPlus, Users, X, type LucideIcon } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { api, errorMessage } from "../api/client";
import type { Member, OrganizationAdmin, Role } from "../api/types";
import { Alert, Button, EmptyState, inputClass, Loading, SectionTitle, Sheet, Spinner } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { notifyPendingChanged } from "../hooks/usePendingCount";
import { ROLE_LABEL, ROLES } from "../lib/constants";

const RANK: Record<Role, number> = { militant: 0, experienced: 1, manager: 2, admin: 3 };

/**
 * One list: sign-ups waiting for approval on top, then the members.
 * Militant·es aguerri·es only see (and handle) the sign-ups; responsables and admins manage roles too.
 */
export default function Members() {
  const { user } = useAuth();
  const params = useParams();
  const code = params.code ?? user?.organization?.code ?? "";
  const canManage = Boolean(user?.is_site_admin || user?.can_manage_organization);
  const [pending, setPending] = useState<Member[] | null>(null);
  const [members, setMembers] = useState<Member[] | null>(null);
  const [organization, setOrganization] = useState<OrganizationAdmin | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [adding, setAdding] = useState(false);
  const [added, setAdded] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api<Member[]>("/manage/members/", { query: { organization: code, status: "pending" } })
      .then(setPending)
      .catch((e) => setError(errorMessage(e)));
    if (canManage)
      api<Member[]>("/manage/members/", { query: { organization: code, status: "active" } })
        .then(setMembers)
        .catch((e) => setError(errorMessage(e)));
    else setMembers([]);
  }, [code, canManage]);

  useEffect(load, [load]);
  useEffect(() => {
    if (canManage && code) api<OrganizationAdmin>(`/manage/organizations/${code}/`).then(setOrganization).catch(() => null);
  }, [canManage, code]);

  const matches = (m: Member) => `${m.first_name} ${m.last_name} ${m.email}`.toLowerCase().includes(search.trim().toLowerCase());
  const visiblePending = useMemo(() => pending?.filter(matches), [pending, search]); // eslint-disable-line react-hooks/exhaustive-deps
  const visibleMembers = useMemo(() => members?.filter(matches), [members, search]); // eslint-disable-line react-hooks/exhaustive-deps

  const approved = (m: Member) => {
    setPending((list) => (list ?? []).filter((p) => p.id !== m.id));
    if (canManage) setMembers((list) => [...(list ?? []), m].sort((a, b) => displayName(a).localeCompare(displayName(b))));
    notifyPendingChanged();
  };
  const refused = (id: number) => {
    setPending((list) => (list ?? []).filter((p) => p.id !== id));
    notifyPendingChanged();
  };
  // Suspended members stay in the list (marked as such), to be reactivated from there.
  const updated = (m: Member) => setMembers((list) => (list ?? []).map((x) => (x.id === m.id ? m : x)));

  const loading = (!pending || !members) && !error;
  const total = (pending?.length ?? 0) + (members?.length ?? 0);

  return (
    <Sheet
      title={canManage ? `Membres${members ? ` (${members.length})` : ""}` : "Inscriptions à valider"}
      subtitle={
        <span className="flex items-center gap-1.5">
          {organization?.name ?? user?.organization?.name}
          {user?.is_site_admin && params.code && (
            <Link to={`/organizations/${code}`} className="inline-flex items-center gap-1 font-semibold text-brand-600">
              <Settings2 className="size-3.5" /> réglages
            </Link>
          )}
        </span>
      }
      action={
        !adding && (
          <Button size="sm" icon={UserPlus} onClick={() => (setAdding(true), setAdded(null))}>
            Ajouter
          </Button>
        )
      }
      locate={false}
    >
      {adding && (
        <AddMember
          organization={code}
          myRole={canManage ? (user?.role ?? "militant") : null}
          onCancel={() => setAdding(false)}
          onAdded={(m) => {
            setAdding(false);
            setAdded(`${m.email} peut maintenant se connecter.`);
            setPending((list) => (list ?? []).filter((p) => p.id !== m.id));
            if (canManage) setMembers((list) => [...(list ?? []).filter((x) => x.id !== m.id), m]);
            notifyPendingChanged();
          }}
        />
      )}
      {added && <Alert kind="success">{added}</Alert>}
      {error && <Alert>{error}</Alert>}
      {loading && <Loading />}

      {total > 8 && (
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-3.5 size-[18px] -translate-y-1/2 text-zinc-400" />
          <input className={`${inputClass} pl-10`} placeholder="Rechercher…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
      )}

      {visiblePending && visiblePending.length > 0 && (
        <>
          <SectionTitle>
            À valider <span className="ml-1 rounded-full bg-brand-600 px-1.5 py-0.5 text-xs text-white tabular-nums">{visiblePending.length}</span>
          </SectionTitle>
          {visiblePending.map((m) => (
            <PendingCard key={m.id} member={m} onApproved={approved} onRefused={refused} />
          ))}
        </>
      )}

      {canManage && visibleMembers && visibleMembers.length > 0 && (
        <>
          {visiblePending && visiblePending.length > 0 && <div className="h-1" />}
          <div className="-mx-1 divide-y divide-zinc-950/[0.06]">
            {visibleMembers.map((m) => (
              <MemberRow key={m.id} member={m} isMe={m.id === user?.id} myRole={user?.role ?? "militant"} onChange={updated} />
            ))}
          </div>
        </>
      )}

      {!loading && visiblePending?.length === 0 && (!canManage || visibleMembers?.length === 0) && (
        <EmptyState icon={search ? Search : Users} title={search ? "Aucun résultat" : canManage ? "Aucun membre" : "Aucune inscription en attente"}>
        </EmptyState>
      )}
    </Sheet>
  );
}

function displayName(m: Member) {
  return [m.first_name, m.last_name].filter(Boolean).join(" ") || m.email;
}

function Avatar({ member }: { member: Member }) {
  const letter = (member.first_name || member.email).trim().charAt(0).toUpperCase();
  return <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-zinc-100 text-sm font-semibold text-zinc-600">{letter}</span>;
}

function PendingCard({ member, onApproved, onRefused }: { member: Member; onApproved: (m: Member) => void; onRefused: (id: number) => void }) {
  const [busy, setBusy] = useState<"approve" | "refuse" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const act = async (kind: "approve" | "refuse") => {
    setBusy(kind);
    setError(null);
    try {
      if (kind === "approve") onApproved(await api<Member>(`/manage/members/${member.id}/`, { method: "PATCH", body: { is_approved: true } }));
      else {
        await api(`/manage/members/${member.id}/`, { method: "DELETE" });
        onRefused(member.id);
      }
    } catch (e) {
      setError(errorMessage(e));
      setBusy(null);
    }
  };

  return (
    <div className="space-y-3 rounded-2xl bg-white p-3.5 ring-1 ring-zinc-950/[0.08]">
      <div className="flex items-center gap-3">
        <Avatar member={member} />
        <div className="min-w-0">
          <p className="truncate font-semibold tracking-tight">{displayName(member)}</p>
          <p className="truncate text-sm text-zinc-500">{member.email}</p>
        </div>
      </div>
      {error && <Alert>{error}</Alert>}
      <div className="grid grid-cols-2 gap-2">
        <Button variant="secondary" size="sm" icon={X} loading={busy === "refuse"} onClick={() => act("refuse")} disabled={busy !== null}>
          Refuser
        </Button>
        <Button size="sm" icon={Check} loading={busy === "approve"} onClick={() => act("approve")} disabled={busy !== null}>
          Accepter
        </Button>
      </div>
    </div>
  );
}

/** A member: tap the role label to change their rights (or suspend them). */
function MemberRow({ member, isMe, myRole, onChange }: { member: Member; isMe: boolean; myRole: Role; onChange: (m: Member) => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmSuspend, setConfirmSuspend] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const menu = useRef<HTMLDivElement>(null);
  const popup = useRef<HTMLDivElement>(null);
  const [upward, setUpward] = useState(false);
  const editable = !isMe && RANK[member.role] <= RANK[myRole];
  const suspended = !member.is_approved && member.suspended_at !== null;

  // Near the bottom of the list, open the menu above the label so it is reachable without scrolling.
  useLayoutEffect(() => {
    if (!open || !menu.current || !popup.current) return;
    const scroller = menu.current.closest(".overflow-y-auto") ?? document.documentElement;
    const area = scroller.getBoundingClientRect();
    const anchor = menu.current.getBoundingClientRect();
    const height = popup.current.offsetHeight + 8;
    const below = area.bottom - anchor.bottom;
    const above = anchor.top - area.top;
    setUpward(below < height && above > below);
  }, [open, confirmSuspend]);

  useEffect(() => {
    if (!open) return;
    const close = (e: PointerEvent) => {
      if (menu.current && !menu.current.contains(e.target as Node)) {
        setOpen(false);
        setConfirmSuspend(false);
      }
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);

  const patch = async (body: { role?: Role; is_approved?: boolean }, key: string) => {
    setBusy(key);
    setError(null);
    try {
      onChange(await api<Member>(`/manage/members/${member.id}/`, { method: "PATCH", body }));
      setOpen(false);
      setConfirmSuspend(false);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex items-center gap-3 px-1 py-3">
      <div className={suspended ? "opacity-40 grayscale" : ""}>
        <Avatar member={member} />
      </div>
      <div className="min-w-0 flex-1">
        <p className={`truncate font-semibold tracking-tight ${suspended ? "text-zinc-400" : ""}`}>
          {displayName(member)} {isMe && <span className="text-sm font-normal text-zinc-500">(toi)</span>}
        </p>
        <p className="truncate text-sm text-zinc-500">
          {suspended ? (
            <span className="font-medium text-zinc-500">
              <PauseCircle className="mr-1 inline size-3.5 -translate-y-px" />
              Accès suspendu
            </span>
          ) : (
            <>
              {member.email}
              {!member.last_login && <span className="text-amber-600"> · jamais connecté·e</span>}
            </>
          )}
        </p>
        {suspended && error && <p className="text-xs text-red-600">{error}</p>}
      </div>

      <div ref={menu} className="relative shrink-0">
        {suspended ? (
          editable && (
            <Button variant="secondary" size="sm" icon={PlayCircle} loading={busy === "reactivate"} onClick={() => patch({ is_approved: true }, "reactivate")}>
              Réactiver
            </Button>
          )
        ) : editable ? (
          <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-haspopup="menu" className="rounded-full active:opacity-80">
            <RoleBadge role={member.role} chevron />
          </button>
        ) : (
          <RoleBadge role={member.role} />
        )}

        {open && (
          <div
            ref={popup}
            role="menu"
            className={`absolute right-0 z-20 w-64 rounded-2xl bg-white p-1.5 shadow-float ring-1 ring-zinc-950/10 ${
              upward ? "bottom-full mb-1.5" : "top-full mt-1.5"
            }`}
          >
            {error && <p className="px-2.5 py-1.5 text-xs text-red-600">{error}</p>}
            {ROLES.filter((r) => RANK[r.value] <= RANK[myRole]).map((r) => {
              const Icon = ROLE_ICONS[r.value];
              const current = r.value === member.role;
              return (
                <button
                  key={r.value}
                  type="button"
                  role="menuitemradio"
                  aria-checked={current}
                  disabled={busy !== null}
                  onClick={() => (current ? setOpen(false) : patch({ role: r.value }, r.value))}
                  className={`flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left ${
                    current ? "bg-brand-50 text-brand-700" : "active:bg-zinc-50"
                  }`}
                >
                  <span className={`flex size-7 shrink-0 items-center justify-center rounded-lg ${ROLE_STYLES[r.value]}`}>
                    <Icon className="size-3.5" />
                  </span>
                  <span className="min-w-0 flex-1 text-sm font-semibold">{r.label}</span>
                  {busy === r.value ? <Spinner className="size-4 text-brand-600" /> : current && <Check className="size-4 shrink-0 text-brand-600" strokeWidth={3} />}
                </button>
              );
            })}
            <div className="my-1 border-t border-zinc-950/5" />
            {confirmSuspend ? (
              <div className="space-y-2 px-2.5 py-1.5">
                <p className="text-xs text-zinc-600">Plus d'accès au porte-à-porte. Tu pourras le réactiver depuis cette liste.</p>
                <div className="grid grid-cols-2 gap-1.5">
                  <Button variant="secondary" size="sm" onClick={() => setConfirmSuspend(false)} disabled={busy !== null}>
                    Annuler
                  </Button>
                  <Button variant="dark" size="sm" loading={busy === "suspend"} onClick={() => patch({ is_approved: false }, "suspend")}>
                    Suspendre
                  </Button>
                </div>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setConfirmSuspend(true)}
                className="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-sm font-semibold text-red-600 active:bg-red-50"
              >
                <PauseCircle className="size-4" /> Suspendre l'accès
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** The email (the person fills in their name at their first login) and, for responsables, the role. */
function AddMember({
  organization,
  myRole,
  onCancel,
  onAdded,
}: {
  organization: string;
  /** Role of the person adding, when they can give roles (responsables); null: militant·e only. */
  myRole: Role | null;
  onCancel: () => void;
  onAdded: (m: Member) => void;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("militant");
  const roles = myRole ? ROLES.filter((r) => RANK[r.value] <= RANK[myRole]) : [];
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      onAdded(await api<Member>("/manage/members/", { method: "POST", body: { email, organization, role } }));
    } catch (err) {
      setError(errorMessage(err));
      setLoading(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3 rounded-2xl bg-zinc-50 p-3.5 ring-1 ring-zinc-950/5">
      <p className="text-xs leading-relaxed text-zinc-500">
        Validé·e d'office : la personne reçoit une invitation et n'a qu'à se connecter avec cette adresse.
      </p>
      {error && <Alert>{error}</Alert>}
      <div className="relative">
        <Mail className="pointer-events-none absolute top-1/2 left-3.5 size-[18px] -translate-y-1/2 text-zinc-400" />
        <input
          className={`${inputClass} pl-10`}
          type="email"
          inputMode="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="adresse@email.org"
          aria-label="Adresse email"
          required
          autoFocus
        />
      </div>
      {roles.length > 1 && (
        <div role="radiogroup" aria-label="Rôle" className="space-y-1">
          <p className="px-0.5 text-xs font-semibold text-zinc-500">Rôle</p>
          {roles.map((r) => {
            const Icon = ROLE_ICONS[r.value];
            const selected = role === r.value;
            return (
              <button
                key={r.value}
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => setRole(r.value)}
                className={`flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left transition ${
                  selected ? "bg-brand-50 ring-1 ring-brand-200" : "bg-white ring-1 ring-zinc-950/5 active:bg-zinc-50"
                }`}
              >
                <span className={`flex size-7 shrink-0 items-center justify-center rounded-lg ${ROLE_STYLES[r.value]}`}>
                  <Icon className="size-3.5" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className={`block text-sm font-semibold ${selected ? "text-brand-700" : ""}`}>{r.label}</span>
                  <span className="block truncate text-xs text-zinc-500">{r.description}</span>
                </span>
                <span
                  className={`flex size-5 shrink-0 items-center justify-center rounded-full ${
                    selected ? "bg-brand-600 text-white" : "ring-2 ring-zinc-300"
                  }`}
                >
                  {selected && <Check className="size-3.5" strokeWidth={3} />}
                </span>
              </button>
            );
          })}
        </div>
      )}
      <div className="grid grid-cols-2 gap-2">
        <Button type="button" variant="secondary" size="sm" onClick={onCancel}>
          Annuler
        </Button>
        <Button type="submit" size="sm" icon={UserPlus} loading={loading}>
          Ajouter
        </Button>
      </div>
    </form>
  );
}

const ROLE_ICONS: Record<Role, LucideIcon> = { militant: User, experienced: ShieldCheck, manager: Shield, admin: Crown };

const ROLE_STYLES: Record<Role, string> = {
  militant: "bg-zinc-100 text-zinc-600",
  experienced: "bg-sky-50 text-sky-700",
  manager: "bg-brand-50 text-brand-700",
  admin: "bg-zinc-900 text-white",
};

const SHORT_ROLE: Record<Role, string> = { militant: "Militant·e", experienced: "Aguerri·e", manager: "Responsable", admin: "Admin" };

export function RoleBadge({ role, chevron = false }: { role: Role; chevron?: boolean }) {
  const Icon = ROLE_ICONS[role];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full py-1 pr-2 pl-2 text-xs font-semibold ${ROLE_STYLES[role]}`} title={ROLE_LABEL[role]}>
      <Icon className="size-3.5" />
      {SHORT_ROLE[role]}
      {chevron && <ChevronDown className="size-3.5 opacity-60" />}
    </span>
  );
}
