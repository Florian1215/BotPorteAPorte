import type { GeoState } from "../hooks/useGeolocation";
import { Alert } from "./ui";

export default function LocationStatus({ geo, onRetry }: { geo: GeoState; onRetry: () => void }) {
  if (geo.status === "pending") return <p className="text-sm text-slate-500">📍 Recherche de ta position…</p>;
  if (geo.error)
    return (
      <Alert kind="warning">
        {geo.error}{" "}
        <button className="font-semibold underline" onClick={onRetry}>
          Réessayer
        </button>
      </Alert>
    );
  return null;
}
