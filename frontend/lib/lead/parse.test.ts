import { describe, expect, it } from 'vitest';
import { OVERVIEW_SHIFT_LEAD } from '@/test/fixtures/lead';
import { LeadParseError, parseOverview } from './parse';

// Written after parse.ts, in the same commit (the parser is small and was shaped by the fixture).
describe('parseOverview', () => {
  it('reads the sample overview unchanged', () => {
    expect(parseOverview(structuredClone(OVERVIEW_SHIFT_LEAD))).toEqual(OVERVIEW_SHIFT_LEAD);
  });

  it('refuses an answer with no chasing list, rather than reading it as nothing to chase', () => {
    const rest = structuredClone(OVERVIEW_SHIFT_LEAD) as Partial<typeof OVERVIEW_SHIFT_LEAD>;
    delete rest.chasing;
    expect(() => parseOverview(rest)).toThrow(LeadParseError);
  });

  it('refuses a ladder step it does not know', () => {
    const bad = structuredClone(OVERVIEW_SHIFT_LEAD);
    bad.chasing[0].ladder[0].step = 'text' as never;
    expect(() => parseOverview(bad)).toThrow(LeadParseError);
  });

  it('refuses a negative count', () => {
    const bad = structuredClone(OVERVIEW_SHIFT_LEAD);
    bad.counts.accepting = -1;
    expect(() => parseOverview(bad)).toThrow(LeadParseError);
  });
});
