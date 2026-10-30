import { fhirFetch, FhirError } from '@/lib/fhir/client';
import { replayFromBackEnd, type AuditReplay } from './audit';

// Server only: one read of the audit replay for the lead (W47). It is not cached, and each read is audited
// by the back end (U42). A refusal and an unknown reference are the same 404, so the answer does not say
// which: the page says "No record for that reference." for both.

export async function fetchReplay(token: string, reference: string): Promise<AuditReplay> {
  try {
    const { data } = await fhirFetch<unknown>(`/admin/audit/${encodeURIComponent(reference)}`, {
      root: true,
      token,
      cache: 'no-store',
    });
    return replayFromBackEnd(data);
  } catch (error) {
    if (error instanceof FhirError && (error.status === 403 || error.status === 404)) {
      throw new FhirError(404, {
        resourceType: 'OperationOutcome',
        issue: [{ severity: 'error', code: 'not-found', diagnostics: 'not found' }],
      });
    }
    throw error;
  }
}
