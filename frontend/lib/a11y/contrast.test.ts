import { describe, expect, it } from 'vitest';
import { contrastRatio } from './contrast';

describe('contrastRatio', () => {
  it('is 21:1 for black on white', () => {
    expect(contrastRatio('#000000', '#FFFFFF')).toBeCloseTo(21, 2);
  });

  it('is 1:1 for a colour on itself', () => {
    expect(contrastRatio('#0B5C8C', '#0B5C8C')).toBeCloseTo(1, 5);
  });

  it('matches the published value for #767676 on white (4.54:1)', () => {
    expect(contrastRatio('#767676', '#FFFFFF')).toBeCloseTo(4.54, 2);
  });

  it('does not depend on argument order', () => {
    expect(contrastRatio('#A34700', '#FFFFFF')).toBeCloseTo(
      contrastRatio('#FFFFFF', '#A34700'),
      10,
    );
  });

  it('accepts lower-case hex', () => {
    expect(contrastRatio('#ffffff', '#000000')).toBeCloseTo(21, 2);
  });
});
