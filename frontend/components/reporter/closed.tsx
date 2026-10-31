import { type ClosedLink, londonHm } from '@/lib/links/model';

// What a closed booking page says of its closing (KI-169, KI-648, KI-649, KI-664, KI-665; H-486, H-488,
// H-499): the booking's reference, when it closed, and the coordination number. Each is shown only when
// the back end sent it; none is guessed.

/** "Reference 4821. Closed at 14:26." from what is known, or null when nothing is. */
export function closedFacts(closed: ClosedLink | null): string | null {
  if (closed === null) return null;
  const parts: string[] = [];
  if (closed.reference !== null) parts.push(`Reference ${closed.reference}.`);
  if (closed.closedAt !== null) parts.push(`Closed at ${londonHm(closed.closedAt)}.`);
  return parts.length === 0 ? null : parts.join(' ');
}

/** "<verb> at 14:19." for a time, or null when there is none. */
export function atTime(verb: string, instant: string | null | undefined): string | null {
  return instant === null || instant === undefined ? null : `${verb} at ${londonHm(instant)}.`;
}

/** The coordination number as a link a phone can dial, or the words to use when there is none. */
export function PhoneTo({ phone, lead, none }: { phone: string | null; lead: string; none: string }) {
  if (phone === null) return <>{none}</>;
  return (
    <>
      {lead} <a href={`tel:${phone}`}>{phone}</a>.
    </>
  );
}
