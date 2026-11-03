// The postcode district check and download (DEC-1329), as the BFF returns them. The back end's answer is
// read here, never trusted as it arrives: a count that is not a whole number, or a prefix that is not text,
// is an unreadable answer, never a guessed count.

export type DistrictCheck = { prefix: string; postcodes: number };

/** The check the back end made for one district, or null when the answer is not the one it gives. */
export function districtCheckFrom(data: unknown): DistrictCheck | null {
  if (typeof data !== 'object' || data === null) return null;
  const { prefix, postcodes } = data as { prefix?: unknown; postcodes?: unknown };
  if (typeof prefix !== 'string' || prefix.length === 0 || prefix.length > 8) return null;
  if (typeof postcodes !== 'number' || !Number.isSafeInteger(postcodes) || postcodes < 0) return null;
  return { prefix, postcodes };
}

/** The district entries the admin typed: separated by commas, trimmed, upper-cased, with blanks dropped. */
export function typedDistricts(text: string): string[] {
  return text
    .split(',')
    .map((entry) => entry.trim().replace(/\s+/g, ' ').toUpperCase())
    .filter((entry) => entry.length > 0);
}
