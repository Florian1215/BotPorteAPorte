export type LoginRequestResponse = { email: string; expires_in_minutes: number };

export type LatLon = { lat: number; lon: number };

export type Organization = {
  code: string;
  name: string;
  country_code: string;
  city: string;
  city_lat: number | null;
  city_lon: number | null;
  logo_url: string | null;
};

export type City = { name: string; region: string; country: string; country_code: string; lat: number; lon: number };

/** Fields sent to the API when a city is picked (country deduced from it). */
export type CityFields = Pick<Organization, "city" | "city_lat" | "city_lon" | "country_code">;

export type OrganizationAdmin = Organization & {
  n_members?: number;
  n_pending?: number;
  /** Voter list (LEC) the organization depends on (chosen by a site admin), and how far around its city. */
  voter_list: number | null;
  voter_list_name: string | null;
  radius_km: number;
};

/** A consular voter list (LEC), shared by the organizations depending on it; managed by the site admins. */
export type VoterList = {
  id: number;
  name: string;
  country_code: string;
  created_at: string;
  n_active: number;
  n_disabled: number;
  organizations: { code: string; name: string; city: string }[];
};

export type Role = "militant" | "experienced" | "manager" | "admin";

export type User = {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  is_approved: boolean;
  suspended_at: string | null;
  is_staff: boolean;
  role: Role;
  can_canvass: boolean;
  can_validate: boolean;
  can_manage_organization: boolean;
  is_site_admin: boolean;
  organization: Organization | null;
  /** Telegram account linked from "Mon compte" (visits made with the old bot are then this user's). */
  telegram_id: number | null;
  /** App opened when tapping an address during a tour. */
  navigation_app: NavigationApp;
};

export type NavigationApp = "google" | "apple";

export type Member = {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  role: Role;
  is_approved: boolean;
  /** Suspended by a responsable: listed with the members (to reactivate), not with the sign-ups. */
  suspended_at: string | null;
  organization: string | null;
  date_joined: string;
  last_login: string | null;
};

export type ResultValue =
  | "commitment_to_vote"
  | "good_conversation"
  | "not_interested"
  | "do_not_contact"
  | "address_to_retry"
  | "address_failure";

/** Only for "address_to_retry": leaflet left in the mailbox, or mailbox out of reach. */
export type AbsentDetail = "leaflet" | "mailbox_inaccessible";

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
  first_names?: string;
  birth_year?: number | null;
};

export type Stop = {
  id: number;
  position: number;
  result: ResultValue | null;
  absent_detail: AbsentDetail | null;
  visited_at: string | null;
  /** Last time this person was found absent in another tour. */
  /** Last time someone knocked at this door, in another tour (possibly for a past election). */
  last_visit: {
    at: string;
    by: string | null;
    result: ResultValue;
    detail: AbsentDetail | null;
    /** "pour l'élection consulaire 2026" */
    election: string | null;
    current_election: boolean;
  } | null;
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

/** A polling district (Wahlbezirk), as shown on maps and in lists. */
export type District = {
  id: number;
  code: string;
  name: string;
  score: number;
  geometry: GeoJSONGeometry;
  label: LatLon | null;
  /** Share of the organization's addresses inside that were visited at least once. */
  done_pct?: number;
  n_to_visit?: number;
};

/** Best districts to canvass, for prepared tours (militant·es). */
/** `n_total`: French voters of the current election in the district, `n_done`: those done. */
export type Area = District & { n_to_visit: number; done_pct: number; n_total: number; n_done: number };

export type ScoreCriterionKey = "party" | "abstention" | "age" | "density" | "social";
export type ScoreWeights = Record<ScoreCriterionKey, number>;

export type DistrictImport = {
  id: number;
  source: string;
  status: "pending" | "running" | "done" | "failed";
  message: string;
  report: {
    n_districts?: number;
    n_with_census?: number;
    n_without_results?: number;
    examples_without_results?: string[];
    n_results_without_district?: number;
    examples_results_without_district?: string[];
    n_with_social?: number;
    /** City pack: level of the zones and official sources. */
    level?: string;
    sources?: string[];
  };
  created_at: string;
  finished_at: string | null;
};

/** The zones' progress (% done) is the one of the current election, set by the site admins. */
export type ProgressElections = {
  /** Name of that election, null when none is current. */
  progress_election: string | null;
};

export type DistrictMap = ProgressElections & {
  /** Reference election of the score (votes), not the canvassing campaign. */
  election: string;
  /** `n_total`: French voters of the current election in the district, `n_done`: those done. */
  districts: (District & { done_pct: number; n_total: number; n_done: number })[];
  weights: ScoreWeights;
  criteria: { key: ScoreCriterionKey; label: string }[];
  import: DistrictImport | null;
  /** One-click imports of the cities with official open data, the organization's city first. */
  packs: CityPack[];
} & ReferenceParty;

/** The organization's party standing in for LFI, and its social indicator. */
export type ReferenceParty = {
  reference_party: string;
  /** Parties of the results whose votes are summed (several for joint lists). */
  reference_party_columns: string[];
  /** Parties found in the imported results, most voted first. */
  party_options: string[];
  social_label: string;
  social_higher_is_poorer: boolean;
};

export type DistrictDetail = District & ProgressElections & {
  done_pct: number;
  election: string;
  eligible: number | null;
  voters: number | null;
  valid: number | null;
  reference_party: string;
  reference_party_columns: string[];
  reference_votes: number | null;
  reference_pct: number | null;
  turnout_pct: number | null;
  parties: { name: string; votes: number; pct: number | null }[];
  area_km2: number;
  density: number | null;
  share_18_29: number | null;
  /** LFI vote expected from the age of the French voters of the list (0–1). */
  age_lfi_vote: number | null;
  share_65_plus: number | null;
  /** The organization's social indicator (share 0–1, rate or income), null without data. */
  social_label: string;
  social_value: number | null;
  score_parts: { key: ScoreCriterionKey; label: string; value: number | null; rank: number | null; weight: number }[];
  progress: DistrictProgress;
  /** Age of the French voters of the list living in the district (year of birth). */
  ages: { groups: { label: string; count: number }[]; unknown: number };
};

/** The organization's addresses (French voters on the list) in a district. */
export type DistrictProgress = {
  total: number;
  /** Still to do: nobody went yet (or mailbox inaccessible) + leaflet left but nobody met. */
  remaining: number;
  not_leafleted: number;
  leafleted: number;
  /** Remaining ones not in someone's tour right now (can go in a new tour). */
  to_visit: number;
  done: number;
  done_pct: number;
};

export type CityPack = {
  key: string;
  city: string;
  /** ISO country code. */
  country: string;
  election: string;
  /** "bureaux de vote", "quartiers", "arrondissements"… */
  level: string;
  description: string;
  sources: string[];
  label: string;
  /** The pack of the organization's city. */
  recommended: boolean;
};

/** Dots on the map only: no street address, no names. */
export type NearbyResponse = { total: number; truncated: boolean; addresses: { id: number; lat: number; lon: number }[] };

export type MyStats = {
  total_success: number;
  total_visits: number;
  by_result: Record<ResultValue, number>;
  tours_completed: number;
  rank: number;
  ranked_members: number;
};

export type MemberRankRow = { id: number; rank: number; name: string; organization: string; doors: number; is_me: boolean };

export type OrganizationRankRow = {
  id: number;
  rank: number;
  name: string;
  city: string;
  logo_url: string | null;
  members: number;
  doors: number;
  is_me: boolean;
};

/** Only the doors knocked for the current election count (`election`: its name, null when none is set). */
export type Leaderboard = { election: string | null } & (
  | { scope: "group" | "all"; rows: MemberRankRow[] }
  | { scope: "organizations"; rows: OrganizationRankRow[] }
);

export type OrganizationOverview = {
  total: number;
  doors_knocked: number;
  doors_by_result: Record<ResultValue, number>;
  /** Current election (the doors knocked only count its visits), null when none is set. */
  election: string | null;
  by_status: Record<
    "to_visit" | "planned" | "failure" | "commitment_to_vote" | "good_conversation" | "do_not_contact" | "not_interested",
    number
  >;
};

export type AddressCounts = { active: number; disabled: number };

export type ImportReport = {
  total: number;
  new: number;
  existing: number;
  reactivated: number;
  disabled: number;
  invalid: number;
  errors: string[];
  /** People whose address changed since the last list. */
  moved: number;
  /** Distinct addresses never located before (the slow part of the import). */
  to_geocode: number;
  not_geocoded: number;
  not_geocoded_examples: string[];
  /** Why some addresses could not be sent to ArcGIS (service refused or unreachable). */
  geocoding_warnings?: string[];
  dry_run?: boolean;
};

export type Election = {
  id: number;
  name: string;
  is_current: boolean;
  created_at: string;
  started_at: string | null;
  n_visits: number;
};

export type SiteElections = { elections: Election[]; to_reset: number };

/** Background import of the voter list (geocoding). */
export type AddressImportJob = {
  id: number;
  filename: string;
  status: "running" | "done" | "failed";
  message: string;
  report: Partial<ImportReport>;
  geocode_total: number;
  geocode_done: number;
  created_at: string;
  finished_at: string | null;
};

export type FreeTourPreview = {
  route: [number, number][];
  route_approximate: boolean;
  corridor: GeoJSONGeometry;
  n_addresses: number;
  max_stops: number;
};
