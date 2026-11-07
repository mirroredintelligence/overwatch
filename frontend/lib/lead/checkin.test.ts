import { describe, expect, it } from 'vitest';
import { CHECKIN_CODE } from '@/test/msw/handlers/lead';
import { CheckinCodeParseError, matrixPath, parseCheckinCode } from './checkin';

describe('parseCheckinCode', () => {
  it('reads the service, the address and the matrix', () => {
    expect(parseCheckinCode(CHECKIN_CODE)).toEqual(CHECKIN_CODE);
  });

  it.each([
    ['not an object', 'x'],
    ['no service', { ...CHECKIN_CODE, service: '' }],
    ['an address that is not https', { ...CHECKIN_CODE, url: 'http://x/c/t' }],
    ['a size that is not a QR size', { ...CHECKIN_CODE, size: 5 }],
    ['rows of the wrong number', { ...CHECKIN_CODE, rows: CHECKIN_CODE.rows.slice(1) }],
    ['a row of the wrong length', { ...CHECKIN_CODE, rows: [...CHECKIN_CODE.rows.slice(1), '1'] }],
    ['a cell that is not 0 or 1', { ...CHECKIN_CODE, rows: [...CHECKIN_CODE.rows.slice(1), '2'.repeat(21)] }],
  ])('refuses %s', (_name, value) => {
    expect(() => parseCheckinCode(value)).toThrow(CheckinCodeParseError);
  });
});

describe('matrixPath', () => {
  it('draws one bar for each run of dark cells', () => {
    expect(matrixPath(['110', '011'])).toBe('M0 0h2v1h-2zM1 1h2v1h-2z');
  });

  it('draws nothing for an empty matrix', () => {
    expect(matrixPath(['000'])).toBe('');
  });
});
