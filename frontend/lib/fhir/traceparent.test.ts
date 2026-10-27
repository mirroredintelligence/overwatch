import { afterEach, describe, expect, it, vi } from 'vitest';
import { newTraceparent } from './traceparent';

const FORMAT = /^00-[0-9a-f]{32}-[0-9a-f]{16}-01$/;

afterEach(() => {
  vi.restoreAllMocks();
});

describe('newTraceparent', () => {
  it('returns a W3C traceparent with version 00 and the sampled flag', () => {
    expect(newTraceparent()).toMatch(FORMAT);
  });

  it('returns a different value on each call', () => {
    expect(newTraceparent()).not.toBe(newTraceparent());
  });

  it('takes its random bytes from crypto.getRandomValues', () => {
    const spy = vi.spyOn(crypto, 'getRandomValues');

    newTraceparent();

    expect(spy).toHaveBeenCalled();
  });

  it('never returns an all-zero trace id, which W3C forbids', () => {
    const spy = vi.spyOn(crypto, 'getRandomValues');
    spy.mockImplementationOnce(<T extends ArrayBufferView | null>(array: T): T => {
      if (array instanceof Uint8Array) array.fill(0);
      return array;
    });

    const value = newTraceparent();

    expect(value).toMatch(FORMAT);
    expect(value.slice(3, 35)).not.toBe('0'.repeat(32));
  });
});
