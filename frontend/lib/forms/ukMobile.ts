// A UK mobile number as the forms accept it (W18, W37, W43): national ("07700 900123") or +44, with
// spaces, hyphens or brackets anywhere. The back end normalises the same way (normalise_uk_mobile).
// It checks the shape only; the back end checks the number, and it is never echoed back in full.

const MOBILE = /^07\d{9}$/;

/** The national form of the number: separators removed, and +44 or 0044 turned into the leading 0. */
export function normaliseUkMobile(value: string): string {
  const compact = value.replace(/[\s\-()]/g, '');
  if (compact.startsWith('+44')) return `0${compact.slice(3).replace(/^0/, '')}`;
  if (compact.startsWith('0044')) return `0${compact.slice(4)}`;
  return compact;
}

export function isUkMobile(value: string): boolean {
  return MOBILE.test(normaliseUkMobile(value));
}
