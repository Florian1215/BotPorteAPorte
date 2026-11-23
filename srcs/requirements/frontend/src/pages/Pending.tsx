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

  if (!user.first_name || !user.confidentiality_accepted_at) return <AskName />;

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

/** First login: the validators need to know who is behind the email, and the militant signs the confidentiality agreement. */
export function AskName() {
  const { user, updateProfile } = useAuth();
  const [firstName, setFirstName] = useState(user?.first_name ?? "");
  const [lastName, setLastName] = useState(user?.last_name ?? "");
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!accepted) {
      setError("Tu dois accepter l'engagement de confidentialité pour continuer.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await updateProfile({ first_name: firstName.trim(), last_name: lastName.trim(), accept_confidentiality: true });
    } catch (err) {
      setError(errorMessage(err));
      setLoading(false);
    }
  };

  const signer = [firstName.trim(), lastName.trim()].filter(Boolean).join(" ");

  return (
    <AuthShell title="Comment t'appelles-tu ?" subtitle="Pour que ton organisation sache qui valider." organization={user?.organization}>
      <form onSubmit={submit} className="space-y-4">
        {error && <Alert>{error}</Alert>}
        <Field label="Prénom">
          <input className={inputClass} value={firstName} onChange={(e) => setFirstName(e.target.value)} autoComplete="given-name" maxLength={150} required autoFocus />
        </Field>
        <Field label="Nom">
          <input className={inputClass} value={lastName} onChange={(e) => setLastName(e.target.value)} autoComplete="family-name" maxLength={150} required />
        </Field>
        <ConfidentialityAgreement signer={signer} />
        <label className="flex cursor-pointer items-start gap-3 rounded-xl bg-zinc-50 p-3 ring-1 ring-zinc-200">
          <input
            type="checkbox"
            className="mt-0.5 size-5 shrink-0 accent-brand-600"
            checked={accepted}
            onChange={(e) => setAccepted(e.target.checked)}
            required
          />
          <span className="text-sm leading-snug text-zinc-800">
            J'ai lu et j'accepte l'engagement de confidentialité ci-dessus. <strong>Lu et approuvé.</strong>
          </span>
        </label>
        <Button type="submit" className="w-full" icon={Check} loading={loading} disabled={!accepted}>
          Valider mon inscription
        </Button>
      </form>
    </AuthShell>
  );
}

/** Text of the confidentiality agreement (RGPD) every militant accepts before seeing any personal data. */
function ConfidentialityAgreement({ signer }: { signer: string }) {
  return (
    <div className="max-h-64 space-y-2 overflow-y-auto rounded-xl bg-white p-4 text-[13px] leading-relaxed text-zinc-700 ring-1 ring-zinc-200">
      <p className="text-center font-bold text-zinc-900">
        DÉCLARATION DE CONFIDENTIALITÉ
        <br />
        des données à caractère personnel
      </p>
      <p className="text-center font-semibold text-zinc-900">Campagne de Jean-Luc Mélenchon — Élection présidentielle 2027</p>
      <p>
        Je soussigné(e) <strong>{signer || "…"}</strong>, militant(e) bénévole pour la campagne de Jean-Luc Mélenchon à
        l'élection présidentielle de 2027, étant à ce titre amené·e à accéder à des données à caractère personnel pendant cette
        campagne, déclare reconnaître la confidentialité desdites données.
      </p>
      <p>
        Je m'engage, conformément aux dispositions de la loi n° 78-17 du 6 janvier 1978 modifiée relative à l'informatique, aux
        fichiers et aux libertés, et au Règlement (UE) 2016/679 du Parlement européen et du Conseil du 27 avril 2016 (RGPD), à
        prendre toutes les précautions conformes aux usages et à l'état de l'art, dans le cadre de mes attributions, afin de
        protéger la confidentialité des informations auxquelles j'ai accès.
      </p>
      <p>Je m'engage en particulier à :</p>
      <ul className="list-disc space-y-1 pl-5">
        <li>ne pas utiliser les données auxquelles je peux accéder à des fins autres que celles prévues par mes attributions ;</li>
        <li>
          ne divulguer ces données qu'aux personnes dûment autorisées, en raison de leurs fonctions, à en recevoir communication,
          qu'il s'agisse de personnes privées, publiques, physiques ou morales ;
        </li>
        <li>ne faire aucune copie de ces données sauf à ce que cela soit nécessaire à l'exécution de mes fonctions ;</li>
        <li>
          prendre toutes les mesures conformes aux usages et à l'état de l'art dans le cadre de mes attributions afin d'éviter
          l'utilisation détournée ou frauduleuse de ces données ;
        </li>
        <li>
          prendre toutes précautions conformes aux usages et à l'état de l'art pour préserver la sécurité physique et logique de
          ces données ;
        </li>
        <li>
          m'assurer, dans la limite de mes attributions, que seuls des moyens de communication sécurisés seront utilisés pour
          transférer ces données ;
        </li>
        <li>
          en cas de cessation de mes fonctions, restituer intégralement les données, fichiers informatiques et tout support
          d'information relatif à ces données, dans un délai de 7 jours, au ou à la responsable de mon groupe d'action ou à la
          personne désignée par celui-ci ou celle-ci.
        </li>
      </ul>
      <p>
        Cet engagement de confidentialité, en vigueur pendant toute la durée de mes fonctions, demeurera effectif sans limitation
        de durée après la cessation de mes fonctions, quelle qu'en soit la cause, dès lors qu'il concerne l'utilisation et la
        communication de données à caractère personnel.
      </p>
      <p>
        J'ai été informé(e) que toute violation du présent engagement m'expose à des sanctions disciplinaires et pénales
        conformément à la réglementation en vigueur, notamment au regard des articles 226-16 à 226-24 du code pénal.
      </p>
      <p className="text-xs text-zinc-500">
        Document établi conformément au RGPD (UE) 2016/679 et à la loi n° 78-17 du 6 janvier 1978 modifiée. La date et l'heure de
        ton acceptation sont enregistrées.
      </p>
    </div>
  );
}
