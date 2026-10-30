// The postcode rule of the needs form (W11). A postcode is typed once and never sent anywhere but
// the case save (DEC-398: the stored data is the district and the age band). It is never logged,
// never put in a URL and never kept in browser storage.

const FULL_POSTCODE = /^[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}$/;
const INWARD_LENGTH = 3;

/**
 * "dt48xx", " DT4 8XX " and "dt4  8xx" all become "DT4 8XX": spaces dropped, upper case, one space
 * before the last three characters. Null when the result is not a full UK postcode.
 */
export function normalisePostcode(input: string): string | null {
  const squeezed = input.replace(/\s+/g, '').toUpperCase();
  if (squeezed.length <= INWARD_LENGTH) return null;
  const outward = squeezed.slice(0, -INWARD_LENGTH);
  const inward = squeezed.slice(-INWARD_LENGTH);
  const spaced = `${outward} ${inward}`;
  return FULL_POSTCODE.test(spaced) ? spaced : null;
}
