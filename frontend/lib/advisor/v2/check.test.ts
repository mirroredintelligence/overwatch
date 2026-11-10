import { describe, expect, it } from 'vitest';
import { parseCheck } from './check';

const FIT = {
  serviceId: 's',
  fits: true,
  reasons: [],
  fitsNeeds: ['frailty'],
  warnings: ['Figure is old'],
  phone: '01305 000000',
};

describe('parseCheck', () => {
  it('reads a fit and a non-fit', () => {
    expect(parseCheck(FIT)).toMatchObject({ fits: true, phone: '01305 000000', fitsNeeds: ['frailty'] });
    expect(parseCheck({ ...FIT, fits: false, reasons: ['Does not accept frailty'], fitsNeeds: [] })).toMatchObject({
      fits: false,
      reasons: ['Does not accept frailty'],
    });
  });

  it('never reads a missing or unsound answer as a fit', () => {
    expect(parseCheck({ serviceId: 's', reasons: [] })).toBeNull();
    expect(parseCheck({ ...FIT, fits: 'yes' })).toBeNull();
    expect(parseCheck({ ...FIT, reasons: ['Does not accept frailty'] })).toBeNull();
    expect(parseCheck({ ...FIT, fits: false, reasons: [] })).toBeNull();
    expect(parseCheck({ ...FIT, fits: true, reasons: [''] })).toBeNull();
    expect(parseCheck({ ...FIT, fits: true, reasons: [123] })).toBeNull();
    expect(parseCheck({ ...FIT, reasons: 'none' })).toBeNull();
    expect(parseCheck(null)).toBeNull();
    expect(parseCheck([])).toBeNull();
  });
});
