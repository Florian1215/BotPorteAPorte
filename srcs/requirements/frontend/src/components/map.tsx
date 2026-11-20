import { LeafletContext, createLeafletContext } from "@react-leaflet/core";
import L from "leaflet";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AttributionControl, Circle, CircleMarker, MapContainer, Marker, TileLayer, useMap, useMapEvents } from "react-leaflet";

import { api } from "../api/client";
import type { LatLon } from "../api/types";
import { MapUIContext, useMapUI } from "../context/MapContext";
import { lastKnownPosition } from "../hooks/useGeolocation";
import { DEFAULT_CENTER } from "../lib/constants";

/** Height reserved for the floating top bar. */
const TOP_BAR_PX = 72;

type TileConfig = { tile_url: string; attribution: string; provider?: string; fallback?: TileConfig | null };

/** OpenStreetMap's standard tiles (no key): used if /api/config/ cannot be reached, or when CARTO tiles fail. */
const OSM_TILES: TileConfig = {
  tile_url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  provider: "osm",
};

/** Tiles failing before this many load fine: CARTO is down (or refuses us), switch to the fallback. */
const TILE_ERRORS_BEFORE_FALLBACK = 6;

/**
 * Tile URL comes from the backend at runtime (CARTO by default, OpenStreetMap when the server finds CARTO not
 * working), so the key lives only in srcs/.env. If CARTO tiles still fail in the browser, `onTileError` switches
 * to the fallback.
 */
function useTileConfig() {
  const [tiles, setTiles] = useState<TileConfig | null>(null);
  const stats = useRef({ errors: 0, loads: 0 });
  useEffect(() => {
    api<{ map: TileConfig }>("/config/")
      .then((config) => setTiles(config.map))
      .catch(() => setTiles(OSM_TILES));
  }, []);
  const onTileLoad = useCallback(() => {
    stats.current.loads += 1;
  }, []);
  const onTileError = useCallback(() => {
    const s = stats.current;
    s.errors += 1;
    if (s.errors >= TILE_ERRORS_BEFORE_FALLBACK && s.errors > s.loads)
      setTiles((current) => {
        if (!current?.fallback) return current;
        console.warn("Map tiles failing, switching to OpenStreetMap");
        return current.fallback;
      });
  }, []);
  return { tiles, onTileLoad, onTileError };
}

/** Full-screen map, always mounted behind the whole app. */
export function MapShell({ children }: { children: ReactNode }) {
  const [map, setMap] = useState<L.Map | null>(null);
  const { tiles, onTileLoad, onTileError } = useTileConfig();
  const sheetHeight = useRef(0);
  const focus = useRef<{ point: [number, number]; zoom: number } | null>(null);
  const flying = useRef(false);
  const recenterTimer = useRef<number | undefined>(undefined);
  const initial = useMemo(() => lastKnownPosition(), []);

  // The sheet grew or shrank (content loaded, collapsed…): keep the focused point in the middle of the free space.
  // Debounced, so it runs once the sheet has settled (height transition, several loads in a row).
  const sheetChanged = useCallback(() => {
    if (!map) return;
    window.clearTimeout(recenterTimer.current);
    recenterTimer.current = window.setTimeout(() => {
      const f = focus.current;
      if (!f) return;
      const target = visibleCenter(map, f.point, f.zoom, sheetHeight.current ?? 0);
      const shift = map.project(target, f.zoom).subtract(map.project(map.getCenter(), f.zoom));
      if (map.getZoom() === f.zoom && Math.abs(shift.x) < 2 && Math.abs(shift.y) < 2) return;
      flying.current = true;
      map.flyTo(target, f.zoom, { duration: 0.35 });
    }, 200);
  }, [map]);

  // The user moving or zooming the map themselves: stop keeping the point centered.
  useEffect(() => {
    if (!map) return;
    const release = () => {
      if (!flying.current) focus.current = null;
    };
    const settled = () => {
      flying.current = false;
    };
    const dragged = () => {
      focus.current = null;
    };
    map.on("zoomstart", release);
    map.on("dragstart", dragged);
    map.on("moveend", settled);
    return () => {
      map.off("zoomstart", release);
      map.off("dragstart", dragged);
      map.off("moveend", settled);
      window.clearTimeout(recenterTimer.current);
    };
  }, [map]);

  const ui = useMemo(() => ({ map, sheetHeight, focus, flying, sheetChanged }), [map, sheetChanged]);

  return (
    <MapUIContext.Provider value={ui}>
      <div className="fixed inset-0 overflow-hidden bg-zinc-100">
        <MapContainer
          ref={setMap}
          center={initial ?? DEFAULT_CENTER}
          zoom={initial ? 15 : 12}
          className="absolute inset-0 z-0"
          zoomControl={false}
          attributionControl={false}
          preferCanvas
        >
          {tiles && (
            <TileLayer
              key={tiles.tile_url}
              attribution={tiles.attribution}
              url={tiles.tile_url}
              maxZoom={20}
              maxNativeZoom={tiles.provider === "osm" ? 19 : 18}
              eventHandlers={{ tileload: onTileLoad, tileerror: onTileError }}
            />
          )}
          <AttributionControl position="topright" prefix={false} />
        </MapContainer>
        {children}
      </div>
    </MapUIContext.Provider>
  );
}

/** Draw react-leaflet layers on the background map from anywhere in the app. */
export function MapLayers({ children }: { children: ReactNode }) {
  const { map } = useMapUI();
  const ctx = useMemo(() => (map ? createLeafletContext(map) : null), [map]);
  if (!ctx) return null;
  return <LeafletContext.Provider value={ctx}>{children}</LeafletContext.Provider>;
}

/** Center of the part of the map that is not hidden by the top bar and the bottom sheet. */
function visibleCenter(map: L.Map, target: L.LatLngExpression, zoom: number, sheetHeight: number): L.LatLng {
  const offsetY = (sheetHeight - TOP_BAR_PX) / 2;
  return map.unproject(map.project(target, zoom).add([0, offsetY]), zoom);
}

export function useFlyTo() {
  const { map, sheetHeight, focus, flying } = useMapUI();
  return (point: [number, number], zoom?: number) => {
    if (!map) return;
    const z = zoom ?? Math.max(map.getZoom(), 16);
    focus.current = { point, zoom: z };
    flying.current = true;
    map.flyTo(visibleCenter(map, point, z, sheetHeight.current ?? 0), z, { duration: 0.6 });
  };
}

/** Fit the view to the given points (above the sheet) whenever `fitKey` changes. */
export function FitBounds({ points, fitKey, maxZoom = 17 }: { points: [number, number][]; fitKey: string; maxZoom?: number }) {
  const map = useMap();
  const { sheetHeight, focus, flying } = useMapUI();
  const flyTo = useFlyTo();
  useEffect(() => {
    if (points.length === 0) return;
    if (points.length === 1) {
      flyTo(points[0], Math.max(map.getZoom(), 15));
      return;
    }
    focus.current = null; // a set of points, not one point to keep centered
    flying.current = true;
    map.flyToBounds(L.latLngBounds(points), {
      paddingTopLeft: [24, TOP_BAR_PX + 8],
      // A tall sheet on a short screen would leave a sliver of map: never reserve more than 60 % of it.
      paddingBottomRight: [24, Math.min((sheetHeight.current ?? 0) + 16, map.getSize().y * 0.6)],
      maxZoom,
      duration: 0.6,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey, map]);
  return null;
}

/** Fly to `point` whenever it changes. */
export function FlyTo({ point, zoom }: { point: [number, number] | null; zoom?: number }) {
  const flyTo = useFlyTo();
  const key = point ? `${point[0]},${point[1]}` : "";
  useEffect(() => {
    if (point) flyTo(point, zoom);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return null;
}

export function MapClick({ onClick }: { onClick: (p: LatLon) => void }) {
  useMapEvents({ click: (e) => onClick({ lat: e.latlng.lat, lon: e.latlng.lng }) });
  return null;
}

export function UserPosition({ position }: { position: (LatLon & { accuracy: number }) | null }) {
  if (!position) return null;
  const center: [number, number] = [position.lat, position.lon];
  return (
    <>
      {position.accuracy < 300 && (
        <Circle
          center={center}
          radius={position.accuracy}
          interactive={false}
          pathOptions={{ color: "#2563eb", weight: 1, opacity: 0.4, fillOpacity: 0.08 }}
        />
      )}
      <CircleMarker
        center={center}
        radius={8}
        interactive={false}
        pathOptions={{ color: "white", weight: 3, fillColor: "#2563eb", fillOpacity: 1 }}
      />
    </>
  );
}

export function stopIcon(label: string | number, color: string, current = false, size = 28, count = 1): L.DivIcon {
  const badge = count > 1 ? `<span class="stop-count">${count}</span>` : "";
  return L.divIcon({
    className: "",
    html: `<div class="stop-marker${current ? " current" : ""}" style="background:${color};width:${size}px;height:${size}px">${label}${badge}</div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

const PIN_ICONS = {
  start: '<polygon points="7 4 19 12 7 20 7 4" fill="currentColor"/>',
  end: '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" fill="currentColor"/><line x1="4" x2="4" y1="22" y2="15"/>',
  center: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3" fill="currentColor"/>',
  place: '<path d="M20 10c0 5-8 12-8 12s-8-7-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/>',
};

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

export function PinMarker({
  point,
  color,
  label,
  kind = "place",
}: {
  point: LatLon;
  color: string;
  label: string;
  kind?: keyof typeof PIN_ICONS;
}) {
  const icon = useMemo(
    () =>
      L.divIcon({
        className: "",
        html: `<div class="map-pin">
          <div class="map-pin-label" style="background:${color}">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">${PIN_ICONS[kind]}</svg>
            ${escapeHtml(label)}
          </div>
          <div class="map-pin-stem" style="background:${color}"></div>
          <div class="map-pin-dot" style="background:${color}"></div>
        </div>`,
        iconSize: [0, 0],
      }),
    [color, label, kind],
  );
  return <Marker position={[point.lat, point.lon]} icon={icon} interactive={false} />;
}
