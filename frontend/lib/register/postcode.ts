// A UK postcode in its usual form: capitals, one space before the last three characters. Pure: the
// browser and the BFF both use it, so a lookup and a save agree on what was typed.

const POSTCODE = /^([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})$/;

/** The postcode as `DT4 8XX`, or null when it is not a UK postcode. */
export function normalisePostcode(input: string): string | null {
  const match = POSTCODE.exec(input.trim().toUpperCase());
  if (match === null) return null;
  return `${match[1]} ${match[2]}`;
}
