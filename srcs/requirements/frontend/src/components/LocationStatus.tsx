import { LoaderCircle } from "lucide-react";

import type { GeoState } from "../hooks/useGeolocation";
import { Alert } from "./ui";

export default function LocationStatus({ geo, onRetry }: { geo: GeoState; onRetry: () => void }) {
  if (geo.status === "pending")
    return (
      <p className="flex items-center gap-2 text-sm text-zinc-500">
        <LoaderCircle className="size-4 animate-spin text-sky-600" /> Recherche de ta position…
      </p>
    );
  if (geo.error)
    return (
      <Alert kind="warning">
        {geo.error}{" "}
        <button className="font-semibold underline underline-offset-2" onClick={onRetry}>
          Réessayer
        </button>
      </Alert>
    );
  return null;
}
