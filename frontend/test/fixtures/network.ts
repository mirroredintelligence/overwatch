import { NETWORK, TENANT_A_FIXTURE } from '@/test/tenants';

// Sample network bodies, shaped from the back end's own routes (routes_network.py,
// routes_network_views.py, network_board_projector.py). Sample names only. Every body is what the back
// end sends: snake_case, ISO 8601 UTC times, and no tenant, grant or source service id anywhere.

export const NETWORK_NOW = '2026-10-23T13:12:00+00:00';

/** The own organisation's display name is tenant A's: a row of that name is the viewer's own. */
export const OWN_ORGANISATION = TENANT_A_FIXTURE.displayName;
export const OTHER_ORGANISATION = 'Sample Area B';
export const THIRD_ORGANISATION = 'Sample Area D';

export const NETWORKS_BODY = {
  networks: [
    {
      id: NETWORK.id,
      name: NETWORK.displayName,
      system_name: 'Sample capacity',
      pathway_name: 'Sample pathway',
      time_zone: 'Europe/London',
    },
  ],
};

export function boardEntry(overrides: Record<string, unknown> = {}) {
  return {
    row_ref: 'lst-0001',
    organisation_name: OWN_ORGANISATION,
    service_name: 'UCR West',
    category: 'urgent-community-response',
    presentation: 'shown',
    status: 'accepting',
    unit_label: 'beds',
    effective_available: 4,
    over_by: null,
    used: 2,
    established: 6,
    reported_at: '2026-10-23T13:08:00+00:00',
    stale_warning: false,
    was_due_at: null,
    source: 'manual',
    ...overrides,
  };
}

export const BOARD_ENTRIES = [
  boardEntry(),
  boardEntry({
    row_ref: 'lst-0002',
    organisation_name: OTHER_ORGANISATION,
    service_name: 'Virtual ward frailty',
    category: 'hospital-at-home-or-virtual-ward',
    status: 'limited',
    effective_available: 1,
    used: 9,
    established: 10,
  }),
  boardEntry({
    row_ref: 'lst-0003',
    organisation_name: OTHER_ORGANISATION,
    service_name: 'Care packages north',
    category: 'reablement',
    status: 'not-updated',
    unit_label: 'packages',
    effective_available: 3,
    used: 7,
    established: 10,
    reported_at: '2026-10-23T09:02:00+00:00',
    stale_warning: true,
    was_due_at: '2026-10-23T11:00:00+00:00',
  }),
  boardEntry({
    row_ref: 'lst-0004',
    organisation_name: THIRD_ORGANISATION,
    service_name: 'Paused listing',
    category: 'inpatient-beds',
    presentation: 'unavailable',
    status: null,
    unit_label: null,
    effective_available: null,
    used: null,
    established: null,
    reported_at: null,
  }),
];

export const BOARD_BODY = {
  entries: BOARD_ENTRIES,
  pressure: 'normal',
  all_limited_or_worse: false,
  generated_at: NETWORK_NOW,
  system_name: 'Sample capacity',
  pathway_name: 'Sample pathway',
  time_zone: 'Europe/London',
};

export function directoryEntry(overrides: Record<string, unknown> = {}) {
  return {
    row_ref: 'lst-0001',
    organisation_name: OWN_ORGANISATION,
    service_name: 'UCR West',
    category: 'urgent-community-response',
    active: true,
    source: 'manual',
    contact_label: 'Service line',
    contact_phone: '01632 960010',
    location: { location_name: 'West hub', postal_district: 'DT4', city: 'Sampletown', latitude: 50.6, longitude: -2.45 },
    opening_hours: [{ position: 0, days: ['mon', 'tue', 'wed', 'thu', 'fri'], all_day: false, start: '08:00', end: '20:00' }],
    presentation: 'shown',
    ended_at: null,
    end_reason: null,
    ...overrides,
  };
}

export const DIRECTORY_BODY = {
  entries: [
    directoryEntry(),
    directoryEntry({
      row_ref: 'lst-0002',
      organisation_name: OTHER_ORGANISATION,
      service_name: 'Virtual ward frailty',
      category: 'hospital-at-home-or-virtual-ward',
      contact_label: null,
      contact_phone: null,
      location: null,
      opening_hours: [{ position: 0, days: ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'], all_day: true, start: null, end: null }],
    }),
  ],
  system_name: 'Sample capacity',
  pathway_name: 'Sample pathway',
  time_zone: 'Europe/London',
};

/** What a departed member shared, as `?history=true` answers it. */
export const DIRECTORY_HISTORY_BODY = {
  entries: [
    directoryEntry({
      row_ref: 'lst-0090',
      organisation_name: THIRD_ORGANISATION,
      service_name: 'Former service',
      ended_at: '2026-10-01T09:00:00+00:00',
      end_reason: 'left',
    }),
    directoryEntry({
      row_ref: 'lst-0091',
      organisation_name: OTHER_ORGANISATION,
      service_name: 'Stopped service',
      ended_at: '2026-10-05T09:00:00+00:00',
      end_reason: 'grant-ended',
    }),
  ],
  system_name: 'Sample capacity',
  pathway_name: 'Sample pathway',
  time_zone: 'Europe/London',
};

export const CRITERIA_BODY = {
  entries: [
    {
      row_ref: 'lst-0001',
      organisation_name: OWN_ORGANISATION,
      service_name: 'UCR West',
      version: 3,
      age_min: 18,
      age_max: 120,
      districts: ['DT4', 'DT5'],
      accepts: ['frailty', 'wound-care'],
      excludes: ['dementia'],
      review_by: '2027-01-15',
      ended_at: null,
      end_reason: null,
    },
  ],
  system_name: 'Sample capacity',
  pathway_name: 'Sample pathway',
  time_zone: 'Europe/London',
};

export const SYSTEM_NOW_BODY = {
  generated_at: NETWORK_NOW,
  services: 4,
  organisations: 3,
  by_status: {
    accepting: 1,
    limited: 1,
    'not-accepting': 0,
    'over-capacity': 0,
    'not-updated': 1,
    'out-of-hours': 0,
    unavailable: 1,
  },
  pressure: 'normal',
  all_limited_or_worse: false,
  alert: { raised: false, level: 'normal', limited_or_worse: 1, watch_from: 3, high_from: 5 },
  system_name: 'Sample capacity',
  pathway_name: 'Sample pathway',
  time_zone: 'Europe/London',
};

export const PHONES_BODY = {
  phones: [
    {
      row_ref: 'lst-0001',
      organisation_name: OWN_ORGANISATION,
      service_name: 'UCR West',
      category: 'urgent-community-response',
      presentation: 'shown',
      status: 'accepting',
      stale_warning: false,
      reported_at: '2026-10-23T13:08:00+00:00',
      contact_label: 'Service line',
      contact_phone: '01632 960010',
    },
    {
      row_ref: 'lst-0003',
      organisation_name: OTHER_ORGANISATION,
      service_name: 'Care packages north',
      category: 'reablement',
      presentation: 'shown',
      status: 'not-updated',
      stale_warning: true,
      reported_at: '2026-10-23T09:02:00+00:00',
      contact_label: null,
      contact_phone: null,
    },
    {
      row_ref: 'lst-0004',
      organisation_name: THIRD_ORGANISATION,
      service_name: 'Paused listing',
      category: 'inpatient-beds',
      presentation: 'unavailable',
      status: null,
      stale_warning: false,
      reported_at: null,
      contact_label: null,
      contact_phone: null,
    },
  ],
  organisations: 3,
  system_name: 'Sample capacity',
  pathway_name: 'Sample pathway',
  time_zone: 'Europe/London',
};

function measure(label: string, value: number | null) {
  return { label, value, hidden: value === null };
}

export const WEEK_BODY = {
  week_start: '2026-10-19',
  withheld: false,
  hours_sampled: measure('hours sampled', 134),
  on_time_pct: measure('capacity updates on time', 75),
  status_share: {
    accepting: measure('accepting', 48),
    limited: measure('limited', 20),
    'not-accepting': measure('not accepting', 5),
    'over-capacity': measure('over capacity', null),
    'not-updated': measure('not updated', 22),
    'out-of-hours': measure('out of hours', 5),
  },
  pressure_hours: { normal: measure('normal', 100), watch: measure('watch', 30), high: measure('high', null) },
  pressure_over_time: [
    { hour: '2026-10-19T00:00:00+00:00', pressure: 'normal' },
    { hour: '2026-10-19T01:00:00+00:00', pressure: 'watch' },
  ],
  system_name: 'Sample capacity',
  pathway_name: 'Sample pathway',
  time_zone: 'Europe/London',
};

export const WEEK_WITHHELD_BODY = {
  ...WEEK_BODY,
  withheld: true,
  hours_sampled: measure('hours sampled', null),
  on_time_pct: measure('capacity updates on time', null),
  pressure_over_time: [],
};
