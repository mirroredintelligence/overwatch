import type { OptionView, OptionsParts } from '@/lib/advisor/options';

// Sample options for the radar screens (RadarWeb, RadarPhone). Sample data only: the service names are the
// sample board's and the coordinates are invented points around one sample area, not real places. The
// shape is what the BFF answers for a case's options (lib/advisor/options.ts), the same as the map's.

const base: OptionView = {
  serviceId: '',
  name: '',
  category: null,
  status: 'accepting',
  effectiveAvailable: null,
  overBy: null,
  unitLabel: null,
  travelText: null,
  dataAgeSeconds: null,
  staleWarning: false,
  criteriaVersion: 3,
  fits: [],
  checks: [],
  phone: null,
  network: null,
  position: null,
  coverage: null,
  travel: null,
};

export const UCR_WEST: OptionView = {
  ...base,
  serviceId: 'svc-ucr-west',
  name: 'UCR West',
  category: 'urgent-community-response',
  effectiveAvailable: 4,
  unitLabel: 'referrals in the next 2 hrs',
  travelText: 'about 25 to 35 min',
  dataAgeSeconds: 540,
  coverage: { lat: 50.72, lon: -2.45, radiusKm: 12 },
};

export const UCR_EAST: OptionView = {
  ...base,
  serviceId: 'svc-ucr-east',
  name: 'UCR East',
  category: 'urgent-community-response',
  status: 'limited',
  effectiveAvailable: 1,
  unitLabel: 'referral',
  travelText: 'about 40 to 55 min',
  dataAgeSeconds: 1860,
  coverage: { lat: 50.7, lon: -2.3, radiusKm: 14 },
};

export const HOSPITAL_AT_HOME: OptionView = {
  ...base,
  serviceId: 'svc-hospital-at-home',
  name: 'Hospital at home',
  category: 'hospital-at-home-or-virtual-ward',
  status: 'over-capacity',
  overBy: 2,
  dataAgeSeconds: 840,
  coverage: { lat: 50.71, lon: -2.44, radiusKm: 15 },
};

export const WARD_B: OptionView = {
  ...base,
  serviceId: 'svc-ward-b',
  name: 'Community hospital · Ward B',
  category: 'inpatient-beds',
  effectiveAvailable: 5,
  unitLabel: 'beds free',
  travelText: 'about 35 to 50 min',
  dataAgeSeconds: 8100,
  staleWarning: true,
  position: { lat: 50.69, lon: -2.4 },
  travel: { low: 35, high: 50, source: 'Routing data, updated 12 Oct', legs: [] },
};

/** A visiting service far from the others: no overlap with them and does not cover the patient. */
export const UCR_FAR: OptionView = {
  ...base,
  serviceId: 'svc-ucr-far',
  name: 'UCR Far',
  category: 'urgent-community-response',
  coverage: { lat: 51.2, lon: -1.2, radiusKm: 5 },
};

export const RADAR_PARTS: OptionsParts = {
  options: [UCR_WEST, UCR_EAST, HOSPITAL_AT_HOME, WARD_B],
  notSuitable: [{ serviceId: 'svc-utc', name: 'Urgent treatment centre', reason: 'Open until 20:00, not suited to this need' }],
  patientArea: { lat: 50.71, lon: -2.44 },
  notFound: false,
  outOfArea: false,
  districts: [],
};

/** What the BFF answers for the radar's options read (`?only=own`). */
export const RADAR_VIEW = { shownAt: '2026-10-30T14:12:00.000Z', ...RADAR_PARTS, network: 'none' };

export const RADAR_NOT_FOUND = { ...RADAR_VIEW, notFound: true, options: [], notSuitable: [], patientArea: null, districts: ['DT3', 'DT4'] };
export const RADAR_OUT_OF_AREA = { ...RADAR_VIEW, outOfArea: true, options: [], notSuitable: [], patientArea: null, districts: ['DT3'] };
export const RADAR_EMPTY = { ...RADAR_VIEW, options: [], notSuitable: [] };

// ---- The same options as the back end's `$filter-options` Parameters (for the browser tests' stand-in) ----

type Part = {
  name: string;
  valueString?: string;
  valueCode?: string;
  valueInteger?: number;
  valueDecimal?: number;
  valueBoolean?: boolean;
  part?: Part[];
};

function optionPart(option: OptionView): Part {
  const parts: Part[] = [
    { name: 'serviceId', valueString: option.serviceId },
    { name: 'name', valueString: option.name },
    { name: 'status', valueCode: option.status },
  ];
  if (option.category !== null) parts.push({ name: 'category', valueCode: option.category });
  if (option.criteriaVersion !== null) parts.push({ name: 'criteriaVersion', valueInteger: option.criteriaVersion });
  if (option.effectiveAvailable !== null) parts.push({ name: 'effectiveAvailable', valueInteger: option.effectiveAvailable });
  if (option.overBy !== null) parts.push({ name: 'overBy', valueInteger: option.overBy });
  if (option.unitLabel !== null) parts.push({ name: 'unitLabel', valueString: option.unitLabel });
  if (option.dataAgeSeconds !== null) parts.push({ name: 'dataAgeSeconds', valueInteger: option.dataAgeSeconds });
  const range = /(\d+) to (\d+) min/.exec(option.travelText ?? '');
  if (range !== null) {
    parts.push({ name: 'travelLow', valueInteger: Number(range[1]) }, { name: 'travelHigh', valueInteger: Number(range[2]) });
  }
  const place = option.coverage ?? option.position;
  if (place !== null) parts.push({ name: 'lat', valueDecimal: place.lat }, { name: 'lon', valueDecimal: place.lon });
  if (option.coverage !== null) parts.push({ name: 'coverageRadiusKm', valueDecimal: option.coverage.radiusKm });
  return { name: 'option', part: parts };
}

/** `$filter-options` as the back end answers it for the radar's sample case. */
export const RADAR_PARAMETERS = {
  resourceType: 'Parameters',
  parameter: [
    ...RADAR_PARTS.options.map(optionPart),
    ...RADAR_PARTS.notSuitable.map((item) => ({
      name: 'notSuitable',
      part: [
        { name: 'serviceId', valueString: item.serviceId },
        { name: 'name', valueString: item.name },
        { name: 'reason', valueString: item.reason },
      ],
    })),
    { name: 'patientLat', valueDecimal: RADAR_PARTS.patientArea?.lat },
    { name: 'patientLon', valueDecimal: RADAR_PARTS.patientArea?.lon },
  ],
};

/** A postcode the back end cannot place, with the districts the services cover to choose from. */
export const RADAR_NOT_FOUND_PARAMETERS = {
  resourceType: 'Parameters',
  parameter: [
    { name: 'notFound', valueBoolean: true },
    { name: 'outOfArea', valueBoolean: false },
    { name: 'district', valueString: 'DT3' },
    { name: 'district', valueString: 'DT4' },
  ],
};
