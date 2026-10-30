import { describe, expect, it } from 'vitest';
import { conflictError } from './model';

describe('conflictError', () => {
  it('refuses a need that is both accepted and not accepted', () => {
    expect(conflictError(['frailty'], ['frailty'])).toBe('A need cannot be both accepted and not accepted');
  });

  it('allows distinct lists', () => {
    expect(conflictError(['frailty'], ['dementia'])).toBeNull();
    expect(conflictError([], [])).toBeNull();
  });
});
