import { useSyncExternalStore } from "react";

/** Large screens (Tailwind's `lg`): side panel instead of the mobile bottom sheet. */
export const DESKTOP_QUERY = "(min-width: 1024px)";

export function isDesktop(): boolean {
  return typeof window !== "undefined" && window.matchMedia(DESKTOP_QUERY).matches;
}

function subscribe(onChange: () => void) {
  const mql = window.matchMedia(DESKTOP_QUERY);
  mql.addEventListener("change", onChange);
  return () => mql.removeEventListener("change", onChange);
}

export function useIsDesktop(): boolean {
  return useSyncExternalStore(subscribe, isDesktop, () => false);
}
