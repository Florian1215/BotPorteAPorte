import type { Area } from "../api/types";

/** Every vertex of a zone as [lat, lon] (to fit the map on it). */
export function areaPoints(area: Pick<Area, "geometry">): [number, number][] {
  const pts: [number, number][] = [];
  const walk = (c: unknown) => {
    if (Array.isArray(c) && typeof c[0] === "number") pts.push([c[1] as number, c[0] as number]);
    else if (Array.isArray(c)) c.forEach(walk);
  };
  walk(area.geometry.coordinates);
  return pts;
}
