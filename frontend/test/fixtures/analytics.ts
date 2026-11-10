import type { AnalyticsOverview } from '@/lib/analytics/types';

// The Analytics User's overview as the BFF gives it (DEC-1368): figures only, no case, no postcode of a patient.
// Five services: one is in two districts, one has no district (it must show under "Not placed"), one has an old
// figure (no number, never spare capacity).

export const ANALYTICS_OVERVIEW: AnalyticsOverview = {
  generatedAt: '2026-11-10T14:00:00Z',
  counts: { accepting: 1, limited: 1, notAccepting: 1, overCapacity: 1, notUpdated: 1 },
  outOfHours: 0,
  services: [
    {
      serviceId: 'svc-poole',
      name: 'Poole UTC',
      category: 'urgent-treatment',
      status: 'accepting',
      districts: ['BH15'],
      figureCurrent: true,
      available: 8,
      overBy: null,
      unitLabel: 'appointment slots',
      reportedAt: '2026-11-10T13:30:00Z',
    },
    {
      serviceId: 'svc-sdec',
      name: 'Bournemouth SDEC',
      category: 'same-day-emergency-care',
      status: 'limited',
      districts: ['BH15', 'BH7'],
      figureCurrent: true,
      available: 1,
      overBy: null,
      unitLabel: 'appointment slots',
      reportedAt: '2026-11-10T13:45:00Z',
    },
    {
      serviceId: 'svc-ward',
      name: 'Ward Z',
      category: 'inpatient-beds',
      status: 'over-capacity',
      districts: ['BH7'],
      figureCurrent: true,
      available: null,
      overBy: 2,
      unitLabel: 'beds',
      reportedAt: '2026-11-10T13:50:00Z',
    },
    {
      serviceId: 'svc-hah',
      name: 'Hospital at home',
      category: 'hospital-at-home-or-virtual-ward',
      status: 'not-updated',
      districts: [],
      figureCurrent: false,
      available: null,
      overBy: null,
      unitLabel: 'virtual beds',
      reportedAt: '2026-11-09T08:00:00Z',
    },
    {
      serviceId: 'svc-reab',
      name: 'Wimborne reablement',
      category: 'reablement',
      status: 'not-accepting',
      districts: ['BH21'],
      figureCurrent: true,
      available: 0,
      overBy: null,
      unitLabel: 'care packages',
      reportedAt: '2026-11-10T12:00:00Z',
    },
  ],
  underPressure: [
    { serviceId: 'svc-hah', name: 'Hospital at home', status: 'not-updated', reason: 'Figure is old. Confirm before redirecting demand.', usedPercent: null },
    { serviceId: 'svc-ward', name: 'Ward Z', status: 'over-capacity', reason: '2 over normal capacity', usedPercent: 120 },
  ],
  underutilised: [{ serviceId: 'svc-poole', name: 'Poole UTC', usedPercent: 20, spare: 8, unitLabel: 'appointment slots' }],
};

/** The back end's answer for it (the same shape: the BFF checks it and passes it on). */
export const ANALYTICS_BACKEND_ANSWER = ANALYTICS_OVERVIEW;
