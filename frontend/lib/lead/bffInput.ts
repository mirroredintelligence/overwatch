import { FhirError } from '@/lib/fhir/client';
import type { OperationOutcome } from '@/lib/fhir/types';

// What the lead's BFF routes need from a request before they call the back end: the Idempotency-Key the
// back end requires (the same character rule it applies), and a JSON body. A refusal is a 400 with a
// fixed message, and it never repeats the value sent (H-331).

const KEY = /^[\x21-\x7e]{1,200}$/;

export function invalidRequest(): FhirError {
  const outcome: OperationOutcome = {
    resourceType: 'OperationOutcome',
    issue: [{ severity: 'error', code: 'invalid', diagnostics: 'The request was not valid.' }],
  };
  return new FhirError(400, outcome);
}

/** The Idempotency-Key header, checked as the back end checks it. Missing or malformed is a 400. */
export function idempotencyKeyOf(request: Request): string {
  const value = request.headers.get('idempotency-key');
  if (value === null || !KEY.test(value)) throw invalidRequest();
  return value;
}

/** The request's JSON body. Anything that is not JSON is a 400. */
export async function jsonBody(request: Request): Promise<unknown> {
  try {
    return (await request.json()) as unknown;
  } catch {
    throw invalidRequest();
  }
}
