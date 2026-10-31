import type { BoardStatus } from '@/lib/board/types';

// The network answers as the screens read them (TEN-068). They are the back end's own (routes_network.py,
// routes_network_views.py) in camelCase, cut down to the fields a page uses. None holds a tenant, a
// grant, a source service id or any personal data: a network carries capacity only (DEC-1100 Q11).

export type NetworkSummary = {
  /** The opaque id the server offered (`net-...`). A choice among the offered networks, never an authority. */
  id: string;
  name: string;
  systemName: string;
  pathwayName: string;
  timeZone: string;
};

/** What `GET /api/bff/network` answers. */
export type NetworkList = {
  /** The viewer's own organisation's display name, to mark its rows. Null when it cannot be read. */
  ownOrganisation: string | null;
  networks: NetworkSummary[];
};

export type Presentation = 'shown' | 'unavailable';
export type Pressure = 'normal' | 'watch' | 'high';

export type NetworkBoardEntry = {
  /** An opaque reference of the row; never a service id of an organisation. */
  rowRef: string;
  organisationName: string;
  serviceName: string;
  category: string;
  presentation: Presentation;
  status: BoardStatus | null;
  unitLabel: string | null;
  effectiveAvailable: number | null;
  overBy: number | null;
  used: number | null;
  established: number | null;
  reportedAt: string | null;
  staleWarning: boolean;
  wasDueAt: string | null;
};

export type NetworkBoard = {
  entries: NetworkBoardEntry[];
  pressure: Pressure;
  allLimitedOrWorse: boolean;
  /** The back end's clock when the board was built. */
  generatedAt: string;
  systemName: string;
  pathwayName: string;
  timeZone: string;
};

export type EndReason = 'left' | 'grant-ended' | 'replaced';

export type NetworkLocation = {
  name: string;
  postalDistrict: string;
  city: string;
  latitude: number | null;
  longitude: number | null;
};

export type OpeningHour = {
  position: number;
  /** 0 is Monday, 6 is Sunday. */
  days: number[];
  allDay: boolean;
  start: string | null;
  end: string | null;
};

export type NetworkDirectoryEntry = {
  rowRef: string;
  organisationName: string;
  serviceName: string;
  category: string;
  active: boolean;
  source: 'manual' | 'directory-of-services';
  contactLabel: string | null;
  contactPhone: string | null;
  location: NetworkLocation | null;
  openingHours: OpeningHour[];
  presentation: Presentation;
  endedAt: string | null;
  endReason: EndReason | null;
};

export type NetworkDirectory = {
  entries: NetworkDirectoryEntry[];
  systemName: string;
  pathwayName: string;
  timeZone: string;
};

export type NetworkCriteriaEntry = {
  rowRef: string;
  organisationName: string;
  serviceName: string;
  version: number;
  ageMin: number;
  ageMax: number;
  districts: string[];
  accepts: string[];
  excludes: string[];
  /** A date, `YYYY-MM-DD`. */
  reviewBy: string;
  endedAt: string | null;
  endReason: EndReason | null;
};

export type NetworkCriteria = {
  entries: NetworkCriteriaEntry[];
  systemName: string;
  pathwayName: string;
  timeZone: string;
};

export const SYSTEM_NOW_KEYS = ['accepting', 'limited', 'not-accepting', 'over-capacity', 'not-updated', 'out-of-hours', 'unavailable'] as const;
export type SystemNowKey = (typeof SYSTEM_NOW_KEYS)[number];

export type NetworkSystemNow = {
  generatedAt: string;
  services: number;
  organisations: number;
  byStatus: Record<SystemNowKey, number>;
  pressure: Pressure;
  allLimitedOrWorse: boolean;
  alert: { raised: boolean; level: Pressure; limitedOrWorse: number; watchFrom: number; highFrom: number };
  systemName: string;
  pathwayName: string;
  timeZone: string;
};

export type NetworkPhone = {
  rowRef: string;
  organisationName: string;
  serviceName: string;
  category: string;
  presentation: Presentation;
  status: BoardStatus | null;
  staleWarning: boolean;
  reportedAt: string | null;
  contactLabel: string | null;
  contactPhone: string | null;
};

export type NetworkPhones = {
  phones: NetworkPhone[];
  organisations: number;
  systemName: string;
  pathwayName: string;
  timeZone: string;
};

/** One figure of the week. A hidden figure has no value (fewer than 10). */
export type WeekMeasure = { label: string; value: number | null; hidden: boolean };

export const WEEK_STATUSES = ['accepting', 'limited', 'not-accepting', 'over-capacity', 'not-updated', 'out-of-hours'] as const;
export const WEEK_PRESSURES = ['normal', 'watch', 'high'] as const;

export type NetworkWeek = {
  weekStart: string;
  withheld: boolean;
  hoursSampled: WeekMeasure;
  onTimePct: WeekMeasure;
  statusShare: Record<(typeof WEEK_STATUSES)[number], WeekMeasure>;
  pressureHours: Record<Pressure, WeekMeasure>;
  pressureOverTime: { hour: string; pressure: Pressure }[];
  systemName: string;
  pathwayName: string;
  timeZone: string;
};
