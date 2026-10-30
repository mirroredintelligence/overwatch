import { describe, expect, it } from 'vitest';
import { looksLikePatientData } from './patientDataHint';

describe('looksLikePatientData', () => {
  it('flags a full postcode', () => {
    expect(looksLikePatientData('fell at DT4 8XX')).toBe(true);
    expect(looksLikePatientData('dt48xx')).toBe(true);
  });

  it('flags a ten digit number, which may be an NHS number', () => {
    expect(looksLikePatientData('4857773456')).toBe(true);
  });

  it('does not flag ordinary words', () => {
    expect(looksLikePatientData('ward was full')).toBe(false);
    expect(looksLikePatientData('the button is slow after 2 clicks')).toBe(false);
  });
});
