import { FhirError } from '@/lib/fhir/client';

// A path segment of a tenant administrator route, checked by its shape before it goes into a back-end
// path. A malformed one is the same 404 as an unknown one, so the answer does not say which it is.

const PATTERNS = {
  ticket: /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/,
  channel: /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/,
  version: /^[1-9][0-9]{0,5}$/,
  tenant: /^[a-z0-9][a-z0-9-]{1,30}$/,
} as const;

export function notFound(): FhirError {
  return new FhirError(404, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-found', diagnostics: 'not found' }] });
}

export async function segment(context: { params: Promise<Record<string, string>> }, name: string, kind: keyof typeof PATTERNS): Promise<string> {
  const { [name]: value } = await context.params;
  if (typeof value !== 'string' || !PATTERNS[kind].test(value)) throw notFound();
  return value;
}
