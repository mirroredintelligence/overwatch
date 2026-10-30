// A UK mobile number as a person types it: 07 and nine digits, or +44 7 and nine digits, with
// spaces or hyphens anywhere (W37). It checks the shape only; the back end checks the number.

export function isUkMobile(text: string): boolean {
  const compact = text.replace(/[\s-]/g, '');
  return /^07\d{9}$/.test(compact) || /^\+447\d{9}$/.test(compact);
}
