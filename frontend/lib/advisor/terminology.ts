import { PATHWAYS_RESULTS_MAX } from './scores';
import { FhirError, fhirFetch } from '@/lib/fhir/client';
import type { OperationOutcome } from '@/lib/fhir/types';

// Server-only. The Pathways Dx lookup (R16), mounted at the back end's root. Codes come from the
// back end's list; the browser may only choose one of them (W12).

export type PathwaysDx = { code: string; display: string };

function unreadable(): FhirError {
  const outcome: OperationOutcome = {
    resourceType: 'OperationOutcome',
    issue: [{ severity: 'error', code: 'exception', diagnostics: 'The back end returned a code list that could not be read.' }],
  };
  return new FhirError(502, outcome);
}

export async function searchPathwaysDx(token: string, text: string): Promise<PathwaysDx[]> {
  const { data } = await fhirFetch<unknown>(`/terminology/pathways-dx?q=${encodeURIComponent(text)}`, {
    token,
    root: true,
  });
  if (!Array.isArray(data)) throw unreadable();
  const codes: PathwaysDx[] = [];
  for (const item of data) {
    if (typeof item !== 'object' || item === null) continue;
    const { code, display } = item as { code?: unknown; display?: unknown };
    if (typeof code === 'string' && typeof display === 'string') codes.push({ code, display });
  }
  return codes.slice(0, PATHWAYS_RESULTS_MAX);
}
