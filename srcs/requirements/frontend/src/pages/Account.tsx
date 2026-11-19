import { ArrowLeft, Check, Link2, Mail, MailCheck, Pencil, RotateCcw, Save, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { api, errorMessage } from "../api/client";
import type { LoginRequestResponse, NavigationApp, User } from "../api/types";
import { Alert, Button, Card, Field, inputClass, SectionTitle, Segmented, Sheet } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { NAVIGATION_APPS, ROLE_LABEL } from "../lib/constants";

/** The user's own information: name, and email (changed only once the new address is confirmed). */
export default function Account() {
  const { user, updateProfile } = useAuth();
  const [names, setNames] = useState({ first_name: user?.first_name ?? "", last_name: user?.last_name ?? "" });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!user) return null;
  const dirty = names.first_name.trim() !== user.first_name || names.last_name.trim() !== user.last_name;

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await updateProfile({ first_name: names.first_name.trim(), last_name: names.last_name.trim() });
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Sheet title="Mon compte" subtitle={`${ROLE_LABEL[user.role]}${user.organization ? ` · ${user.organization.name}` : ""}`} locate={false}>
      <SectionTitle>Identité</SectionTitle>
      <form onSubmit={save} className="space-y-3">
        {error && <Alert>{error}</Alert>}
        {saved && !dirty && <Alert kind="success">Modifications enregistrées.</Alert>}
        <div className="grid grid-cols-2 gap-2">
          <Field label="Prénom">
            <input
              className={inputClass}
              value={names.first_name}
              onChange={(e) => setNames({ ...names, first_name: e.target.value })}
              autoComplete="given-name"
              maxLength={150}
              required
            />
          </Field>
          <Field label="Nom">
            <input
              className={inputClass}
              value={names.last_name}
              onChange={(e) => setNames({ ...names, last_name: e.target.value })}
              autoComplete="family-name"
              maxLength={150}
            />
          </Field>
        </div>
        <Button type="submit" className="w-full" icon={Save} loading={saving} disabled={!dirty}>
          Enregistrer
        </Button>
      </form>

      <SectionTitle>Navigation</SectionTitle>
      <NavigationAppChoice />

      <SectionTitle>Adresse email</SectionTitle>
      <EmailChange current={user.email} />

      <TelegramLink />

      <div className="pt-4">
        <DeleteAccount />
      </div>
    </Sheet>
  );
}

/** The app opened when tapping an address during a tour; saved as soon as it is picked. */
function NavigationAppChoice() {
  const { user, updateProfile } = useAuth();
  const [value, setValue] = useState<NavigationApp>(user?.navigation_app ?? "google");
  const [error, setError] = useState<string | null>(null);

  const pick = async (app: NavigationApp) => {
    const previous = value;
    setValue(app);
    setError(null);
    try {
      await updateProfile({ navigation_app: app });
    } catch (err) {
      setValue(previous);
      setError(errorMessage(err));
    }
  };

  return (
    <div className="space-y-2">
      {error && <Alert>{error}</Alert>}
      <Segmented options={NAVIGATION_APPS} value={value} onChange={pick} />
      <p className="text-xs text-zinc-500">Ouverte quand tu touches l'adresse pendant une tournée, pour t'y guider à pied.</p>
    </div>
  );
}

function EmailChange({ current }: { current: string }) {
  const { setUser } = useAuth();
  const [editing, setEditing] = useState(false);
  const [email, setEmail] = useState("");
  const [sentTo, setSentTo] = useState<{ email: string; minutes: number } | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState<"send" | "verify" | null>(null);
  const codeInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (sentTo) codeInput.current?.focus();
  }, [sentTo]);

  const reset = () => {
    setEditing(false);
    setSentTo(null);
    setEmail("");
    setCode("");
    setError(null);
  };

  const send = async (e?: FormEvent) => {
    e?.preventDefault();
    setBusy("send");
    setError(null);
    try {
      const r = await api<LoginRequestResponse>("/auth/me/email/", { method: "POST", body: { email } });
      setSentTo({ email: r.email, minutes: r.expires_in_minutes });
      setCode("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const verify = async (value: string) => {
    setBusy("verify");
    setError(null);
    try {
      const me = await api<User>("/auth/me/email/code/", { method: "POST", body: { code: value } });
      setUser(me);
      setDone(me.email);
      reset();
    } catch (err) {
      setError(errorMessage(err));
      setCode("");
      codeInput.current?.focus();
    } finally {
      setBusy(null);
    }
  };

  const onCodeChange = (raw: string) => {
    const digits = raw.replace(/\D/g, "").slice(0, 6);
    setCode(digits);
    if (digits.length === 6 && busy === null) verify(digits);
  };

  if (sentTo)
    return (
      <Card className="space-y-3 p-3.5">
        <div className="flex gap-2.5 text-sm text-zinc-700">
          <MailCheck className="mt-0.5 size-5 shrink-0 text-sky-600" />
          <p>
            Code envoyé à <strong className="font-semibold text-zinc-900">{sentTo.email}</strong>. Entre-le ici, ou clique sur le lien
            de l'email. Valable {sentTo.minutes} minutes.
          </p>
        </div>
        {error && <Alert>{error}</Alert>}
        <input
          ref={codeInput}
          className={`${inputClass} h-14 text-center font-mono text-2xl font-semibold tracking-[0.45em] placeholder:text-zinc-300`}
          value={code}
          onChange={(e) => onCodeChange(e.target.value)}
          inputMode="numeric"
          autoComplete="one-time-code"
          placeholder="000000"
          aria-label="Code de confirmation"
        />
        <Button className="w-full" icon={Check} loading={busy === "verify"} disabled={code.length !== 6} onClick={() => verify(code)}>
          Confirmer la nouvelle adresse
        </Button>
        <div className="grid grid-cols-2 gap-2">
          <Button variant="ghost" size="sm" icon={ArrowLeft} onClick={() => (setSentTo(null), setError(null))}>
            Autre adresse
          </Button>
          <Button variant="ghost" size="sm" icon={RotateCcw} loading={busy === "send"} onClick={() => send()}>
            Renvoyer le code
          </Button>
        </div>
        <Button variant="ghost" size="sm" className="w-full" onClick={reset}>
          Annuler le changement
        </Button>
      </Card>
    );

  if (editing)
    return (
      <Card className="p-3.5">
        <form onSubmit={send} className="space-y-3">
          {error && <Alert>{error}</Alert>}
          <Field label="Nouvelle adresse email" hint="Elle ne sera utilisée qu'après confirmation avec le code reçu dessus.">
            <input
              className={inputClass}
              type="email"
              inputMode="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
            />
          </Field>
          <div className="grid grid-cols-2 gap-2">
            <Button type="button" variant="secondary" size="sm" onClick={reset}>
              Annuler
            </Button>
            <Button type="submit" size="sm" icon={Mail} loading={busy === "send"}>
              Envoyer un code
            </Button>
          </div>
        </form>
      </Card>
    );

  return (
    <div className="space-y-3">
      {done && <Alert kind="success">Adresse confirmée : tu te connecteras désormais avec {done}.</Alert>}
      <Card className="flex items-center gap-3 p-3.5">
        <Mail className="size-5 shrink-0 text-zinc-400" />
        <span className="min-w-0 flex-1 truncate text-[15px] font-medium">{current}</span>
        <Button variant="secondary" size="sm" icon={Pencil} onClick={() => (setEditing(true), setDone(null))}>
          Modifier
        </Button>
      </Card>
    </div>
  );
}

/** Erases the personal data; tours and doors knocked stay in the organization's statistics. */
type TelegramAuthData = Record<string, string | number>;

declare global {
  interface Window {
    Telegram?: { Login?: { auth: (options: { bot_id: number; request_access?: boolean }, callback: (data: TelegramAuthData | false) => void) => void } };
  }
}

const TELEGRAM_SCRIPT = "https://telegram.org/js/telegram-widget.js?22";

/** Loads Telegram's login script once (ahead of the click, so that its popup is not blocked). */
function loadTelegramScript(): Promise<void> {
  if (window.Telegram?.Login) return Promise.resolve();
  return new Promise((resolve, reject) => {
    let script = document.querySelector<HTMLScriptElement>(`script[src="${TELEGRAM_SCRIPT}"]`);
    if (!script) {
      script = document.createElement("script");
      script.src = TELEGRAM_SCRIPT;
      script.async = true;
      document.head.appendChild(script);
    }
    script.addEventListener("load", () => resolve());
    script.addEventListener("error", () => reject(new Error("Impossible de charger Telegram.")));
  });
}

/**
 * Link the Telegram account used with the old bot: Telegram's popup confirms the account, the server checks its
 * signature and gives this user the doors knocked with the bot. Once linked, the button is gone.
 */
function TelegramLink() {
  const { user, setUser } = useAuth();
  const [botId, setBotId] = useState<number | null | undefined>(undefined);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [linkedVisits, setLinkedVisits] = useState<number | null>(null);
  const linked = user?.telegram_id != null;

  useEffect(() => {
    if (linked) return;
    api<{ telegram_bot_id: number | null }>("/config/")
      .then((config) => setBotId(config.telegram_bot_id))
      .catch(() => setBotId(null));
  }, [linked]);

  useEffect(() => {
    if (!botId || linked) return;
    loadTelegramScript()
      .then(() => setReady(true))
      .catch((e) => setError(errorMessage(e)));
  }, [botId, linked]);

  if (!user || (!linked && !botId)) return null; // not configured on this site

  const start = () => {
    if (!botId || !window.Telegram?.Login) return;
    setError(null);
    setBusy(true);
    window.Telegram.Login.auth({ bot_id: botId }, async (data) => {
      if (!data) return setBusy(false); // popup closed
      try {
        const me = await api<User & { linked_visits: number }>("/auth/me/telegram/", { method: "POST", body: data });
        setLinkedVisits(me.linked_visits);
        setUser(me);
      } catch (err) {
        setError(errorMessage(err));
      } finally {
        setBusy(false);
      }
    });
  };

  return (
    <>
      <SectionTitle>Telegram</SectionTitle>
      {linked ? (
        <Card className="flex items-center gap-3 p-3.5">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-sky-50 text-sky-600">
            <Check className="size-[18px]" strokeWidth={3} />
          </span>
          <div className="min-w-0">
            <p className="font-semibold tracking-tight">Compte Telegram lié</p>
            <p className="text-sm text-zinc-500">
              {linkedVisits != null
                ? `${linkedVisits.toLocaleString("fr")} porte${linkedVisits > 1 ? "s" : ""} faite${linkedVisits > 1 ? "s" : ""} avec le bot ajoutée${linkedVisits > 1 ? "s" : ""} à ton historique.`
                : "Ce que tu as fait avec le bot Telegram est dans ton historique."}
            </p>
          </div>
        </Card>
      ) : (
        <Card className="space-y-3 p-3.5">
          <p className="text-sm text-zinc-600">
            Tu faisais du porte-à-porte avec le bot Telegram ? Lie ton compte Telegram pour retrouver ces portes dans ton
            historique et tes statistiques.
          </p>
          {error && <Alert>{error}</Alert>}
          <Button className="w-full" variant="secondary" icon={Link2} loading={busy} disabled={!ready} onClick={start}>
            Lier mon compte Telegram
          </Button>
        </Card>
      )}
    </>
  );
}

function DeleteAccount() {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      await api("/auth/me/", { method: "DELETE" });
      await logout();
      navigate("/login", { replace: true });
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  };

  if (!confirm)
    return (
      <button
        type="button"
        onClick={() => setConfirm(true)}
        className="flex w-full items-center justify-center gap-2 rounded-xl py-2.5 text-sm font-semibold text-red-600 active:bg-red-50"
      >
        <Trash2 className="size-4" /> Supprimer mon compte
      </button>
    );

  return (
    <div className="space-y-3 rounded-2xl bg-red-50 p-3.5 ring-1 ring-red-200/70">
      <p className="flex items-center gap-2 font-semibold text-red-900">
        <Trash2 className="size-[18px] text-red-600" /> Supprimer mon compte ?
      </p>
      <p className="text-sm leading-relaxed text-red-900/80">
        Ton nom, ton prénom et ton adresse email seront effacés et tu ne pourras plus te connecter. Les tournées et les portes que
        tu as frappées restent dans les statistiques de l'organisation, sans ton nom. Cette action est définitive.
      </p>
      {error && <Alert>{error}</Alert>}
      <div className="grid grid-cols-2 gap-2">
        <Button variant="secondary" size="sm" onClick={() => setConfirm(false)} disabled={busy}>
          Annuler
        </Button>
        <Button variant="destructive" size="sm" icon={Trash2} loading={busy} onClick={remove}>
          Supprimer
        </Button>
      </div>
    </div>
  );
}
