import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { api, errorMessage } from "../api/client";
import type { Scope } from "../api/types";
import { Alert, Button, Field, inputClass } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import AuthShell from "./AuthShell";

export default function Register() {
  const { register } = useAuth();
  const [scopes, setScopes] = useState<Scope[]>([]);
  const [form, setForm] = useState({ username: "", first_name: "", password: "", scope: "" });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api<Scope[]>("/auth/scopes/").then(setScopes).catch(() => setScopes([]));
  }, []);

  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await register({ ...form, scope: form.scope || null });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell title="Créer un compte">
      <form onSubmit={submit} className="space-y-4">
        {error && <Alert>{error}</Alert>}
        <Field label="Prénom">
          <input className={inputClass} value={form.first_name} onChange={set("first_name")} autoComplete="given-name" required />
        </Field>
        <Field label="Nom d'utilisateur">
          <input className={inputClass} value={form.username} onChange={set("username")} autoComplete="username" required />
        </Field>
        <Field label="Mot de passe" hint="8 caractères minimum.">
          <input className={inputClass} type="password" value={form.password} onChange={set("password")} autoComplete="new-password" required />
        </Field>
        {scopes.length > 0 && (
          <Field label="Ta ville / ton groupe d'action">
            <select className={inputClass} value={form.scope} onChange={set("scope")}>
              <option value="">Je ne sais pas</option>
              {scopes.map((s) => (
                <option key={s.code} value={s.code}>
                  {s.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        <Button type="submit" className="w-full" loading={loading}>
          Créer mon compte
        </Button>
        <p className="text-center text-sm text-slate-600">
          Déjà inscrit·e ?{" "}
          <Link to="/login" className="font-semibold text-brand-600">
            Se connecter
          </Link>
        </p>
      </form>
    </AuthShell>
  );
}
