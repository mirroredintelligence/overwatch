import { FhirError } from '@/lib/fhir/client';

// The shapes of the ids the network administration routes take, checked before any back-end path is
// built (TEN-080). A malformed id is the same 404 as an unknown one, so the answer never says which.

import { RECORD_ID } from './patterns';

export { NETWORK_ID, ORGANISATION_CODE, RECORD_ID } from './patterns';

function notFound(): FhirError {
  return new FhirError(404, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-found', diagnostics: 'not found' }] });
}

/** A record id from a route segment, or the one 404. */
export async function recordIdOf(context: { params: Promise<Record<string, string>> }, name = 'id'): Promise<string> {
  const { [name]: value } = await context.params;
  if (typeof value !== 'string' || !RECORD_ID.test(value)) throw notFound();
  return value;
}

export { notFound };
