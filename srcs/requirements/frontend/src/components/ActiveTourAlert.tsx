import { CircleStop, Play } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, api, errorMessage } from "../api/client";
import type { Tour } from "../api/types";
import { Alert, Button } from "./ui";

/** Id of the tour in progress when preparing a new one was refused for that reason, else null. */
export function activeTourId(err: unknown): number | null {
  if (!(err instanceof ApiError) || !err.data || typeof err.data !== "object") return null;
  const data = err.data as { code?: string; tour_id?: number };
  return data.code === "active_tour" && typeof data.tour_id === "number" ? data.tour_id : null;
}

/**
 * "You already have a tour in progress": resume it, or stop it (cancelled if no door was knocked,
 * otherwise finished and recorded — same rule as the stop button of a tour), then `onStopped`.
 */
export default function ActiveTourAlert({ tourId, onStopped }: { tourId: number; onStopped: () => void }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const stop = async () => {
    setBusy(true);
    setError(null);
    try {
      const tour = await api<Tour>(`/tours/${tourId}/`);
      if (tour.stops.some((s) => s.result)) await api(`/tours/${tourId}/finish/`, { method: "POST" });
      else await api(`/tours/${tourId}/`, { method: "DELETE" });
      onStopped();
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  };

  return (
    <Alert kind="warning">
      <p>Tu as déjà une tournée en cours. Continue-la, ou arrête-la pour en préparer une nouvelle.</p>
      {error && <p className="mt-1 font-semibold">{error}</p>}
      <div className="mt-2.5 grid grid-cols-2 gap-2">
        <Button size="sm" variant="secondary" icon={Play} onClick={() => navigate(`/tours/${tourId}`)} disabled={busy}>
          Continuer
        </Button>
        <Button size="sm" variant="danger" icon={CircleStop} onClick={stop} loading={busy}>
          Arrêter
        </Button>
      </div>
    </Alert>
  );
}
