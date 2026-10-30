// The duty coordinator's number as a phone link (W40, DEC-777). Pure.

/** "01632 960001" as a tel: link target: digits and a leading plus only. */
export function telHref(phone: string): string {
  return `tel:${phone.replace(/[^0-9+]/g, '')}`;
}
