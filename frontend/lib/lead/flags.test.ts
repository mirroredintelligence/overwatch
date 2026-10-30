import { describe, expect, it } from 'vitest';
import { flagItemsFrom, flagSummary } from './flags';

describe('flagSummary', () => {
  it('says each rule in the words of the screen footnote', () => {
    expect(flagSummary('out-of-range-twice')).toBe('The figure was out of its usual range twice.');
    expect(flagSummary('many-changes')).toBe('The figure changed many times in a short time.');
    expect(flagSummary('differs-from-phoned')).toBe('The figure differs from what advisors recorded by phone.');
  });

  it('says it was flagged by rules for a reason it does not know, so the flag is never hidden', () => {
    expect(flagSummary('something-new')).toBe('Flagged by rules.');
  });
});

describe('flagItemsFrom', () => {
  const bundle = {
    resourceType: 'Bundle',
    type: 'searchset',
    total: 2,
    entry: [
      {
        resource: {
          resourceType: 'Flag',
          id: 'flag-1',
          status: 'active',
          code: { coding: [{ code: 'out-of-range-twice' }] },
          subject: { reference: 'HealthcareService/s-ucr-east', display: 'UCR East' },
          period: { start: '2026-10-30T14:12:00Z' },
        },
      },
      {
        resource: {
          resourceType: 'Flag',
          id: 'flag-2',
          code: { coding: [{ code: 'an-unknown-reason' }] },
          subject: { reference: 'HealthcareService/s-reablement', display: 'Reablement' },
        },
      },
    ],
  };

  it('maps each flag to its id, service, reason and summary', () => {
    expect(flagItemsFrom(bundle)).toEqual([
      {
        id: 'flag-1',
        serviceId: 's-ucr-east',
        serviceName: 'UCR East',
        reason: 'out-of-range-twice',
        summary: 'The figure was out of its usual range twice.',
      },
      {
        id: 'flag-2',
        serviceId: 's-reablement',
        serviceName: 'Reablement',
        reason: 'unknown',
        summary: 'Flagged by rules.',
      },
    ]);
  });

  it('gives no items for a bundle with no entries', () => {
    expect(flagItemsFrom({ resourceType: 'Bundle', type: 'searchset', total: 0 })).toEqual([]);
  });

  it('drops an entry that has no id, rather than showing a flag nobody can act on', () => {
    const noId = structuredClone(bundle);
    delete (noId.entry[0].resource as Record<string, unknown>).id;
    expect(flagItemsFrom(noId)).toHaveLength(1);
  });
});
