// A light check on free text (W46): it warns, it does not block. The server is the real guard. A full
// postcode (outward and inward part) or a ten-digit number, which may be an NHS number, is flagged.

const POSTCODE = /\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b/i;
const TEN_DIGITS = /\b\d{10}\b/;

export function looksLikePatientData(text: string): boolean {
  return POSTCODE.test(text) || TEN_DIGITS.test(text);
}
