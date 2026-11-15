import { CircleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { errorMessage } from "../api/client";
import { Loading } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import AuthShell from "./AuthShell";

/** Landing page of the link sent by email: logs in with its one-time token. */
export default function VerifyLink() {
  const [params] = useSearchParams();
  const { verifyLink } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false); // the token is single use: never post it twice (StrictMode)

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const token = params.get("token");
    if (!token) {
      setError("Lien de connexion incomplet.");
      return;
    }
    verifyLink(token)
      .then(() => navigate("/", { replace: true }))
      .catch((e) => setError(errorMessage(e)));
  }, [params, verifyLink, navigate]);

  return (
    <AuthShell title={error ? "Lien invalide" : "Connexion…"}>
      {error ? (
        <div className="space-y-4">
          <div className="flex gap-2.5 rounded-2xl bg-red-50 px-3.5 py-3 text-sm text-red-900 ring-1 ring-red-200/70">
            <CircleAlert className="mt-px size-[18px] shrink-0 text-red-600" />
            {error}
          </div>
          <Link
            to="/login"
            replace
            className="flex min-h-12 items-center justify-center rounded-2xl bg-brand-600 font-semibold text-white active:bg-brand-700"
          >
            Recevoir un nouveau code
          </Link>
        </div>
      ) : (
        <Loading />
      )}
    </AuthShell>
  );
}
