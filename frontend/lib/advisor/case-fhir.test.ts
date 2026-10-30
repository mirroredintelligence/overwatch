import { describe, expect, it } from 'vitest';
import { CASE_BLANK, CASE_CLOSED, CASE_FULL } from '@/test/fixtures/backend-shapes';
import type { CaseInput } from './codes';
import { fromServiceRequest, SCORE_EXTENSION, toServiceRequest, URGENCY_EXTENSION } from './case-fhir';

// The mapping between the browser's coded case and the back end's ServiceRequest. The back-end side of
// every test is JSON the back end's own mapping produced (test/fixtures/backend-shapes.ts), so a
// shape the back end does not send is never assumed here.

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

type Extension = { url: string; valueCode?: string };
const extensionsOf = (request: Record<string, unknown>) => request.extension as Extension[];

describe('case scores on the ServiceRequest (W12)', () => {
  it('writes each score as a complex extension and reads it back unchanged', () => {
    const request = toServiceRequest('case-1', INPUT);
    const scores = extensionsOf(request).filter((item) => item.url === SCORE_EXTENSION);
    expect(scores).toHaveLength(5);

    expect(fromServiceRequest(request, 'W/"1"')?.scores).toEqual(INPUT.scores);
  });

  it('reads the score the back end sends, in the shape its mapping writes', () => {
    expect(fromServiceRequest(CASE_FULL, 'W/"1"')?.scores).toEqual([{ method: 'news2', value: 2 }]);
  });

  it('reads a case with no score extension as no scores', () => {
    expect(fromServiceRequest(CASE_BLANK, null)?.scores).toEqual([]);
  });

  it('is not a ServiceRequest when it has no resource type, so the route can answer 502', () => {
    expect(fromServiceRequest({ resourceType: 'Patient', id: 'x' }, null)).toBeNull();
    expect(fromServiceRequest(null, null)).toBeNull();
  });
});

describe('urgency (W11)', () => {
  it.each([
    ['within-2-hrs', 'urgent'],
    ['today', 'routine'],
    ['planned', 'routine'],
  ] as const)('writes %s as the urgency extension and the priority %s', (urgency, priority) => {
    const request = toServiceRequest('case-1', { ...INPUT, urgency });
    expect(request.priority).toBe(priority);
    expect(extensionsOf(request).find((item) => item.url === URGENCY_EXTENSION)?.valueCode).toBe(urgency);
  });

  it('reads planned back as planned, from the urgency extension (the priority alone cannot say)', () => {
    const planned = { ...CASE_FULL, priority: 'routine', extension: toServiceRequest('case-1', { ...INPUT, urgency: 'planned' }).extension };
    expect(fromServiceRequest(planned, null)?.urgency).toBe('planned');
    expect(fromServiceRequest(toServiceRequest('case-1', { ...INPUT, urgency: 'today' }), null)?.urgency).toBe('today');
  });

  it('reads the urgency the back end sends', () => {
    expect(fromServiceRequest(CASE_FULL, null)?.urgency).toBe('within-2-hrs');
  });

  it('falls back to the priority only when the extension is absent (urgent is within 2 hrs, routine is today)', () => {
    const noExtension = { ...CASE_FULL, extension: [] };
    expect(fromServiceRequest(noExtension, null)?.urgency).toBe('within-2-hrs');
    expect(fromServiceRequest({ ...noExtension, priority: 'routine' }, null)?.urgency).toBe('today');
  });

  it('reads an urgency the rules do not know as none, never a guess', () => {
    const odd = {
      ...CASE_FULL,
      extension: [{ url: URGENCY_EXTENSION, valueCode: 'whenever' }],
    };
    expect(fromServiceRequest(odd, null)?.urgency).toBeNull();
  });
});

describe('the case the back end answers (W10, W11)', () => {
  it('reads the id, the case number, the open time, the district and the codes', () => {
    expect(fromServiceRequest(CASE_FULL, 'W/"1"')).toEqual({
      id: 'case-1',
      reference: '4821',
      referrerType: 'ambulance-crew',
      ageBand: '80+',
      postcode: 'DT4',
      needs: ['fall-no-injury', 'frailty'],
      urgency: 'within-2-hrs',
      scores: [{ method: 'news2', value: 2 }],
      openedAt: '2026-10-30T14:00:00Z',
      closed: false,
      closedAt: null,
      outcome: null,
      etag: 'W/"1"',
    });
  });

  it('reads a blank case as nothing recorded yet', () => {
    expect(fromServiceRequest(CASE_BLANK, null)).toMatchObject({
      reference: '4821',
      referrerType: null,
      ageBand: null,
      postcode: null,
      needs: [],
      urgency: null,
      scores: [],
      closed: false,
      openedAt: '2026-10-30T14:00:00Z',
    });
  });

  it('reads a closed case with its close time and outcome, and no postcode or needs (D18)', () => {
    expect(fromServiceRequest(CASE_CLOSED, null)).toMatchObject({
      closed: true,
      closedAt: '2026-10-30T14:09:00Z',
      outcome: 'accepted-and-booked',
      postcode: null,
      needs: [],
    });
  });

  it('keeps no field the screens do not show: no practitioner, no extension it does not know', () => {
    const noisy = { ...CASE_FULL, requester: { reference: 'Practitioner/adv-1' }, text: { div: 'Sample Patient' } };
    expect(JSON.stringify(fromServiceRequest(noisy, null))).not.toContain('Sample Patient');
    expect(JSON.stringify(fromServiceRequest(noisy, null))).not.toContain('adv-1');
  });
});

describe('what a save writes (W11)', () => {
  it('writes the postcode when one is given, for the back end to keep as its district (DEC-398)', () => {
    const patient = (toServiceRequest('case-1', INPUT).contained as { address?: { postalCode: string }[] }[])[0];
    expect(patient?.address).toEqual([{ postalCode: 'DT4 8XX' }]);
  });

  it('leaves the postcode out when the stored district is to stay as it is', () => {
    const request = toServiceRequest('case-1', { ...INPUT, postcode: null });
    expect(JSON.stringify(request)).not.toContain('postalCode');
    expect(JSON.stringify(request)).not.toContain('"address"');
  });
});
