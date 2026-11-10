import type { StatusCode } from '@/components/ui/StatusBadge';
import type { PressureItem, UnderutilisedItem } from '@/lib/lead/types';

// The Analytics User's overview as the browser sees it (DEC-1368): figures about the organisation's own services.
// There is no case, patient, postcode or phone number in it, and no total of places available (DEC-1343).

export type AnalyticsService = {
  serviceId: string;
  name: string;
  /** A service category code such as `urgent-community-response`. */
  category: string;
  status: StatusCode;
  /** The districts the service covers, in name order. Empty means it is not placed. */
  districts: string[];
  /** False when the figure is old, late or unknown: `available` and `overBy` are then null. */
  figureCurrent: boolean;
  available: number | null;
  overBy: number | null;
  unitLabel: string;
  reportedAt: string | null;
};

export type AnalyticsCounts = {
  accepting: number;
  limited: number;
  notAccepting: number;
  overCapacity: number;
  notUpdated: number;
};

export type AnalyticsOverview = {
  generatedAt: string;
  counts: AnalyticsCounts;
  outOfHours: number;
  services: AnalyticsService[];
  underPressure: PressureItem[];
  underutilised: UnderutilisedItem[];
};
