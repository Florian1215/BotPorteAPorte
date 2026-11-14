export type LatLon = { lat: number; lon: number };

export type Scope = { code: string; name: string; country_code: string };

export type User = {
  id: number;
  username: string;
  first_name: string;
  is_approved: boolean;
  is_staff: boolean;
  can_canvass: boolean;
  scope: Scope | null;
};

export type ResultValue =
  | "commitment_to_vote"
  | "good_conversation"
  | "do_not_contact"
  | "address_to_retry"
  | "address_failure";

export type AddressDTO = {
  id: number;
  address: string;
  zip_code: string;
  city: string;
  label: string;
  lat: number;
  lon: number;
  name?: string;
  first_name?: string;
};

export type Stop = {
  id: number;
  position: number;
  result: ResultValue | null;
  visited_at: string | null;
  address: AddressDTO;
};

export type TourSummary = Record<ResultValue, number> & { total_success: number; not_visited: number };

export type Tour = {
  id: number;
  kind: "free" | "predefined";
  status: "draft" | "active" | "completed";
  area: { id: number; name: string } | null;
  start: LatLon;
  end: LatLon | null;
  radius_km: number | null;
  route: [number, number][] | null;
  route_distance_m: number | null;
  route_duration_s: number | null;
  route_approximate: boolean;
  too_many_addresses: boolean;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  stops: Stop[];
  summary: TourSummary;
};

export type GeoJSONGeometry = { type: "Polygon" | "MultiPolygon"; coordinates: unknown };

export type Area = { id: number; name: string; score: number; n_to_visit: number; geometry: GeoJSONGeometry };

export type NearbyResponse = { total: number; truncated: boolean; addresses: AddressDTO[] };

export type GeocodedAddress = { address: string; zip_code: string; city: string; lat: number; lon: number };

export type MyStats = {
  total_success: number;
  total_visits: number;
  by_result: Record<ResultValue, number>;
  tours_completed: number;
};

export type ScopeOverview = {
  total: number;
  by_status: Record<
    "to_visit" | "planned" | "failure" | "commitment_to_vote" | "good_conversation" | "do_not_contact",
    number
  >;
};
