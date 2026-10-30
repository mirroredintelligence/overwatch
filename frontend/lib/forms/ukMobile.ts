// A UK mobile number as the forms accept it: 11 digits starting 07, spaces allowed (W18, W37, W43).
// The back end normalises the same way (normalise_uk_mobile). The number is never echoed back in full.

const MOBILE = /^07\d{9}$/;

/** The number with its spaces removed. */
export function normaliseUkMobile(value: string): string {
  return value.replace(/\s/g, '');
}

export function isUkMobile(value: string): boolean {
  return MOBILE.test(normaliseUkMobile(value));
}
