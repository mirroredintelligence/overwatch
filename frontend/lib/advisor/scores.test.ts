import { describe, expect, it } from 'vitest';
import { CFS_LABELS, parseNews2, parseScores } from './scores';

describe('parseNews2 (W12)', () => {
  it('an empty box is no score; whole numbers 0 to 20 are accepted', () => {
    expect(parseNews2('')).toEqual({ valid: true, value: null });
    expect(parseNews2('0')).toEqual({ valid: true, value: 0 });
    expect(parseNews2('2')).toEqual({ valid: true, value: 2 });
    expect(parseNews2('20')).toEqual({ valid: true, value: 20 });
  });

  it.each(['21', '-1', '2.5', 'a', '100', ' 2 '])('%j is not a whole number from 0 to 20', (text) => {
    expect(parseNews2(text).valid).toBe(false);
  });
});

describe('CFS labels (W12)', () => {
  it('has the nine labels of the Clinical Frailty Scale as the referrer names them', () => {
    expect(CFS_LABELS[6]).toBe('Moderately frail');
    expect(Object.keys(CFS_LABELS)).toHaveLength(9);
    expect(CFS_LABELS[1]).toBe('Very fit');
    expect(CFS_LABELS[9]).toBe('Terminally ill');
  });
});

describe('parseScores (W12)', () => {
  const SAMPLE = [
    { method: 'news2', value: 2 },
    { method: 'cfs', value: 6 },
    { method: 'ambulance-category', value: 2 },
    { method: 'manchester', value: 'very-urgent' },
    { method: 'pathways-dx', value: 'PD-101' },
  ];

  it('accepts one score per method, as recorded', () => {
    expect(parseScores(SAMPLE)).toEqual(SAMPLE);
    expect(parseScores([])).toEqual([]);
  });

  it('refuses a second score for one method', () => {
    expect(parseScores([...SAMPLE, { method: 'news2', value: 3 }])).toBeNull();
  });

  it.each([
    ['a NEWS2 over 20', { method: 'news2', value: 21 }],
    ['a NEWS2 that is not whole', { method: 'news2', value: 2.5 }],
    ['a CFS of 0', { method: 'cfs', value: 0 }],
    ['a CFS of 10', { method: 'cfs', value: 10 }],
    ['an ambulance category of 5', { method: 'ambulance-category', value: 5 }],
    ['a Manchester word not on the list', { method: 'manchester', value: 'urgent-ish' }],
    ['an empty Pathways code', { method: 'pathways-dx', value: '' }],
    ['a Pathways code with a space', { method: 'pathways-dx', value: 'PD 101' }],
    ['an unknown method', { method: 'apgar', value: 7 }],
  ])('refuses %s', (_label, score) => {
    expect(parseScores([score])).toBeNull();
  });

  it('refuses anything that is not a list', () => {
    expect(parseScores({ method: 'news2', value: 2 })).toBeNull();
    expect(parseScores(null)).toBeNull();
  });
});
