import { FhirError } from '@/lib/fhir/client';

// The shapes of the ids the network administration routes take, checked before any back-end path is
// built (TEN-080). A malformed id is the same 404 as an unknown one, so the answer never says which.

/** A network id as the back end makes it: `net-` and lower-case letters, digits and hyphens, 31 characters at most. */
export const NETWORK_ID = /^net-[a-z0-9][a-z0-9-]{1,26}$/;
/** A registry record's id (a membership, a grant, a listing): `RECORD_ID_PATTERN` of the back end. */
export const RECORD_ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
/** An organisation code: the back end's tenant id shape (`TENANT_ID_PATTERN`). */
export const ORGANISATION_CODE = /^[a-z0-9][a-z0-9-]{1,30}$/;

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
