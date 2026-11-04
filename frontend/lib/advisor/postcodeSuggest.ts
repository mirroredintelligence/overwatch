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
