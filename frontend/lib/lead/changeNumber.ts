import { isUkMobile } from '@/lib/forms/ukMobile';
import { invalidRequest } from './bffInput';

// The body of a change of reporter number (W18), checked before the back end is asked. The new number is
// returned as typed, for the back end to normalise; nothing here echoes it.

export const COVER_CHOICES = ['today', 'this-week', 'until-changed'] as const;
export type CoverChoice = (typeof COVER_CHOICES)[number];

export type ChangeNumber = { serviceId: string; newNumber: string; until: CoverChoice };

const SERVICE_ID = /^[A-Za-z0-9.-]{1,64}$/;
const CHANGE_KEYS = ['serviceId', 'newNumber', 'until'];

export function readChangeNumber(value: unknown): ChangeNumber {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw invalidRequest();
  const body = value as Record<string, unknown>;
  if (Object.keys(body).some((key) => !CHANGE_KEYS.includes(key))) throw invalidRequest();
  const serviceId = body.serviceId;
  const newNumber = body.newNumber;
  const until = body.until;
  if (typeof serviceId !== 'string' || !SERVICE_ID.test(serviceId)) throw invalidRequest();
  if (typeof newNumber !== 'string' || !isUkMobile(newNumber)) throw invalidRequest();
  if (typeof until !== 'string' || !(COVER_CHOICES as readonly string[]).includes(until)) throw invalidRequest();
  return { serviceId, newNumber, until: until as CoverChoice };
}
