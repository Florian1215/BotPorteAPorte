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
};

export const MapUIContext = createContext<MapUI | null>(null);

export function useMapUI(): MapUI {
  const ctx = useContext(MapUIContext);
  if (!ctx) throw new Error("useMapUI must be used inside <MapShell>");
  return ctx;
}
