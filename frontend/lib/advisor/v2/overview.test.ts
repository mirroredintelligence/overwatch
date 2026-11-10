import { describe, expect, it } from 'vitest';
import { attentionShown, parseOverview, statusHref, V2_BROWSE_NOTE } from './overview';

// Advisor v2: the capacity overview (DEC-1366). The counts link to filtered lists; the Needs attention lists are
// the shift lead's rules; a stale figure is never spare capacity and is never shown as a number.

const BODY = {
  generatedAt: '2026-11-10T14:00:00Z',
  counts: { accepting: 3, limited: 2, notAccepting: 1, overCapacity: 1, notUpdated: 2 },
  attentionShown: 3,
  underPressure: [
    { serviceId: 'a', name: 'A', status: 'over-capacity', reason: '2 over normal capacity', usedPercent: 120 },
    { serviceId: 'b', name: 'B', status: 'limited', reason: 'Figure is old. Confirm before redirecting demand.', usedPercent: null },
  ],
  underutilised: [{ serviceId: 'c', name: 'C', usedPercent: 20, spare: 8, unitLabel: 'beds free' }],
  services: [
    {
      serviceId: 'a',
      name: 'A',
      category: 'inpatient-beds',
      status: 'accepting',
      effectiveAvailable: 4,
      overBy: null,
      unitLabel: 'beds free',
      reportedAt: '2026-11-10T13:50:00Z',
      figureUnavailable: false,
      lastFigure: 4,
    },
  ],
};

describe('parseOverview', () => {
  it('reads the counts, the two lists and the rows', () => {
    const view = parseOverview(BODY);
    expect(view?.counts).toEqual({ accepting: 3, limited: 2, 'not-accepting': 1, 'over-capacity': 1, 'not-updated': 2 });
    expect(view?.underPressure).toHaveLength(2);
    expect(view?.underutilised[0]).toMatchObject({ serviceId: 'c', spare: 8 });
    expect(view?.services).toHaveLength(1);
  });

  it('is null when the answer is not shaped like an overview', () => {
    expect(parseOverview(null)).toBeNull();
    expect(parseOverview({ ...BODY, counts: undefined })).toBeNull();
  });

  it('shows no percentage for a stale figure under pressure', () => {
    expect(parseOverview(BODY)?.underPressure[1]?.usedPercent).toBeNull();
  });

  it('drops a row it cannot read and reads an unknown status as not updated', () => {
    const view = parseOverview({
      ...BODY,
      services: [{ ...BODY.services[0], serviceId: 1 }, { ...BODY.services[0], status: 'wide-open' }],
    });
    expect(view?.services).toHaveLength(1);
    expect(view?.services[0]?.status).toBe('not-updated');
    expect(view?.services[0]?.figureUnavailable).toBe(true);
  });
});

describe('statusHref', () => {
  it('links a count to the filtered list of v2, not the v1 list', () => {
    expect(statusHref('limited')).toBe('/advisor/v2/services?status=limited');
  });
});

describe('attentionShown', () => {
  it('shows the first few and counts the rest', () => {
    expect(attentionShown([1, 2, 3, 4, 5], 3)).toEqual({ shown: [1, 2, 3], more: 2 });
    expect(attentionShown([1], 3)).toEqual({ shown: [1], more: 0 });
  });
});

describe('V2_BROWSE_NOTE', () => {
  it('says plainly that nothing is stored', () => {
    expect(V2_BROWSE_NOTE).toMatch(/no case/i);
    expect(V2_BROWSE_NOTE).toMatch(/nothing is stored/i);
  });
});
