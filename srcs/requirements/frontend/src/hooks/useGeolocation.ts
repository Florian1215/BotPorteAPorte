import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

import type { LatLon } from "../api/types";

export type GeoState = {
  position: (LatLon & { accuracy: number }) | null;
  error: string | null;
  status: "idle" | "pending" | "ok" | "error";
};

export type Geo = GeoState & { retry: () => void; here: LatLon | null };

const ERRORS: Record<number, string> = {
  1: "Localisation refusée. Autorise-la dans les réglages du navigateur, ou touche la carte pour placer le point.",
  2: "Position indisponible. Touche la carte pour placer le point.",
  3: "La localisation a pris trop de temps. Réessaie ou touche la carte.",
};

const LAST_POSITION_KEY = "canvassing:last-position";

/** Last known position, used to open the map where the militant was last time. */
export function lastKnownPosition(): [number, number] | null {
  try {
    const raw = localStorage.getItem(LAST_POSITION_KEY);
    if (!raw) return null;
    const [lat, lon] = JSON.parse(raw);
    return typeof lat === "number" && typeof lon === "number" ? [lat, lon] : null;
  } catch {
    return null;
  }
}

function rememberPosition(lat: number, lon: number) {
  try {
    localStorage.setItem(LAST_POSITION_KEY, JSON.stringify([lat, lon]));
  } catch {
    /* storage unavailable: not a problem */
  }
}

/** Follows the device position (asks for permission on mount). */
export function useGeolocation(watch = true): Geo {
  const [state, setState] = useState<GeoState>({ position: null, error: null, status: "idle" });
  const watchId = useRef<number | null>(null);

  const start = useCallback(() => {
    if (!("geolocation" in navigator)) {
      setState({ position: null, error: "Ton navigateur ne permet pas la géolocalisation.", status: "error" });
      return;
    }
    if (!window.isSecureContext) {
      setState({
        position: null,
        error: "La géolocalisation nécessite HTTPS. Touche la carte pour placer le point.",
        status: "error",
      });
      return;
    }
    setState((s) => ({ ...s, status: s.position ? "ok" : "pending", error: null }));
    const onOk = (p: GeolocationPosition) => {
      rememberPosition(p.coords.latitude, p.coords.longitude);
      setState({
        position: { lat: p.coords.latitude, lon: p.coords.longitude, accuracy: p.coords.accuracy },
        error: null,
        status: "ok",
      });
    };
    const onErr = (e: GeolocationPositionError) =>
      setState((s) => ({ ...s, error: ERRORS[e.code] ?? e.message, status: s.position ? "ok" : "error" }));
    const options = { enableHighAccuracy: true, timeout: 15000, maximumAge: 10000 };
    if (watchId.current !== null) navigator.geolocation.clearWatch(watchId.current);
    if (watch) watchId.current = navigator.geolocation.watchPosition(onOk, onErr, options);
    else navigator.geolocation.getCurrentPosition(onOk, onErr, options);
  }, [watch]);

  useEffect(() => {
    start();
    return () => {
      if (watchId.current !== null) navigator.geolocation.clearWatch(watchId.current);
    };
  }, [start]);

  const lat = state.position?.lat;
  const lon = state.position?.lon;
  const here = lat != null && lon != null ? { lat, lon } : null;
  return { ...state, here, retry: start };
}

/** One shared position watcher for the whole signed-in app. */
export const GeoContext = createContext<Geo | null>(null);

export function useGeo(): Geo {
  const ctx = useContext(GeoContext);
  if (!ctx) throw new Error("useGeo must be used inside <GeoContext.Provider>");
  return ctx;
}
