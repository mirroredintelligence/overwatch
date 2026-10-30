// Sample options for the advisor screens (W13). Sample data only: service names are the sample
// board's (docs/design/ui-screens "Advisor" artboard), and the reasons are plain test text.
// The Parameters below are the shape `$filter-options` answers (routes_cases.py `_option_to_part`),
// with the parts the prompt needs and the back end does not send yet written as they would be.

type Part = { name: string; valueString?: string; valueCode?: string; valueInteger?: number; part?: Part[] };

const parts = (...items: Part[]) => items;

function option(values: {
  serviceId: string;
  name: string;
  status: string;
  effectiveAvailable?: number;
  overBy?: number;
  category?: string;
  unitLabel?: string;
  travelLow?: number;
  travelHigh?: number;
  dataAgeSeconds?: number;
  fits: string[];
  checks: string[];
}): Part {
  const list: Part[] = [
    { name: 'serviceId', valueString: values.serviceId },
    { name: 'name', valueString: values.name },
    { name: 'status', valueCode: values.status },
    { name: 'criteriaVersion', valueInteger: 3 },
  ];
  if (values.category !== undefined) list.push({ name: 'category', valueCode: values.category });
  if (values.effectiveAvailable !== undefined) list.push({ name: 'effectiveAvailable', valueInteger: values.effectiveAvailable });
  if (values.overBy !== undefined) list.push({ name: 'overBy', valueInteger: values.overBy });
  if (values.unitLabel !== undefined) list.push({ name: 'unitLabel', valueString: values.unitLabel });
  if (values.travelLow !== undefined) list.push({ name: 'travelLow', valueInteger: values.travelLow });
  if (values.travelHigh !== undefined) list.push({ name: 'travelHigh', valueInteger: values.travelHigh });
  if (values.dataAgeSeconds !== undefined) list.push({ name: 'dataAgeSeconds', valueInteger: values.dataAgeSeconds });
  list.push(...values.fits.map((fit) => ({ name: 'fits', valueString: fit })));
  list.push(...values.checks.map((check) => ({ name: 'checks', valueString: check })));
  return { name: 'option', part: list };
}

function notSuitable(serviceId: string, name: string, reason: string): Part {
  return {
    name: 'notSuitable',
    part: [
      { name: 'serviceId', valueString: serviceId },
      { name: 'name', valueString: name },
      { name: 'reason', valueString: reason },
    ],
  };
}

/** The three options of the "Advisor" artboard, in the order the back end sends them. */
export const OPTIONS_PARAMETERS = {
  resourceType: 'Parameters',
  parameter: parts(
    option({
      serviceId: 'svc-ucr-west',
      name: 'UCR West',
      status: 'accepting',
      category: 'urgent-community-response',
      effectiveAvailable: 4,
      unitLabel: 'referrals in the next 2 hrs',
      travelLow: 35,
      travelHigh: 50,
      dataAgeSeconds: 540,
      fits: ['Covers this postcode', 'Falls without injury', 'Frailty'],
      checks: ['Visits after 18:00 need phone confirmation'],
    }),
    option({
      serviceId: 'svc-ward-b',
      name: 'Community hospital · Ward B',
      status: 'accepting',
      category: 'inpatient-beds',
      effectiveAvailable: 5,
      unitLabel: 'beds free',
      travelLow: 25,
      travelHigh: 35,
      dataAgeSeconds: 8100,
      fits: ['Covers this postcode'],
      checks: [],
    }),
    option({
      serviceId: 'svc-hospital-at-home',
      name: 'Hospital at home',
      status: 'over-capacity',
      category: 'hospital-at-home-or-virtual-ward',
      overBy: 2,
      unitLabel: 'over established capacity',
      dataAgeSeconds: 240,
      fits: ['Covers this postcode'],
      checks: ['Confirm by phone before offering'],
    }),
    notSuitable('svc-sdec-2', 'SDEC · Site 2', 'not accepting since 13:30'),
    notSuitable('svc-virtual-ward', 'Virtual ward · frailty', 'not updated since 09:02'),
    notSuitable('svc-reablement', 'Reablement', 'outside the criteria for this district'),
  ),
};

/** What the BFF answers for the three options above. Its shape is the options view (W13). */
export const OPTIONS_VIEW = {
  shownAt: '2026-10-30T14:12:00.000Z',
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
      dataAgeSeconds: 540,
      staleWarning: false,
      criteriaVersion: 3,
      fits: ['Covers this postcode', 'Falls without injury', 'Frailty'],
      checks: ['Visits after 18:00 need phone confirmation'],
      phone: null,
      network: null,
    },
    {
      serviceId: 'svc-ward-b',
      name: 'Community hospital · Ward B',
      category: 'inpatient-beds',
      status: 'accepting',
      effectiveAvailable: 5,
      overBy: null,
      unitLabel: 'beds free',
      travelText: 'about 25 to 35 min',
      dataAgeSeconds: 8100,
      staleWarning: true,
      criteriaVersion: 3,
      fits: ['Covers this postcode'],
      checks: [],
      phone: null,
      network: null,
    },
    {
      serviceId: 'svc-hospital-at-home',
      name: 'Hospital at home',
      category: 'hospital-at-home-or-virtual-ward',
      status: 'over-capacity',
      effectiveAvailable: null,
      overBy: 2,
      unitLabel: 'over established capacity',
      travelText: null,
      dataAgeSeconds: 240,
      staleWarning: false,
      criteriaVersion: 3,
      fits: ['Covers this postcode'],
      checks: ['Confirm by phone before offering'],
      phone: null,
      network: null,
    },
  ],
  notSuitable: [
    { serviceId: 'svc-sdec-2', name: 'SDEC · Site 2', reason: 'not accepting since 13:30' },
    { serviceId: 'svc-virtual-ward', name: 'Virtual ward · frailty', reason: 'not updated since 09:02' },
    { serviceId: 'svc-reablement', name: 'Reablement', reason: 'outside the criteria for this district' },
  ],
};

/** No service fits: the answer when every service is excluded (W16). */
export const OPTIONS_EMPTY_VIEW = { shownAt: OPTIONS_VIEW.shownAt, options: [], notSuitable: OPTIONS_VIEW.notSuitable };
