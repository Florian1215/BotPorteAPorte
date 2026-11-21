import type L from "leaflet";
import { createContext, useContext, type RefObject } from "react";

/**
 * The app renders a single, always-mounted map in the background.
 * Pages draw on it through <MapLayers> and dock their UI in a <Sheet>,
 * whose height is shared so that fitting / flying keeps targets visible above it.
 */
export type MapUI = {
  map: L.Map | null;
  sheetHeight: RefObject<number>;
  /** Large screens: width covered on the left by the side menu + panel (the sheet is then not at the bottom). */
  sheetLeft: RefObject<number>;
  /** Point the map was last centered on (fly to), kept centered above the sheet until the user moves the map. */
  focus: RefObject<{ point: [number, number]; zoom: number } | null>;
  /** Our own animations are running (their zoom must not be mistaken for the user's). */
  flying: RefObject<boolean>;
  /** Called by the sheet when its visible height changes. */
  sheetChanged: () => void;
};

export const MapUIContext = createContext<MapUI | null>(null);

export function useMapUI(): MapUI {
  const ctx = useContext(MapUIContext);
  if (!ctx) throw new Error("useMapUI must be used inside <MapShell>");
  return ctx;
}
