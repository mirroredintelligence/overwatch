import { describe, expect, it } from 'vitest';
import { maskMobile, mobileProblem, normaliseMobile } from './phone';

// UK mobile numbers as the registration screens take them. Sample numbers only.

describe('normaliseMobile', () => {
  it('returns the eleven digits of a UK mobile written with a space', () => {
    expect(normaliseMobile('07700 900456')).toBe('07700900456');
  });

  it('ignores spaces and hyphens around and inside the number', () => {
    expect(normaliseMobile('  07700-900-456 ')).toBe('07700900456');
  });

  it('turns +44 7… into the national form', () => {
    expect(normaliseMobile('+44 7700 900456')).toBe('07700900456');
  });

  it.each(['', '   ', '0123', '07700 9004567', '07700 90045', '01305 123456', 'abc', '+44 1305 123456'])(
    'refuses %j, which is not a UK mobile',
    (value) => {
      expect(normaliseMobile(value)).toBeNull();
    },
  );
});

describe('mobileProblem', () => {
  it('says empty for nothing but spaces', () => {
    expect(mobileProblem('   ')).toBe('empty');
    expect(mobileProblem('')).toBe('empty');
  });

  it('says invalid for anything else that is not a UK mobile', () => {
    expect(mobileProblem('07700')).toBe('invalid');
  });

  it('is null for a UK mobile', () => {
    expect(mobileProblem('07700 900456')).toBeNull();
  });
});

describe('maskMobile', () => {
  it('shows only the last three digits, as the code screen does', () => {
    expect(maskMobile('07700900456')).toBe('07xxx xxx456');
  });
});
