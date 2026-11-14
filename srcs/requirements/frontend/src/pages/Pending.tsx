import { useState } from "react";

import { Alert, Button } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import AuthShell from "./AuthShell";

export default function Pending() {
  const { user, refresh, logout } = useAuth();
  const [checking, setChecking] = useState(false);
  if (!user) return null;

  return (
    <AuthShell title={`Bienvenue ${user.first_name || user.username} 👋`}>
      <div className="space-y-4 text-sm">
        <Alert kind="info">
          {user.is_approved && !user.scope
            ? "Ton compte est validé mais aucun périmètre (liste d'adresses) ne t'a encore été attribué."
            : "Ton compte n'est pas encore autorisé à faire du porte-à-porte."}{" "}
          Contacte ta/ton responsable porte-à-porte pour être ajouté·e, en lui donnant ton nom d'utilisateur :
          <strong className="mt-2 block text-base">{user.username}</strong>
        </Alert>
        <Button
          className="w-full"
          loading={checking}
          onClick={() => {
            setChecking(true);
            refresh().finally(() => setChecking(false));
          }}
        >
          J'ai été ajouté·e, vérifier
        </Button>
        <Button variant="ghost" className="w-full" onClick={() => logout()}>
          Se déconnecter
        </Button>
      </div>
    </AuthShell>
  );
}
