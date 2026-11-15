import { ArrowLeft, Mail, MailCheck, RotateCcw } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { errorMessage } from "../api/client";
import { OrganizationSelect, useOrganizations } from "../components/organization";
import { Alert, Button, Field, inputClass, Loading } from "../components/ui";
import { lastEmail, lastOrganization, useAuth } from "../context/AuthContext";
import AuthShell from "./AuthShell";

/** Passwordless login: organization + email, then the 6-digit code received by email (or its link). */
export default function Login() {
  const { requestCode, verifyCode } = useAuth();
  const organizations = useOrganizations();
  const [organization, setOrganization] = useState(lastOrganization);
  const [email, setEmail] = useState(lastEmail);
  const [sentTo, setSentTo] = useState<{ email: string; minutes: number } | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [loading, setLoading] = useState<"request" | "verify" | "resend" | null>(null);
  const codeInput = useRef<HTMLInputElement>(null);

  // Forget a remembered organization that no longer exists.
  const known = organizations?.some((o) => o.code === organization) ?? true;
  const current = known ? organization : "";
  const selected = organizations?.find((o) => o.code === current) ?? null;

  useEffect(() => {
    if (sentTo) codeInput.current?.focus();
  }, [sentTo]);

  const send = async (kind: "request" | "resend") => {
    setLoading(kind);
    setError(null);
    setInfo(null);
    try {
      const response = await requestCode(current, email);
      setSentTo({ email: response.email, minutes: response.expires_in_minutes });
      setCode("");
      if (kind === "resend") setInfo("Un nouveau code vient d'être envoyé.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(null);
    }
  };

  const verify = async (value: string) => {
    if (!sentTo) return;
    setLoading("verify");
    setError(null);
    setInfo(null);
    try {
      await verifyCode(sentTo.email, value);
    } catch (err) {
      setError(errorMessage(err));
      setCode("");
      codeInput.current?.focus();
      setLoading(null);
    }
  };

  const onCodeChange = (raw: string) => {
    const digits = raw.replace(/\D/g, "").slice(0, 6);
    setCode(digits);
    if (digits.length === 6 && loading === null) verify(digits);
  };

  if (sentTo)
    return (
      <AuthShell title="Vérifie tes emails" subtitle={<>Code envoyé à <strong className="font-semibold text-zinc-800">{sentTo.email}</strong></>} organization={selected}>
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            verify(code);
          }}
          className="space-y-4"
        >
          <div className="flex items-center gap-3 rounded-2xl bg-sky-50 p-3.5 text-sm text-sky-950 ring-1 ring-sky-200/70">
            <MailCheck className="size-5 shrink-0 text-sky-600" />
            <span>
              Entre le code à 6 chiffres, ou clique directement sur le lien de l'email. Valable {sentTo.minutes} minutes.
            </span>
          </div>
          {error && <Alert>{error}</Alert>}
          {info && <Alert kind="success">{info}</Alert>}
          <input
            ref={codeInput}
            className={`${inputClass} h-16 text-center font-mono text-3xl font-semibold tracking-[0.5em] placeholder:tracking-[0.5em] placeholder:text-zinc-300`}
            value={code}
            onChange={(e) => onCodeChange(e.target.value)}
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="\d{6}"
            placeholder="000000"
            aria-label="Code de connexion"
            required
          />
          <Button type="submit" className="w-full" loading={loading === "verify"} disabled={code.length !== 6}>
            Me connecter
          </Button>
          <div className="grid grid-cols-2 gap-2">
            <Button type="button" variant="ghost" size="sm" icon={ArrowLeft} onClick={() => (setSentTo(null), setError(null), setInfo(null))}>
              Changer d'email
            </Button>
            <Button type="button" variant="ghost" size="sm" icon={RotateCcw} loading={loading === "resend"} onClick={() => send("resend")}>
              Renvoyer le code
            </Button>
          </div>
        </form>
      </AuthShell>
    );

  return (
    <AuthShell title="Connexion" organization={selected}>
      {organizations === null ? (
        <Loading />
      ) : (
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            send("request");
          }}
          className="space-y-4"
        >
          {error && <Alert>{error}</Alert>}
          {organizations.length > 0 ? (
            <OrganizationSelect organizations={organizations} value={current} onChange={setOrganization} />
          ) : (
            <Alert kind="info">Aucune organisation n'existe encore : seul·e l'administrateur·rice du site peut se connecter pour en créer une.</Alert>
          )}
          <Field label="Adresse email">
            <input
              className={inputClass}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              inputMode="email"
              placeholder="prenom@exemple.org"
              required
            />
          </Field>
          <Button type="submit" className="w-full" icon={Mail} loading={loading === "request"}>
            Recevoir mon code
          </Button>
        </form>
      )}
    </AuthShell>
  );
}
