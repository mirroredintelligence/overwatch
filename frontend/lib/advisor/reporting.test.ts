import { describe, expect, it } from 'vitest';
import type { OptionView } from './options';
import { cadenceWords, lastReportedLine, reportingStrip } from './reporting';

// The reporting strip and the "Last reported" line (DEC-1343).

function option(over: Partial<OptionView> = {}): OptionView {
  return {
    serviceId: 'svc',
    name: 'Service',
    category: null,
    status: 'accepting',
    effectiveAvailable: 4,
    overBy: null,
    unitLabel: 'beds free',
    travelText: null,
    dataAgeSeconds: 600,
    staleWarning: false,
    reportedAt: '2026-11-06T11:00:00Z',
    nextDueAt: '2026-11-06T13:00:00Z',
    cadence: 'every-2-hrs',
    lastFigure: 3,
    overdue: false,
    figureUnavailable: false,
    criteriaVersion: 1,
    fits: [],
    checks: [],
    phone: null,
    network: null,
    position: null,
    coverage: null,
    travel: null,
    ...over,
  };
}

describe('cadenceWords', () => {
  it('words each cadence and says not known for anything else', () => {
    expect(cadenceWords('every-2-hrs')).toBe('Every 2 hrs');
    expect(cadenceWords('twice-a-day')).toBe('Twice a day');
    expect(cadenceWords('once-a-day')).toBe('Once a day');
    expect(cadenceWords('weekly')).toBe('Not known');
    expect(cadenceWords(null)).toBe('Not known');
  });
});

describe('reportingStrip', () => {
  it('gives last update, frequency, next due and on schedule, in London time', () => {
    expect(reportingStrip(option())).toEqual({
      lastUpdate: '11:00',
      frequency: 'Every 2 hrs',
      nextDue: '13:00',
      schedule: 'On schedule',
      overdue: false,
    });
  });

  it('says Overdue in words when the service is late, and no report yet when none', () => {
    const strip = reportingStrip(option({ overdue: true, reportedAt: null }));
    expect(strip?.schedule).toBe('Overdue');
    expect(strip?.overdue).toBe(true);
    expect(strip?.lastUpdate).toBe('No report yet');
  });

  it('has no strip when nothing about the reporting is known', () => {
    expect(reportingStrip(option({ reportedAt: null, nextDueAt: null, cadence: null }))).toBeNull();
  });
});

describe('lastReportedLine', () => {
  it('shows the last figure and how old it is', () => {
    expect(lastReportedLine(option({ dataAgeSeconds: 3 * 3600 }))).toBe('Last reported: 3 beds free · 3 hrs ago');
  });

  it('says so when there is no figure, and never invents one', () => {
    expect(lastReportedLine(option({ lastFigure: null, dataAgeSeconds: null }))).toBe('No figure reported');
    expect(lastReportedLine(option({ lastFigure: null, dataAgeSeconds: 7200 }))).toBe('No figure. Last report 2 hrs ago');
  });
});
