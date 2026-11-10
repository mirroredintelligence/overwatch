import { describe, expect, it } from 'vitest';
import { parseAdvisorUrl, parseOverviewUrl, workspaceHref } from './url';

// URL state for the workspace (WS-URL). The URL holds only where the person is, never who the
// patient is: age, postcode, need and when must never be read or emitted (WS-PRIV).

const ADVISOR_INTENTS = [
  'advisor.intake.age',
  'advisor.intake.need',
  'advisor.results',
  'advisor.map',
  'advisor.reasons',
  'advisor.new-search',
];

const OVERVIEW_INTENTS = ['overview.home', 'overview.attention', 'overview.area'];

describe('workspace URL state', () => {
  it('WS-URL-T01 parses an empty search to the advisor defaults', () => {
    expect(parseAdvisorUrl('')).toEqual({ view: 'find', step: 'age', group: null, order: 'travel' });
  });

  it('WS-URL-T02 reads view, group and order, from a string or a URLSearchParams', () => {
    const expected = { view: 'list', step: 'age', group: 'inpatient-beds', order: 'name' };
    expect(parseAdvisorUrl('?mode=find&view=list&group=inpatient-beds&order=name')).toEqual(expected);
    expect(parseAdvisorUrl(new URLSearchParams('mode=find&view=list&group=inpatient-beds&order=name'))).toEqual(expected);
  });

  it('WS-URL-T03 falls back to the defaults for invalid advisor values', () => {
    expect(parseAdvisorUrl('view=x&step=y&group=Bad%20Group&order=z')).toEqual({
      view: 'find',
      step: 'age',
      group: null,
      order: 'travel',
    });
    for (const group of ['1abc', 'a'.repeat(65), 'UPPER']) {
      expect(parseAdvisorUrl(new URLSearchParams({ group })).group).toBeNull();
    }
    expect(parseAdvisorUrl(new URLSearchParams({ group: 'a'.repeat(64) })).group).toBe('a'.repeat(64));
  });

  it('WS-URL-T04 ignores criteria keys and returns exactly the four keys', () => {
    const result = parseAdvisorUrl('age=65-79&postcode=DT4%208XX&need=frailty&when=today&view=list');
    expect(result).toEqual({ view: 'list', step: 'age', group: null, order: 'travel' });
    expect(Object.keys(result).sort()).toEqual(['group', 'order', 'step', 'view']);
  });

  it('WS-URL-T05 builds the advisor hrefs exactly', () => {
    expect(workspaceHref('advisor.intake.age')).toBe('/advisor/v2?mode=find&view=find&step=age');
    expect(workspaceHref('advisor.intake.need')).toBe('/advisor/v2?mode=find&view=find&step=need');
    expect(workspaceHref('advisor.results')).toBe('/advisor/v2?mode=find&view=list');
    expect(workspaceHref('advisor.results', { group: 'inpatient-beds' })).toBe(
      '/advisor/v2?mode=find&view=list&group=inpatient-beds',
    );
    expect(workspaceHref('advisor.results', { order: 'name' })).toBe('/advisor/v2?mode=find&view=list&order=name');
    expect(workspaceHref('advisor.results', { group: 'inpatient-beds', order: 'name' })).toBe(
      '/advisor/v2?mode=find&view=list&group=inpatient-beds&order=name',
    );
    expect(workspaceHref('advisor.map')).toBe('/advisor/v2?mode=find&view=map');
    expect(workspaceHref('advisor.reasons')).toBe('/advisor/v2?mode=find&view=why');
    expect(workspaceHref('advisor.new-search')).toBe(workspaceHref('advisor.intake.age'));
    expect(workspaceHref('advisor.intake.age', { group: 'x' })).toBe('/advisor/v2?mode=find&view=find&step=age');
  });

  it('WS-URL-T06 never emits age, postcode, need or when, even when they are passed', () => {
    const over = {
      group: 'inpatient-beds',
      order: 'name',
      tab: 'under',
      area: 'area-one',
      age: '65-79',
      postcode: 'DT4 8XX',
      need: 'frailty',
      when: 'today',
    } as unknown as Parameters<typeof workspaceHref>[1];
    for (const id of [...ADVISOR_INTENTS, ...OVERVIEW_INTENTS]) {
      const href = workspaceHref(id, over);
      expect(href).not.toMatch(/[?&](age|postcode|need|when)=/);
      expect(href).not.toContain('DT4');
    }
  });

  it('WS-URL-T07 parses the overview url, with defaults and invalid values falling back', () => {
    expect(parseOverviewUrl('')).toEqual({ view: 'home', tab: 'pressure', area: null });
    expect(parseOverviewUrl('?view=attention&tab=under')).toEqual({ view: 'attention', tab: 'under', area: null });
    expect(parseOverviewUrl('?view=area&area=area-one')).toEqual({ view: 'area', tab: 'pressure', area: 'area-one' });
    expect(parseOverviewUrl('?view=x&tab=y&area=bad%20area')).toEqual({ view: 'home', tab: 'pressure', area: null });
    expect(parseOverviewUrl(new URLSearchParams({ area: 'a'.repeat(65) })).area).toBeNull();
  });

  it('WS-URL-T08 builds the overview hrefs exactly', () => {
    expect(workspaceHref('overview.home')).toBe('/analytics?view=home');
    expect(workspaceHref('overview.attention')).toBe('/analytics?view=attention');
    expect(workspaceHref('overview.attention', { tab: 'under' })).toBe('/analytics?view=attention&tab=under');
    expect(workspaceHref('overview.attention', { tab: 'pressure' })).toBe('/analytics?view=attention');
    expect(workspaceHref('overview.area', { area: 'area-one' })).toBe('/analytics?view=area&area=area-one');
  });

  it('WS-URL-T09 throws the exact errors for advisor.service and unknown intents', () => {
    expect(() => workspaceHref('advisor.service')).toThrow(
      new Error('workspaceHref: advisor.service has no query form'),
    );
    expect(() => workspaceHref('nope')).toThrow(new Error('workspaceHref: unknown intent'));
  });

  it('WS-URL-T10 returns the route of a nav intent with no query', () => {
    expect(workspaceHref('go.planning')).toBe('/planning');
  });
});
