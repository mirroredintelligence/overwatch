// The postcode suggestions as an advisor types (DEC-1332). A failed or slow lookup offers nothing: the field
// still takes a full postcode typed by hand, so a lookup that cannot answer never blocks the form.

const MIN_CHARS = 2;

/** The postcodes that start with the typed text, from the local file. Empty when the text is too short or the
 *  lookup cannot answer. */
export async function suggestPostcodes(typed: string, signal?: AbortSignal): Promise<string[]> {
  const prefix = typed.trim().replace(/\s+/g, ' ').toUpperCase();
  if (prefix.length < MIN_CHARS) return [];
  try {
    const response = await fetch(`/api/bff/advisor/postcodes?prefix=${encodeURIComponent(prefix)}`, {
      cache: 'no-store',
      credentials: 'same-origin',
      signal,
    });
    if (!response.ok) return [];
    const body = (await response.json()) as { postcodes?: unknown };
    return Array.isArray(body.postcodes) ? body.postcodes.filter((p): p is string => typeof p === 'string') : [];
  } catch {
    return [];
  }
}

/** The position of a full postcode from OS Places (DEC-1340). Only the typed postcode is sent, through the BFF.
 *  A lookup that cannot answer is 'unavailable', so the form still saves the postcode as typed. */
export type PostcodeLocation =
  | { status: 'found'; lat: number; lon: number }
  | { status: 'not-found' }
  | { status: 'unavailable' };

export async function locatePostcode(postcode: string, signal?: AbortSignal): Promise<PostcodeLocation> {
  try {
    const response = await fetch(`/api/bff/advisor/postcodes/locate?postcode=${encodeURIComponent(postcode)}`, {
      cache: 'no-store',
      credentials: 'same-origin',
      signal,
    });
    if (!response.ok) return { status: 'unavailable' };
    const body = (await response.json()) as { status?: unknown; lat?: unknown; lon?: unknown };
    if (body.status === 'not-found') return { status: 'not-found' };
    if (body.status === 'found' && typeof body.lat === 'number' && typeof body.lon === 'number') {
      return { status: 'found', lat: body.lat, lon: body.lon };
    }
    return { status: 'unavailable' };
  } catch {
    return { status: 'unavailable' };
  }
}
