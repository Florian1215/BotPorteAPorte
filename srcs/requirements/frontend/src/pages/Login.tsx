import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { errorMessage } from "../api/client";
import { Alert, Button, Field, inputClass } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import AuthShell from "./AuthShell";

export default function Login() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await login(username, password);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell title="Connexion">
      <form onSubmit={submit} className="space-y-4">
        {error && <Alert>{error}</Alert>}
        <Field label="Nom d'utilisateur">
          <input className={inputClass} value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
        </Field>
        <Field label="Mot de passe">
          <input className={inputClass} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </Field>
        <Button type="submit" className="w-full" loading={loading}>
          Se connecter
        </Button>
        <p className="text-center text-sm text-slate-600">
          Pas encore de compte ?{" "}
          <Link to="/register" className="font-semibold text-brand-600">
            S'inscrire
          </Link>
        </p>
      </form>
    </AuthShell>
  );
}
