import { CircleAlert, CircleCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, errorMessage } from "../api/client";
import type { User } from "../api/types";
import { Loading } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import AuthShell from "./AuthShell";

/** Landing page of the link sent to a new email address: confirms the change (from any device). */
export default function VerifyEmail() {
  const [params] = useSearchParams();
  const { user, setUser } = useAuth();
  const [result, setResult] = useState<{ ok: true; email: string } | { ok: false; error: string } | null>(null);
  const started = useRef(false); // single-use token: never post it twice (StrictMode)

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const token = params.get("token");
    if (!token) return setResult({ ok: false, error: "Lien de confirmation incomplet." });
    api<User>("/auth/me/email/link/", { method: "POST", body: { token } })
      .then((me) => {
        if (user && user.id === me.id) setUser(me);
        setResult({ ok: true, email: me.email });
      })
      .catch((e) => setResult({ ok: false, error: errorMessage(e) }));
  }, [params, user, setUser]);

  const back = user ? "/account" : "/login";

  return (
    <AuthShell title={!result ? "Confirmation…" : result.ok ? "Adresse confirmée" : "Lien invalide"}>
      {!result ? (
        <Loading />
      ) : (
        <div className="space-y-4">
          <div
            className={`flex gap-2.5 rounded-2xl px-3.5 py-3 text-sm ring-1 ${
              result.ok ? "bg-emerald-50 text-emerald-950 ring-emerald-200/70" : "bg-red-50 text-red-900 ring-red-200/70"
            }`}
          >
            {result.ok ? <CircleCheck className="mt-px size-[18px] shrink-0 text-emerald-600" /> : <CircleAlert className="mt-px size-[18px] shrink-0 text-red-600" />}
            <span>{result.ok ? `Tu te connecteras désormais avec ${result.email}.` : result.error}</span>
          </div>
          <Link to={back} replace className="flex min-h-12 items-center justify-center rounded-2xl bg-brand-600 font-semibold text-white active:bg-brand-700">
            {user ? "Retour à mon compte" : "Me connecter"}
          </Link>
        </div>
      )}
    </AuthShell>
  );
}
