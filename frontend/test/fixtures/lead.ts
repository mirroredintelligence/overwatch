// Sample shift-lead data for the tests (sample services only, no patient information).
// Times are GMT on Friday 30 October 2026, after the clocks went back, so London local time
// equals UTC and "12:00" in a test is 12:00Z.

import type { LeadOverview } from '@/lib/lead/types';

export const SERVICE_VIRTUAL_WARD = 's-virtual-ward';
export const SERVICE_UCR_EAST = 's-ucr-east';
export const SERVICE_REABLEMENT = 's-reablement';
export const SERVICE_OLD_FIGURE = 's-old-figure';

/** The "ShiftLead" artboard: two services need chasing, one figure is getting old. */
export const OVERVIEW_SHIFT_LEAD: LeadOverview = {
  chasing: [
    {
      serviceId: SERVICE_VIRTUAL_WARD,
      name: 'Virtual ward',
      dueAt: '2026-10-30T12:00:00Z',
      overdueMinutes: 132,
      lastValueText: '3 beds free',
      ladder: [
        { step: 'prompt', at: '2026-10-30T12:00:00Z', done: true },
        { step: 'reminder', at: '2026-10-30T12:30:00Z', done: true },
        { step: 'phone-task', at: '2026-10-30T13:00:00Z', done: false },
        { step: 'escalate', at: '2026-10-30T13:30:00Z', done: false },
      ],
    },
    {
      serviceId: SERVICE_UCR_EAST,
      name: 'UCR East',
      dueAt: '2026-10-30T13:00:00Z',
      overdueMinutes: 50,
      lastValueText: '0 referrals',
      ladder: [
        { step: 'prompt', at: '2026-10-30T13:00:00Z', done: true },
        { step: 'reminder', at: '2026-10-30T13:30:00Z', done: false },
        { step: 'phone-task', at: '2026-10-30T14:00:00Z', done: false },
        { step: 'escalate', at: '2026-10-30T14:30:00Z', done: false },
      ],
    },
  ],
  gettingOld: [
    {
      serviceId: SERVICE_OLD_FIGURE,
      name: 'Reablement',
      reportedAt: '2026-10-30T14:50:00Z',
      nextDueAt: '2026-10-30T17:00:00Z',
      status: 'limited',
    },
  ],
  covering: [
    { serviceId: SERVICE_UCR_EAST, name: 'UCR East', numberEnding: '4821', until: '2026-10-30T20:00:00Z' },
    { serviceId: SERVICE_REABLEMENT, name: 'Reablement', numberEnding: '0377', until: null },
  ],
  counts: { accepting: 4, limited: 2, notAccepting: 1, overCapacity: 1, notUpdated: 1 },
  reportingToday: 9,
};

export const OVERVIEW_NOTHING_TO_CHASE: LeadOverview = {
  ...OVERVIEW_SHIFT_LEAD,
  chasing: [],
  gettingOld: [],
};
