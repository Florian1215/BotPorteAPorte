import type { ResultValue } from "../api/types";

/** Max deviation from the ideal route, free tour (km). Same options as the bot. */
export const RADIUS_OPTIONS_KM = [0.1, 0.2, 0.5, 1, 2, 5, 10];
/** Search radius for nearby addresses (km). Same options as the bot. */
export const NEARBY_RADIUS_OPTIONS_KM = [1, 2, 5, 10, 25, 50];

export const DEFAULT_CENTER: [number, number] = [52.52, 13.405];

export type ResultDef = { value: ResultValue; label: string; short: string; emoji: string; color: string; className: string };

export const RESULTS: ResultDef[] = [
  {
    value: "commitment_to_vote",
    label: "Promesse de vote",
    short: "Promesse de vote",
    emoji: "🤝",
    color: "#16a34a",
    className: "bg-green-600 active:bg-green-700 text-white",
  },
  {
    value: "good_conversation",
    label: "Bonne conversation",
    short: "Bonne conversation",
    emoji: "👍",
    color: "#0d9488",
    className: "bg-teal-600 active:bg-teal-700 text-white",
  },
  {
    value: "do_not_contact",
    label: "Conversation stérile / Ne plus déranger",
    short: "Stérile / Ne plus déranger",
    emoji: "😐",
    color: "#64748b",
    className: "bg-slate-500 active:bg-slate-600 text-white",
  },
  {
    value: "address_to_retry",
    label: "Personne absente / Repasser",
    short: "Absent·e / Repasser",
    emoji: "🚪",
    color: "#d97706",
    className: "bg-amber-500 active:bg-amber-600 text-white",
  },
  {
    value: "address_failure",
    label: "Adresse introuvable",
    short: "Adresse introuvable",
    emoji: "⛔",
    color: "#dc2626",
    className: "bg-red-600 active:bg-red-700 text-white",
  },
];

export const RESULT_BY_VALUE = Object.fromEntries(RESULTS.map((r) => [r.value, r])) as Record<ResultValue, ResultDef>;

export function formatKm(km: number): string {
  return km < 1 ? `${Math.round(km * 1000)} m` : `${km} km`;
}

export function formatDistance(meters: number | null): string {
  if (meters == null) return "—";
  return meters < 1000 ? `${Math.round(meters)} m` : `${(meters / 1000).toFixed(1)} km`;
}

export function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  const minutes = Math.round(seconds / 60);
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")}`;
}

export function navigationUrl(lat: number, lon: number): string {
  return `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}&travelmode=walking`;
}
