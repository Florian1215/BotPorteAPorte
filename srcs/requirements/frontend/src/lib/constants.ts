import { Ban, DoorClosed, HeartHandshake, MapPinOff, Meh, ThumbsUp, type LucideIcon } from "lucide-react";

import type { AbsentDetail, NavigationApp, ResultValue, Role, ScoreCriterionKey } from "../api/types";

export const ROLES: { value: Role; label: string; description: string }[] = [
  { value: "militant", label: "Militant·e", description: "Fait du porte-à-porte dans son organisation" },
  { value: "experienced", label: "Militant·e aguerri·e", description: "Valide aussi les nouvelles inscriptions" },
  { value: "manager", label: "Responsable d'organisation", description: "Gère les membres, le nom et le logo de l'organisation" },
  { value: "admin", label: "Administrateur·rice du site", description: "Gère toutes les organisations" },
];

export const ROLE_LABEL = Object.fromEntries(ROLES.map((r) => [r.value, r.label])) as Record<Role, string>;

/** Organization picked on the last login, pre-selected next time. */
export const LAST_ORGANIZATION_KEY = "canvassing:last-organization";

/** Max deviation from the ideal route, free tour (km). Same options as the bot. */
export const RADIUS_OPTIONS_KM = [0.1, 0.2, 0.5, 1, 2, 5, 10];
/** Search radius for nearby addresses (km). Same options as the bot. */
export const NEARBY_RADIUS_OPTIONS_KM = [0.2, 1, 2, 5, 10];

export const DEFAULT_CENTER: [number, number] = [52.52, 13.405];

export type ResultDef = {
  value: ResultValue;
  label: string;
  short: string;
  icon: LucideIcon;
  /** Marker / dot color on the map. */
  color: string;
  /** Solid style of the button once this feedback is the one selected. */
  solid: string;
  disc: string;
};

export const RESULTS: ResultDef[] = [
  {
    value: "commitment_to_vote",
    label: "Promesse de vote",
    short: "Promesse de vote",
    icon: HeartHandshake,
    color: "#059669",
    solid: "bg-emerald-600 text-white ring-emerald-600",
    disc: "bg-emerald-600",
  },
  {
    value: "good_conversation",
    label: "Bonne conversation",
    short: "Bonne conversation",
    icon: ThumbsUp,
    color: "#0d9488",
    solid: "bg-teal-600 text-white ring-teal-600",
    disc: "bg-teal-600",
  },
  {
    value: "not_interested",
    label: "Personne peu intéressée",
    short: "Peu intéressée",
    icon: Meh,
    color: "#7c3aed",
    solid: "bg-violet-600 text-white ring-violet-600",
    disc: "bg-violet-500",
  },
  {
    value: "do_not_contact",
    label: "Ne plus déranger",
    short: "Ne plus déranger",
    icon: Ban,
    color: "#64748b",
    solid: "bg-zinc-600 text-white ring-zinc-600",
    disc: "bg-zinc-500",
  },
  {
    value: "address_to_retry",
    label: "Absente",
    short: "Absente",
    icon: DoorClosed,
    color: "#d97706",
    solid: "bg-amber-500 text-white ring-amber-500",
    disc: "bg-amber-500",
  },
  {
    value: "address_failure",
    label: "Adresse introuvable",
    short: "Adresse introuvable",
    icon: MapPinOff,
    color: "#dc2626",
    solid: "bg-red-600 text-white ring-red-600",
    disc: "bg-red-600",
  },
];

/** The two halves the "absent" button splits into. */
export const ABSENT_DETAILS: { value: AbsentDetail; label: string; past: string }[] = [
  { value: "leaflet", label: "Tract boîté", past: "a boîté un tract" },
  { value: "mailbox_inaccessible", label: "Boîte aux lettres inaccessible", past: "la boîte aux lettres était inaccessible" },
];

export const ABSENT_DETAIL_BY_VALUE = Object.fromEntries(ABSENT_DETAILS.map((d) => [d.value, d])) as Record<
  AbsentDetail,
  (typeof ABSENT_DETAILS)[number]
>;

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

export const NAVIGATION_APPS: { value: NavigationApp; label: string }[] = [
  { value: "google", label: "Google Maps" },
  { value: "apple", label: "Apple Plans" },
];

/** Walking directions to a door, in the militant's navigation app. */
export function navigationUrl(lat: number, lon: number, app: NavigationApp = "google"): string {
  if (app === "apple") return `https://maps.apple.com/?daddr=${lat},${lon}&dirflg=w`;
  return `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}&travelmode=walking`;
}

/** Score of a polling district (0–100) → map colour: one hue, light (low) to dark (high), 5 classes. */
export const SCORE_CLASSES: { min: number; color: string; label: string }[] = [
  { min: 80, color: "#7f1d1d", label: "80–100" },
  { min: 60, color: "#b91c1c", label: "60–80" },
  { min: 40, color: "#ef4444", label: "40–60" },
  { min: 20, color: "#fca5a5", label: "20–40" },
  { min: 0, color: "#fee2e2", label: "0–20" },
];

export function scoreColor(score: number): string {
  return (SCORE_CLASSES.find((c) => score >= c.min) ?? SCORE_CLASSES[SCORE_CLASSES.length - 1]).color;
}

/** Colour of a district by its share of doors done: light at 0 %, plain red at 50 %, almost black at 100 %. */
export const DONE_STOPS: { pct: number; color: string }[] = [
  { pct: 0, color: "#fee2e2" },
  { pct: 50, color: "#ef4444" },
  { pct: 100, color: "#2a0505" },
];

export function doneColor(donePct: number): string {
  const v = Math.max(0, Math.min(100, donePct));
  const i = v <= DONE_STOPS[1].pct ? 0 : 1;
  const [a, b] = [DONE_STOPS[i], DONE_STOPS[i + 1]];
  const t = (v - a.pct) / (b.pct - a.pct);
  const channel = (hex: string, k: number) => parseInt(hex.slice(1 + 2 * k, 3 + 2 * k), 16);
  const mix = [0, 1, 2].map((k) => Math.round(channel(a.color, k) + (channel(b.color, k) - channel(a.color, k)) * t));
  return `rgb(${mix.join(",")})`;
}

const pct = (v: number) => `${(v * 100).toLocaleString("fr", { maximumFractionDigits: 1 })} %`;

/** How the raw value of each score criterion is shown. */
/** A social indicator is a share (0–1), or a figure such as a median income. */
export const formatSocial = (v: number) => (Math.abs(v) <= 1 ? pct(v) : v.toLocaleString("fr", { maximumFractionDigits: 1 }));

export const CRITERION_FORMAT: Record<ScoreCriterionKey, (v: number) => string> = {
  party: pct,
  abstention: pct,
  age: pct,
  density: (v) => `${Math.round(v).toLocaleString("fr")} Français·es/km²`,
  social: formatSocial,
};

export const CRITERION_HELP: Record<ScoreCriterionKey, string> = {
  party: "Part des voix du parti le plus proche de LFI dans le pays, parmi les suffrages exprimés.",
  abstention: "Inscrit·es qui n'ont pas voté : des électeur·rices à mobiliser.",
  age: "Vote LFI attendu d'après l'âge des Français·es de la liste (18–24 ans : 41 %, 25–34 : 30 %, 35–49 : 36 %, 50–59 : 28 %, 60–69 : 24 %, 70 et plus : 19 %).",
  density: "Français·es de la liste électorale par km² : plus de portes à l'heure.",
  social: "Indicateur social de la zone (bas revenus, pauvreté, revenu médian…) : les zones les plus pauvres d'abord.",
};
