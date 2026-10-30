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

export type ServiceRequestReply = { data: unknown; etag: string | null };

/** Reads a case (GET ServiceRequest). The ETag is the one the save must send as If-Match. */
export async function readCase(token: string, id: string): Promise<ServiceRequestReply> {
  const { data, etag } = await fhirFetch<unknown>(`/ServiceRequest/${encodeURIComponent(id)}`, { token });
  return { data, etag: etag ?? null };
}

/** Saves a case (PUT ServiceRequest). The back end requires If-Match and an Idempotency-Key. A stale ETag answers 412 (FhirError), which the route maps. */
export async function updateCase(
  token: string,
  id: string,
  body: Record<string, unknown>,
  ifMatch: string,
  idempotencyKey: string,
): Promise<ServiceRequestReply> {
  const { data, etag } = await fhirFetch<unknown>(`/ServiceRequest/${encodeURIComponent(id)}`, {
    method: 'PUT',
    token,
    body,
    ifMatch,
    idempotencyKey,
  });
  return { data, etag: etag ?? null };
}

/**
 * The options for a case (W13): one `$filter-options` call. The back end writes an audit snapshot for
 * every call, so the caller makes one call per page load and sends a fresh key for it.
 */
export async function filterOptions(token: string, caseId: string, idempotencyKey: string): Promise<unknown> {
  const { data } = await fhirFetch<unknown>('/HealthcareService/$filter-options', {
    method: 'POST',
    token,
    idempotencyKey,
    body: {
      resourceType: 'Parameters',
      parameter: [{ name: 'case', valueReference: { reference: `ServiceRequest/${caseId}` } }],
    },
  });
  return data;
}

/** Closes a case with its outcome (R07 $close). The answer is the closed ServiceRequest, which carries the close time (DEC-781). */
export async function closeCase(
  token: string,
  id: string,
  input: { outcome: string; bestFitNotUsed?: string; destinationServiceId?: string },
  idempotencyKey: string,
): Promise<ServiceRequestReply> {
  const parameter: Record<string, unknown>[] = [{ name: 'outcome', valueCode: input.outcome }];
  if (input.bestFitNotUsed !== undefined) parameter.push({ name: 'bestFitNotUsed', valueCode: input.bestFitNotUsed });
  if (input.destinationServiceId !== undefined) {
    parameter.push({
      name: 'destination',
      valueReference: { reference: `HealthcareService/${input.destinationServiceId}` },
    });
  }
  const { data, etag } = await fhirFetch<unknown>(`/ServiceRequest/${encodeURIComponent(id)}/$close`, {
    method: 'POST',
    token,
    idempotencyKey,
    body: { resourceType: 'Parameters', parameter },
  });
  return { data, etag: etag ?? null };
}
