// UK mobile numbers as the registration screens take them. The browser sends the digits only; the
// back end checks the same shape again (R10 is_full_uk_phone, and the identity route's own check).

const MOBILE = /^07\d{9}$/;

export type MobileProblem = 'empty' | 'invalid';

/** The eleven-digit national form of a UK mobile, or null. Spaces and hyphens do not count, and +44 7… is accepted. */
export function normaliseMobile(input: string): string | null {
  let compact = input.replace(/[\s-]/g, '');
  if (compact.startsWith('+44')) compact = `0${compact.slice(3)}`;
  return MOBILE.test(compact) ? compact : null;
}

/** Why a typed number is refused, or null when it is a UK mobile. */
export function mobileProblem(input: string): MobileProblem | null {
  if (input.trim() === '') return 'empty';
  return normaliseMobile(input) === null ? 'invalid' : null;
}

/** The number as the code screen shows it: only the last three digits. */
export function maskMobile(mobile: string): string {
  return `07xxx xxx${mobile.slice(-3)}`;
}
