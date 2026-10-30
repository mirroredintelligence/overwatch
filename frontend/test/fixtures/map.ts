// Sample map data (W50). Service names are the sample board's; the coordinates are invented points
// around one sample area, not real places. The Parameters below extend `$filter-options` with the
// parts the map needs (docs/delivery/fragments/W50.md): the patient point, positions, coverage and
// travel legs, and the two flags. The back end does not send them yet.

type Part = { name: string; valueString?: string; valueCode?: string; valueInteger?: number; valueDecimal?: number; valueBoolean?: boolean; part?: Part[] };

const leg = (label: string, low: number, high: number, how: string, source: string): Part => ({
  name: 'leg',
  part: [
    { name: 'label', valueString: label },
    { name: 'low', valueInteger: low },
    { name: 'high', valueInteger: high },
    { name: 'how', valueString: how },
    { name: 'source', valueString: source },
  ],
});

export const MAP_PARAMETERS = {
  resourceType: 'Parameters',
  parameter: [
    { name: 'patientLat', valueDecimal: 50.7 },
    { name: 'patientLon', valueDecimal: -2.44 },
    { name: 'notFound', valueBoolean: false },
    { name: 'outOfArea', valueBoolean: false },
    {
      name: 'option',
      part: [
        { name: 'serviceId', valueString: 'svc-ucr-west' },
        { name: 'name', valueString: 'UCR West' },
        { name: 'status', valueCode: 'accepting' },
        { name: 'criteriaVersion', valueInteger: 3 },
        { name: 'effectiveAvailable', valueInteger: 4 },
        { name: 'unitLabel', valueString: 'referrals in the next 2 hrs' },
        { name: 'travelLow', valueInteger: 35 },
        { name: 'travelHigh', valueInteger: 50 },
        { name: 'travelSource', valueString: 'Routing data, updated 12 Oct' },
        { name: 'dataAgeSeconds', valueInteger: 540 },
        { name: 'lat', valueDecimal: 50.72 },
        { name: 'lon', valueDecimal: -2.45 },
        leg('Patient to UCR West, by road', 35, 50, 'Typical weekday afternoon. The spread is from traffic.', 'Routing data, updated 12 Oct'),
        { name: 'fits', valueString: 'Covers this postcode' },
      ],
    },
    {
      name: 'option',
      part: [
        { name: 'serviceId', valueString: 'svc-ward-b' },
        { name: 'name', valueString: 'Ward B' },
        { name: 'status', valueCode: 'accepting' },
        { name: 'criteriaVersion', valueInteger: 3 },
        { name: 'effectiveAvailable', valueInteger: 5 },
        { name: 'unitLabel', valueString: 'beds free' },
        { name: 'travelLow', valueInteger: 25 },
        { name: 'travelHigh', valueInteger: 35 },
        { name: 'travelSource', valueString: 'Routing data, updated 12 Oct' },
        { name: 'dataAgeSeconds', valueInteger: 8100 },
        { name: 'lat', valueDecimal: 50.69 },
        { name: 'lon', valueDecimal: -2.4 },
        leg('Patient to Ward B, by road', 25, 35, 'Typical weekday afternoon. The spread is from traffic.', 'Routing data, updated 12 Oct'),
      ],
    },
    {
      name: 'option',
      part: [
        { name: 'serviceId', valueString: 'svc-hospital-at-home' },
        { name: 'name', valueString: 'Hospital at home' },
        { name: 'status', valueCode: 'accepting' },
        { name: 'criteriaVersion', valueInteger: 3 },
        { name: 'coverageRadiusKm', valueDecimal: 15 },
        { name: 'lat', valueDecimal: 50.71 },
        { name: 'lon', valueDecimal: -2.44 },
        { name: 'dataAgeSeconds', valueInteger: 240 },
      ],
    },
    {
      name: 'option',
      part: [
        { name: 'serviceId', valueString: 'svc-other-unit' },
        { name: 'name', valueString: 'Other unit' },
        { name: 'status', valueCode: 'accepting' },
        { name: 'criteriaVersion', valueInteger: 1 },
        { name: 'effectiveAvailable', valueInteger: 2 },
        { name: 'unitLabel', valueString: 'slots left today' },
        { name: 'lat', valueDecimal: 50.65 },
        { name: 'lon', valueDecimal: -2.5 },
        { name: 'organisation', valueString: 'Neighbouring' },
        { name: 'organisationSource', valueString: 'Entered by the organisation' },
        { name: 'dataAgeSeconds', valueInteger: 60 },
      ],
    },
  ],
};

export const MAP_NOT_FOUND_PARAMETERS = {
  resourceType: 'Parameters',
  parameter: [{ name: 'notFound', valueBoolean: true }, { name: 'outOfArea', valueBoolean: false }],
};

export const MAP_OUT_OF_AREA_PARAMETERS = {
  resourceType: 'Parameters',
  parameter: [{ name: 'notFound', valueBoolean: false }, { name: 'outOfArea', valueBoolean: true }],
};

/** What the BFF answers for the map parameters above (W50): the options view with the map fields. */
const LEG_UCR = {
  label: 'Patient to UCR West, by road',
  low: 35,
  high: 50,
  how: 'Typical weekday afternoon. The spread is from traffic.',
  source: 'Routing data, updated 12 Oct',
};

export const MAP_VIEW = {
  shownAt: '2026-10-30T14:12:00.000Z',
  patientArea: { lat: 50.7, lon: -2.44 },
  notFound: false,
  outOfArea: false,
  options: [
    {
      serviceId: 'svc-ucr-west',
      name: 'UCR West',
      category: 'urgent-community-response',
      status: 'accepting',
      effectiveAvailable: 4,
      overBy: null,
      unitLabel: 'referrals in the next 2 hrs',
      travelText: 'about 35 to 50 min',
      travel: { low: 35, high: 50, source: 'Routing data, updated 12 Oct', legs: [LEG_UCR] },
      dataAgeSeconds: 540,
      staleWarning: false,
      criteriaVersion: 3,
      fits: ['Covers this postcode'],
      checks: [],
      phone: null,
      network: null,
      position: { lat: 50.72, lon: -2.45 },
      coverage: null,
    },
    {
      serviceId: 'svc-ward-b',
      name: 'Ward B',
      category: 'inpatient-beds',
      status: 'accepting',
      effectiveAvailable: 5,
      overBy: null,
      unitLabel: 'beds free',
      travelText: 'about 25 to 35 min',
      travel: {
        low: 25,
        high: 35,
        source: 'Routing data, updated 12 Oct',
        legs: [{ ...LEG_UCR, label: 'Patient to Ward B, by road', low: 25, high: 35 }],
      },
      dataAgeSeconds: 8100,
      staleWarning: true,
      criteriaVersion: 3,
      fits: ['Covers this postcode'],
      checks: [],
      phone: null,
      network: null,
      position: { lat: 50.69, lon: -2.4 },
      coverage: null,
    },
    {
      serviceId: 'svc-hospital-at-home',
      name: 'Hospital at home',
      category: 'hospital-at-home-or-virtual-ward',
      status: 'accepting',
      effectiveAvailable: 3,
      overBy: null,
      unitLabel: 'beds free',
      travelText: null,
      travel: null,
      dataAgeSeconds: 240,
      staleWarning: false,
      criteriaVersion: 3,
      fits: ['Covers this postcode'],
      checks: [],
      phone: null,
      network: null,
      position: null,
      coverage: { lat: 50.71, lon: -2.44, radiusKm: 15 },
    },
    {
      serviceId: 'svc-other-unit',
      name: 'Other unit',
      category: null,
      status: 'accepting',
      effectiveAvailable: 2,
      overBy: null,
      unitLabel: 'slots left today',
      travelText: null,
      travel: null,
      dataAgeSeconds: 60,
      staleWarning: false,
      criteriaVersion: 1,
      fits: [],
      checks: [],
      phone: null,
      network: { organisation: 'Neighbouring', source: 'Entered by the organisation' },
      position: { lat: 50.65, lon: -2.5 },
      coverage: null,
    },
  ],
  notSuitable: [],
};
