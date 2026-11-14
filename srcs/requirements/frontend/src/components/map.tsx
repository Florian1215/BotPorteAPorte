import { LeafletContext, createLeafletContext } from "@react-leaflet/core";
import L from "leaflet";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AttributionControl, Circle, CircleMarker, MapContainer, Marker, TileLayer, useMap, useMapEvents } from "react-leaflet";

import type { LatLon } from "../api/types";
import { MapUIContext, useMapUI } from "../context/MapContext";
import { lastKnownPosition } from "../hooks/useGeolocation";
import { DEFAULT_CENTER } from "../lib/constants";

/** Height reserved for the floating top bar. */
const TOP_BAR_PX = 72;

/** Full-screen map, always mounted behind the whole app. */
export function MapShell({ children }: { children: ReactNode }) {
  const [map, setMap] = useState<L.Map | null>(null);
  const sheetHeight = useRef(0);
  const initial = useMemo(() => lastKnownPosition(), []);
  const ui = useMemo(() => ({ map, sheetHeight }), [map]);

  return (
    <MapUIContext.Provider value={ui}>
      <div className="fixed inset-0 overflow-hidden bg-slate-200">
        <MapContainer
          ref={setMap}
          center={initial ?? DEFAULT_CENTER}
          zoom={initial ? 15 : 12}
          className="absolute inset-0 z-0"
          zoomControl={false}
          attributionControl={false}
          preferCanvas
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            maxZoom={19}
          />
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
  const { map, sheetHeight } = useMapUI();
  return (point: [number, number], zoom?: number) => {
    if (!map) return;
    const z = zoom ?? Math.max(map.getZoom(), 16);
    map.flyTo(visibleCenter(map, point, z, sheetHeight.current ?? 0), z, { duration: 0.6 });
  };
}

/** Fit the view to the given points (above the sheet) whenever `fitKey` changes. */
export function FitBounds({ points, fitKey, maxZoom = 17 }: { points: [number, number][]; fitKey: string; maxZoom?: number }) {
  const map = useMap();
  const { sheetHeight } = useMapUI();
  const flyTo = useFlyTo();
  useEffect(() => {
    if (points.length === 0) return;
    if (points.length === 1) {
      flyTo(points[0], Math.max(map.getZoom(), 15));
      return;
    }
    map.flyToBounds(L.latLngBounds(points), {
      paddingTopLeft: [24, TOP_BAR_PX + 8],
      paddingBottomRight: [24, (sheetHeight.current ?? 0) + 16],
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
          pathOptions={{ color: "#2563eb", weight: 1, fillOpacity: 0.08 }}
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

export function stopIcon(label: string | number, color: string, current = false, size = 28): L.DivIcon {
  return L.divIcon({
    className: "",
    html: `<div class="stop-marker${current ? " current" : ""}" style="background:${color};width:${size}px;height:${size}px">${label}</div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

export function PinMarker({ point, color, label }: { point: LatLon; color: string; label: string }) {
  const icon = useMemo(
    () =>
      L.divIcon({
        className: "",
        html: `<div style="transform:translate(-50%,-100%);position:absolute;left:0;top:0;display:flex;flex-direction:column;align-items:center">
          <div style="background:${color};color:white;font-weight:700;font-size:12px;padding:3px 8px;border-radius:9999px;box-shadow:0 1px 4px rgba(0,0,0,.35);white-space:nowrap">${label}</div>
          <div style="width:2px;height:10px;background:${color}"></div>
          <div style="width:10px;height:10px;border-radius:9999px;background:${color};border:2px solid white;margin-top:-3px"></div>
        </div>`,
        iconSize: [0, 0],
      }),
    [color, label],
  );
  return <Marker position={[point.lat, point.lon]} icon={icon} interactive={false} />;
}
