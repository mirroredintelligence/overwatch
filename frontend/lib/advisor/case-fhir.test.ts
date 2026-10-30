import { describe, expect, it } from 'vitest';
import type { CaseInput } from './codes';
import { fromServiceRequest, SCORE_EXTENSION, toServiceRequest } from './case-fhir';

const INPUT: CaseInput = {
  referrerType: 'ambulance-crew',
  ageBand: '80+',
  postcode: 'DT4 8XX',
  needs: ['fall-no-injury', 'frailty'],
  urgency: 'within-2-hrs',
  scores: [
    { method: 'news2', value: 2 },
    { method: 'cfs', value: 6 },
    { method: 'ambulance-category', value: 2 },
    { method: 'manchester', value: 'very-urgent' },
    { method: 'pathways-dx', value: 'PD-101' },
  ],
};

describe('case scores on the ServiceRequest (W12)', () => {
  it('writes each score as a complex extension and reads it back unchanged', () => {
    const request = toServiceRequest('4821', INPUT);
    const scores = (request.extension as { url: string }[]).filter((item) => item.url === SCORE_EXTENSION);
    expect(scores).toHaveLength(5);

    const back = fromServiceRequest(request, 'W/"1"');
    expect(back?.scores).toEqual(INPUT.scores);
  });

  it('reads a case with no score extension as no scores', () => {
    const request = toServiceRequest('4821', { ...INPUT, scores: [] });
    expect(fromServiceRequest(request, null)?.scores).toEqual([]);
  });

  it('pins the known loss: a planned case is stored as routine and reads back as today (DEC-397)', () => {
    const back = fromServiceRequest(toServiceRequest('4821', { ...INPUT, urgency: 'planned' }), null);
    expect(back?.urgency).toBe('today');
  });

  it('is not a ServiceRequest when it has no resource type, so the route can answer 502', () => {
    expect(fromServiceRequest({ resourceType: 'Patient', id: 'x' }, null)).toBeNull();
    expect(fromServiceRequest(null, null)).toBeNull();
  });
});
