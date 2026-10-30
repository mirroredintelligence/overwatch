import { isUkMobile } from '@/lib/forms/ukMobile';
import { onlyFields } from './backend';

// The body of a cover request, checked before the back end is asked (DEC-820). The number is passed on
// and never answered, logged or kept.
export type CoverBody = { phone: string; until: 'tonight' | 'this-week' | 'date'; date?: string };

export function coverBody(body: unknown): CoverBody | null {
  if (!onlyFields(body, ['phone', 'until', 'date'])) return null;
  if (typeof body.phone !== 'string' || !isUkMobile(body.phone)) return null;
  const until = body.until;
  if (until !== 'tonight' && until !== 'this-week' && until !== 'date') return null;
  if (until !== 'date') return body.date === undefined ? { phone: body.phone, until } : null;
  return typeof body.date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(body.date) && !Number.isNaN(Date.parse(body.date))
    ? { phone: body.phone, until, date: body.date }
    : null;
}
