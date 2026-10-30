import { FhirError, fhirFetch } from '@/lib/fhir/client';
import type { OperationOutcome } from '@/lib/fhir/types';

// Server-only. The one place the advisor BFF calls the back end's case routes (R07). The browser
// never calls these; the route handlers do, with the session's back-end token.

function unreadable(diagnostics: string): FhirError {
  const outcome: OperationOutcome = {
    resourceType: 'OperationOutcome',
    issue: [{ severity: 'error', code: 'exception', diagnostics }],
  };
  return new FhirError(502, outcome);
}

/** Opens a case with nothing in it yet (W10). The back end returns the new ServiceRequest. */
export async function openEmptyCase(token: string, idempotencyKey: string): Promise<{ id: string }> {
  const { data } = await fhirFetch<{ id?: unknown }>('/ServiceRequest', {
    method: 'POST',
    token,
    idempotencyKey,
    body: { resourceType: 'ServiceRequest' },
  });
  if (typeof data?.id !== 'string' || data.id.length === 0) {
    throw unreadable('The back end did not return a case.');
  }
  return { id: data.id };
}
