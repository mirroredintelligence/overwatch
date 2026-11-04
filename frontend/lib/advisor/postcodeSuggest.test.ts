import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { suggestPostcodes } from './postcodeSuggest';

// The advisor's postcode suggestions (DEC-1332): a lookup that cannot answer offers nothing, and never blocks
// the typed postcode.

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

describe('suggestPostcodes', () => {
  it('asks the BFF with the typed text, upper-cased and single-spaced, and returns the postcodes', async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ postcodes: ['DT4 4FD', 'DT4 4FE'] }), { status: 200 }));
    expect(await suggestPostcodes('  dt4  4f ')).toEqual(['DT4 4FD', 'DT4 4FE']);
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/bff/advisor/postcodes?prefix=DT4%204F');
  });

  it('asks nothing for less than two characters', async () => {
    expect(await suggestPostcodes('D')).toEqual([]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('offers nothing when the lookup fails, rather than an error', async () => {
    fetchMock.mockResolvedValueOnce(new Response('{}', { status: 503 }));
    expect(await suggestPostcodes('DT4')).toEqual([]);
    fetchMock.mockRejectedValueOnce(new Error('offline'));
    expect(await suggestPostcodes('DT4')).toEqual([]);
  });

  it('keeps only text in the answer', async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ postcodes: ['DT4 4FD', 7, null] }), { status: 200 }));
    expect(await suggestPostcodes('DT4')).toEqual(['DT4 4FD']);
  });
});
