import { Check, Hourglass, LogOut, RefreshCw } from "lucide-react";
import { useState, type FormEvent } from "react";

import { errorMessage } from "../api/client";
import { Alert, Button, Field, inputClass } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import AuthShell from "./AuthShell";

export default function Pending() {
  const { user, refresh, logout } = useAuth();
  const [checking, setChecking] = useState(false);
  if (!user) return null;

  if (!user.first_name) return <AskName />;

  return (
    <AuthShell title={`Bienvenue ${user.first_name}`} organization={user.organization}>
      <div className="space-y-4">
        <div className="flex flex-col items-center rounded-3xl bg-amber-50 px-5 py-6 text-center ring-1 ring-amber-200/70">
          <span className="flex size-12 items-center justify-center rounded-2xl bg-amber-500 text-white">
            <Hourglass className="size-6" />
          </span>
          <p className="mt-3 font-semibold text-amber-950">
            {user.suspended_at ? "Ton accès est suspendu" : "Inscription en attente de validation"}
          </p>
          <p className="mt-1 text-sm leading-relaxed text-amber-900/80">
            {user.suspended_at && user.organization ? (
              <>
                Un·e responsable de <strong>{user.organization.name}</strong> a suspendu ton accès au porte-à-porte. Contacte-les
                pour le retrouver, avec ton adresse :
              </>
            ) : user.organization ? (
              <>
                Un·e militant·e aguerri·e ou un·e responsable de <strong>{user.organization.name}</strong> doit valider ton
                compte. Tu peux les prévenir en leur donnant ton adresse :
              </>
            ) : (
              "Ton compte n'est rattaché à aucune organisation. Contacte ton groupe d'action en leur donnant ton adresse :"
            )}
          </p>
          <p className="mt-3 max-w-full truncate rounded-xl bg-white px-4 py-2 text-[15px] font-semibold text-zinc-900 ring-1 ring-amber-200">
            {user.email}
          </p>
        </div>
        <Button
          className="w-full"
          icon={RefreshCw}
          loading={checking}
          onClick={() => {
            setChecking(true);
            refresh().finally(() => setChecking(false));
          }}
        >
          Mon compte a été validé, vérifier
        </Button>
        <Button variant="ghost" icon={LogOut} className="w-full" onClick={() => logout()}>
          Se déconnecter
        </Button>
      </div>
    </AuthShell>
  );
}

/** First login: the validators need to know who is behind the email. */
export function AskName() {
  const { user, updateProfile } = useAuth();
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await updateProfile({ first_name: firstName.trim(), last_name: lastName.trim() });
    } catch (err) {
      setError(errorMessage(err));
      setLoading(false);
    }
  };

  return (
    <AuthShell title="Comment t'appelles-tu ?" subtitle="Pour que ton organisation sache qui valider." organization={user?.organization}>
      <form onSubmit={submit} className="space-y-4">
        {error && <Alert>{error}</Alert>}
        <Field label="Prénom">
          <input className={inputClass} value={firstName} onChange={(e) => setFirstName(e.target.value)} autoComplete="given-name" maxLength={150} required autoFocus />
        </Field>
        <Field label="Nom">
          <input className={inputClass} value={lastName} onChange={(e) => setLastName(e.target.value)} autoComplete="family-name" maxLength={150} />
        </Field>
        <Button type="submit" className="w-full" icon={Check} loading={loading}>
          Continuer
        </Button>
      </form>
    </AuthShell>
  );
}
