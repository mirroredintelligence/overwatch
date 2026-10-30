import { describe, expect, it } from 'vitest';
import type { CaseView } from './codes';
import { NOT_RECORDED, summaryOf, summaryText } from './summary';

const VIEW: CaseView = {
  id: 'case-1',
  reference: '4821',
  closed: false,
  closedAt: null,
  outcome: null,
  referrerType: 'ambulance-crew',
  ageBand: '80+',
  postcode: 'DT4 8XX',
  needs: ['fall-no-injury', 'frailty'],
  urgency: 'within-2-hrs',
  scores: [
    { method: 'news2', value: 2 },
    { method: 'cfs', value: 6 },
  ],
  openedAt: null,
  etag: 'W/"1"',
};

describe('summaryOf (W15)', () => {
  it('turns the case into the display strings the SystmOne summary shows', () => {
    expect(summaryOf(VIEW)).toEqual({
      reference: '4821',
      referrer: 'Ambulance crew',
      ageBand: '80+',
      postcode: 'DT4 8XX',
      needs: 'Fall, Frailty',
      urgency: 'Within 2 hrs',
      scores: 'NEWS2 2; Frailty scale 6 · Moderately frail',
      destination: NOT_RECORDED,
      booked: NOT_RECORDED,
      dataAge: NOT_RECORDED,
    });
  });

  it('says "None given" for no scores, and leaves what is unset unset', () => {
    const summary = summaryOf({ ...VIEW, scores: [], referrerType: null, postcode: null, ageBand: null });
    expect(summary.scores).toBe('None given');
    expect(summary.referrer).toBe(NOT_RECORDED);
    expect(summary.postcode).toBe(NOT_RECORDED);
  });

  it('names every score method as the referrer gave it', () => {
    const summary = summaryOf({
      ...VIEW,
      scores: [
        { method: 'ambulance-category', value: 2 },
        { method: 'manchester', value: 'very-urgent' },
        { method: 'pathways-dx', value: 'PD-101' },
      ],
    });
    expect(summary.scores).toBe('Ambulance category 2; Manchester triage Very urgent; NHS Pathways Dx PD-101');
  });
});

describe('summaryText (W15)', () => {
  it('is one row per line, "Label: value", in the order of the summary', () => {
    const text = summaryText(summaryOf(VIEW));
    expect(text.split('\n')[0]).toBe('Referrer: Ambulance crew');
    expect(text.split('\n')[1]).toBe('Age band: 80+');
    expect(text.split('\n')).toHaveLength(9);
    expect(text).toContain('Postcode: DT4 8XX');
  });
});

describe('the case number on the summary (DEC-631)', () => {
  it('is the four-digit number the back end holds, never the id used in the address', () => {
    expect(summaryOf(VIEW).reference).toBe('4821');
    expect(summaryOf({ ...VIEW, reference: null }).reference).toBe(NOT_RECORDED);
  });
});
