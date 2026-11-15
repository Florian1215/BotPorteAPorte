import { useEffect, useState } from "react";
import { Circle, CircleMarker, Popup } from "react-leaflet";

import { api, errorMessage } from "../api/client";
import type { LatLon, NearbyResponse } from "../api/types";
import LocationStatus from "../components/LocationStatus";
import { FitBounds, MapClick, MapLayers, PinMarker } from "../components/map";
import { Alert, Chips, Sheet, Spinner } from "../components/ui";
import { useGeo } from "../hooks/useGeolocation";
import { NEARBY_RADIUS_OPTIONS_KM, formatKm } from "../lib/constants";

export default function Nearby() {
  const geo = useGeo();
  const [center, setCenter] = useState<LatLon | null>(null);
  const [radius, setRadius] = useState<number>(0.2);
  const [data, setData] = useState<NearbyResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Use the device position as soon as it is known
  useEffect(() => {
    if (!center && geo.here) setCenter(geo.here);
  }, [geo.here, center]);

  useEffect(() => {
    if (!center) return;
    setLoading(true);
    setError(null);
    api<NearbyResponse>("/addresses/nearby/", { query: { lat: center.lat, lon: center.lon, radius_km: radius } })
      .then(setData)
      .catch((e) => setError(errorMessage(e)))
      .finally(() => setLoading(false));
  }, [center, radius]);

  const circleBounds: [number, number][] = center
    ? [
        [center.lat + radius / 111.32, center.lon],
        [center.lat - radius / 111.32, center.lon],
      ]
    : [];

  const subtitle = loading ? (
    <span className="inline-flex items-center gap-2">
      <Spinner className="size-4" /> Recherche…
    </span>
  ) : data && center ? (
    data.total === 0 ? (
      "Aucune adresse à visiter dans ce rayon."
    ) : (
      `${data.total.toLocaleString("fr")} adresse${data.total > 1 ? "s" : ""} à visiter dans un rayon de ${formatKm(radius)}`
    )
  ) : (
    "Touche la carte pour choisir un point."
  );

  return (
    <>
      <MapLayers>
        <MapClick onClick={setCenter} />
        <FitBounds points={circleBounds} fitKey={`${center?.lat}-${center?.lon}-${radius}`} />
        {center && (
          <>
            <Circle
              center={[center.lat, center.lon]}
              radius={radius * 1000}
              interactive={false}
              pathOptions={{ color: "#d1271c", weight: 1.5, dashArray: "4 6", fillOpacity: 0.06 }}
            />
            <PinMarker point={center} color="#18181b" label="Centre" kind="center" />
          </>
        )}
        {data?.addresses.map((a) => (
          <CircleMarker
            key={a.id}
            center={[a.lat, a.lon]}
            radius={6}
            pathOptions={{ color: "white", weight: 1.5, fillColor: "#d1271c", fillOpacity: 0.9 }}
          >
            <Popup>{a.label}</Popup>
          </CircleMarker>
        ))}
      </MapLayers>

      <Sheet title="Adresses alentours" subtitle={subtitle}>
        <Chips options={NEARBY_RADIUS_OPTIONS_KM} value={radius} onChange={setRadius} format={formatKm} />
        {!center && <LocationStatus geo={geo} onRetry={geo.retry} />}
        {data?.truncated && (
          <p className="text-xs text-zinc-500">Seules les {data.addresses.length} plus proches sont affichées sur la carte.</p>
        )}
        {error && <Alert>{error}</Alert>}
      </Sheet>
    </>
  );
}
