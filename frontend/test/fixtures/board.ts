import type { Parameters, ParametersParameter } from '@/lib/fhir/types';
import type { Board, BoardEntry } from '@/lib/board/types';

// Sample boards for the tests. The nine services are the "Main" artboard in
// docs/spec/ui-screens.md (sample data only). The clock is Friday 23 October
// at 14:12 London time, which is 13:12 UTC (British Summer Time).

export const GENERATED_AT = '2026-10-23T13:12:00Z';
export const NOW = new Date(GENERATED_AT);

export function entry(overrides: Partial<BoardEntry> & { serviceId: string; name: string }): BoardEntry {
  return {
    category: 'urgent-community-response',
    status: 'accepting',
    effectiveAvailable: 4,
    overBy: null,
    used: 4,
    established: 8,
    pending: 0,
    unitLabel: 'referrals in the next 2 hrs',
    comment: null,
    reportedAt: '2026-10-23T13:03:00Z',
    nextDueAt: '2026-10-23T13:30:00Z',
    wasDueAt: null,
    ...overrides,
  };
}

export const UCR_WEST = entry({
  serviceId: 'svc-ucr-west',
  name: 'UCR West',
  comment: 'Response time about 1 hr 20',
});

export const VIRTUAL_WARD = entry({
  serviceId: 'svc-virtual-ward',
  name: 'Virtual ward · frailty',
  category: 'hospital-at-home-or-virtual-ward',
  status: 'not-updated',
  effectiveAvailable: 3,
  used: 7,
  established: 10,
  unitLabel: 'beds free',
  comment: 'Last reported 3 beds free',
  reportedAt: '2026-10-23T09:02:00Z',
  nextDueAt: '2026-10-23T15:00:00Z',
  wasDueAt: '2026-10-23T11:00:00Z',
});

export const MAIN_ENTRIES: BoardEntry[] = [
  UCR_WEST,
  entry({
    serviceId: 'svc-ucr-east',
    name: 'UCR East',
    status: 'limited',
    effectiveAvailable: 1,
    used: 7,
    unitLabel: 'referral in the next 2 hrs',
    comment: 'Response time about 2 hrs',
    reportedAt: '2026-10-23T12:41:00Z',
  }),
  entry({
    serviceId: 'svc-sdec-1',
    name: 'SDEC · Site 1',
    category: 'same-day-emergency-care',
    effectiveAvailable: 6,
    used: 4,
    established: 10,
    unitLabel: 'slots left today',
    comment: 'Referral cut-off 17:00',
    reportedAt: '2026-10-23T12:07:00Z',
    nextDueAt: '2026-10-23T15:00:00Z',
  }),
  entry({
    serviceId: 'svc-sdec-2',
    name: 'SDEC · Site 2',
    category: 'same-day-emergency-care',
    status: 'not-accepting',
    effectiveAvailable: 0,
    used: 8,
    unitLabel: 'slots left today',
    comment: 'Closed to referrals since 13:30',
    reportedAt: '2026-10-23T12:34:00Z',
    nextDueAt: '2026-10-23T15:00:00Z',
  }),
  entry({
    serviceId: 'svc-ward-a',
    name: 'Community hospital · Ward A',
    category: 'inpatient-beds',
    status: 'limited',
    effectiveAvailable: 2,
    used: 10,
    established: 12,
    unitLabel: 'beds free',
    comment: 'Both women only · no side room',
    reportedAt: '2026-10-23T11:02:00Z',
    nextDueAt: '2026-10-23T16:00:00Z',
  }),
  entry({
    serviceId: 'svc-ward-b',
    name: 'Community hospital · Ward B',
    category: 'inpatient-beds',
    effectiveAvailable: 5,
    used: 7,
    established: 12,
    unitLabel: 'beds free',
    comment: 'Rehab · 1 side room',
    reportedAt: '2026-10-23T11:02:00Z',
    nextDueAt: '2026-10-23T16:00:00Z',
  }),
  entry({
    serviceId: 'svc-hospital-at-home',
    name: 'Hospital at home',
    category: 'hospital-at-home-or-virtual-ward',
    status: 'over-capacity',
    effectiveAvailable: null,
    overBy: 2,
    used: 14,
    established: 12,
    unitLabel: 'over established capacity',
    comment: 'Escalation in place',
    reportedAt: '2026-10-23T12:58:00Z',
    nextDueAt: '2026-10-23T15:00:00Z',
  }),
  VIRTUAL_WARD,
  entry({
    serviceId: 'svc-reablement',
    name: 'Reablement',
    category: 'reablement',
    effectiveAvailable: 3,
    used: 7,
    established: 10,
    unitLabel: 'packages today',
    comment: 'Postcode catchment applies',
    reportedAt: '2026-10-23T10:12:00Z',
    nextDueAt: '2026-10-24T08:00:00Z',
  }),
];

export const ORGANISATION_A = 'Dorset';
export const ORGANISATION_B = 'Neighbouring';

export const BOARD_A: Board = {
  entries: MAIN_ENTRIES,
  pressure: 'normal',
  allLimitedOrWorse: false,
  generatedAt: GENERATED_AT,
  organisation: ORGANISATION_A,
};

// A second organisation's board. Its names and ids must never appear on a
// screen that was paired to organisation A.
export const BOARD_B: Board = {
  entries: [
    entry({
      serviceId: 'svc-other-unit',
      name: 'Other unit',
      effectiveAvailable: 2,
      used: 6,
      unitLabel: 'slots left today',
    }),
  ],
  pressure: 'normal',
  allLimitedOrWorse: false,
  generatedAt: GENERATED_AT,
  organisation: ORGANISATION_B,
};

// The "TileStates" artboard (docs/spec/ui-screens.md): the same service in step 1
// (a request is pending: available stays at 4) and in step 2 (confirmed by text:
// available drops to 3, pending clears).
export const PENDING_TILE = entry({
  serviceId: 'svc-ucr-west',
  name: 'UCR West',
  pending: 1,
  comment: null,
});

export const CONFIRMED_TILE = entry({
  serviceId: 'svc-ucr-west',
  name: 'UCR West',
  effectiveAvailable: 3,
  used: 5,
  pending: 0,
  comment: 'Response time about 1 hr 20',
  reportedAt: '2026-10-23T13:03:00Z',
  nextDueAt: '2026-10-23T13:30:00Z',
});

// The "BoardSurge" artboard: Friday 23 October 14:12 London time, every service
// limited or worse, so the "System under pressure" banner shows.
export const SURGE_ENTRIES: BoardEntry[] = [
  entry({
    serviceId: 'svc-ucr-west',
    name: 'UCR West',
    status: 'limited',
    effectiveAvailable: 1,
    used: 7,
    pending: 1,
    unitLabel: 'referral in the next 2 hrs',
    comment: 'Response time about 2 hrs 30',
    reportedAt: '2026-10-23T13:06:00Z',
  }),
  entry({
    serviceId: 'svc-ucr-east',
    name: 'UCR East',
    status: 'not-accepting',
    effectiveAvailable: 0,
    used: 8,
    comment: 'Not accepting since 13:10',
    reportedAt: '2026-10-23T12:50:00Z',
  }),
  entry({
    serviceId: 'svc-sdec-1',
    name: 'SDEC · Site 1',
    category: 'same-day-emergency-care',
    status: 'limited',
    effectiveAvailable: 1,
    used: 9,
    established: 10,
    unitLabel: 'slot left today',
    comment: 'Referral cut-off 17:00',
    reportedAt: '2026-10-23T12:54:00Z',
    nextDueAt: '2026-10-23T14:00:00Z',
  }),
  entry({
    serviceId: 'svc-sdec-2',
    name: 'SDEC · Site 2',
    category: 'same-day-emergency-care',
    status: 'not-accepting',
    effectiveAvailable: 0,
    used: 8,
    unitLabel: 'slots left today',
    comment: 'Not accepting since 12:50',
    reportedAt: '2026-10-23T12:47:00Z',
    nextDueAt: '2026-10-23T14:00:00Z',
  }),
  entry({
    serviceId: 'svc-ward-a',
    name: 'Community hospital · Ward A',
    category: 'inpatient-beds',
    status: 'not-accepting',
    effectiveAvailable: 0,
    used: 12,
    established: 12,
    unitLabel: 'beds free',
    comment: 'Full',
    reportedAt: '2026-10-23T12:02:00Z',
    nextDueAt: '2026-10-23T16:00:00Z',
  }),
  entry({
    serviceId: 'svc-ward-b',
    name: 'Community hospital · Ward B',
    category: 'inpatient-beds',
    status: 'limited',
    effectiveAvailable: 1,
    used: 11,
    established: 12,
    unitLabel: 'bed free',
    comment: 'Male · no side room',
    reportedAt: '2026-10-23T12:02:00Z',
    nextDueAt: '2026-10-23T16:00:00Z',
  }),
  entry({
    serviceId: 'svc-hospital-at-home',
    name: 'Hospital at home',
    category: 'hospital-at-home-or-virtual-ward',
    status: 'over-capacity',
    effectiveAvailable: null,
    overBy: 4,
    used: 16,
    established: 12,
    pending: 1,
    unitLabel: 'over established capacity',
    comment: 'Escalation in place',
    reportedAt: '2026-10-23T13:01:00Z',
    nextDueAt: '2026-10-23T14:00:00Z',
  }),
  entry({
    serviceId: 'svc-virtual-ward',
    name: 'Virtual ward · frailty',
    category: 'hospital-at-home-or-virtual-ward',
    status: 'over-capacity',
    effectiveAvailable: null,
    overBy: 1,
    used: 11,
    established: 10,
    unitLabel: 'over established capacity',
    comment: 'Escalation in place',
    reportedAt: '2026-10-23T12:32:00Z',
    nextDueAt: '2026-10-23T14:00:00Z',
  }),
  entry({
    serviceId: 'svc-reablement',
    name: 'Reablement',
    category: 'reablement',
    status: 'limited',
    effectiveAvailable: 1,
    used: 9,
    established: 10,
    unitLabel: 'package today',
    comment: 'Postcode catchment applies',
    reportedAt: '2026-10-23T11:12:00Z',
    nextDueAt: '2026-10-24T08:00:00Z',
  }),
];

export const BOARD_SURGE: Board = {
  entries: SURGE_ENTRIES,
  pressure: 'high',
  allLimitedOrWorse: true,
  generatedAt: GENERATED_AT,
  organisation: ORGANISATION_A,
};

// The "BoardQuiet" artboard: Saturday 24 October 02:40 London time (01:40 UTC, still
// British Summer Time). Six services are out of hours and reopen at 08:00; three are
// open, so there is no pressure banner.
export const QUIET_AT = '2026-10-24T01:40:00Z';

function outOfHours(serviceId: string, name: string, category: string, unitLabel: string): BoardEntry {
  return entry({
    serviceId,
    name,
    category,
    status: 'out-of-hours',
    effectiveAvailable: null,
    used: null,
    unitLabel,
    comment: null,
    reportedAt: '2026-10-23T19:02:00Z',
    nextDueAt: '2026-10-24T07:00:00Z',
  });
}

export const QUIET_ENTRIES: BoardEntry[] = [
  outOfHours('svc-ucr-west', 'UCR West', 'urgent-community-response', 'referrals in the next 2 hrs'),
  outOfHours('svc-ucr-east', 'UCR East', 'urgent-community-response', 'referrals in the next 2 hrs'),
  outOfHours('svc-sdec-1', 'SDEC · Site 1', 'same-day-emergency-care', 'slots left today'),
  outOfHours('svc-sdec-2', 'SDEC · Site 2', 'same-day-emergency-care', 'slots left today'),
  entry({
    serviceId: 'svc-ward-a',
    name: 'Community hospital · Ward A',
    category: 'inpatient-beds',
    effectiveAvailable: 3,
    used: 9,
    established: 12,
    unitLabel: 'beds free',
    comment: 'Women only · 1 side room',
    reportedAt: '2026-10-24T00:20:00Z',
    nextDueAt: '2026-10-24T05:00:00Z',
  }),
  entry({
    serviceId: 'svc-ward-b',
    name: 'Community hospital · Ward B',
    category: 'inpatient-beds',
    status: 'limited',
    effectiveAvailable: 1,
    used: 11,
    established: 12,
    unitLabel: 'bed free',
    comment: 'Male · no side room',
    reportedAt: '2026-10-24T00:20:00Z',
    nextDueAt: '2026-10-24T05:00:00Z',
  }),
  entry({
    serviceId: 'svc-hospital-at-home',
    name: 'Hospital at home',
    category: 'hospital-at-home-or-virtual-ward',
    effectiveAvailable: 2,
    used: 8,
    established: 10,
    unitLabel: 'virtual beds free',
    comment: 'Admissions until 06:00',
    reportedAt: '2026-10-24T00:58:00Z',
    nextDueAt: '2026-10-24T05:00:00Z',
  }),
  outOfHours('svc-virtual-ward', 'Virtual ward · frailty', 'hospital-at-home-or-virtual-ward', 'virtual beds free'),
  outOfHours('svc-reablement', 'Reablement', 'reablement', 'packages today'),
];

export const BOARD_QUIET: Board = {
  entries: QUIET_ENTRIES,
  pressure: 'normal',
  allLimitedOrWorse: false,
  generatedAt: QUIET_AT,
  organisation: ORGANISATION_A,
};

function integer(name: string, value: number | null): ParametersParameter[] {
  return value === null ? [] : [{ name, valueInteger: value }];
}

function dateTime(name: string, value: string | null): ParametersParameter[] {
  return value === null ? [] : [{ name, valueDateTime: value }];
}

/** An `entry` parameter as the back end writes it: a null part, and an empty comment, are left out. */
export function entryParameter(e: BoardEntry): ParametersParameter {
  return {
    name: 'entry',
    part: [
      { name: 'serviceId', valueString: e.serviceId },
      { name: 'name', valueString: e.name },
      { name: 'category', valueCode: e.category },
      { name: 'status', valueCode: e.status },
      ...integer('effectiveAvailable', e.effectiveAvailable),
      ...integer('overBy', e.overBy),
      ...integer('used', e.used),
      { name: 'established', valueInteger: e.established },
      { name: 'pending', valueInteger: e.pending },
      { name: 'unitLabel', valueString: e.unitLabel },
      ...(e.comment ? [{ name: 'comment', valueString: e.comment }] : []),
      ...dateTime('reportedAt', e.reportedAt),
      ...dateTime('nextDueAt', e.nextDueAt),
      ...dateTime('wasDueAt', e.wasDueAt),
    ],
  };
}

export function boardParameters(board: Board): Parameters {
  return {
    resourceType: 'Parameters',
    parameter: [
      ...board.entries.map(entryParameter),
      { name: 'pressure', valueCode: board.pressure },
      { name: 'allLimitedOrWorse', valueBoolean: board.allLimitedOrWorse },
      { name: 'generatedAt', valueDateTime: board.generatedAt },
      ...(board.organisation === null
        ? []
        : [{ name: 'organisation', valueString: board.organisation }]),
    ],
  };
}

/** The same board, built at another instant: every time in it moves by the same amount (W06). */
export function boardBuiltAt(board: Board, generatedAt: string): Board {
  const delta = Date.parse(generatedAt) - Date.parse(board.generatedAt);
  const shift = (value: string | null) => (value === null ? null : new Date(Date.parse(value) + delta).toISOString());
  return {
    ...board,
    generatedAt,
    entries: board.entries.map((e) => ({
      ...e,
      reportedAt: shift(e.reportedAt),
      nextDueAt: shift(e.nextDueAt),
      wasDueAt: shift(e.wasDueAt),
    })),
  };
}

/**
 * A payload that names another organisation on its first entry, which the back end
 * must never send on a tenant's board. The wall must refuse it (W07, DEC-169 item 8).
 */
export function withForeignOrganisation(parameters: Parameters, name: string = ORGANISATION_B): Parameters {
  const copy = structuredClone(parameters);
  const first = copy.parameter?.find((p) => p.name === 'entry');
  if (first?.part) first.part.push({ name: 'organisation', valueString: name });
  return copy;
}
