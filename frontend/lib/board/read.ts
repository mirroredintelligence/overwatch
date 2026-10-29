import type { Role, Session } from '@/lib/auth/session';
import { FhirError, fhirFetch } from '@/lib/fhir/client';
import type { Parameters } from '@/lib/fhir/types';
import { BoardParseError, parseBoardParameters } from './parse';
import type { Board } from './types';

// Server-only. The one place the front end reads `$board`, for the page and for
// GET /api/bff/board, so both answer from the same code.

/** The roles that may read the wall board here (W05 prompt). */
export const BOARD_ROLES: readonly Role[] = ['wall', 'advisor', 'lead', 'exec'];

export function canReadBoard(role: Role): boolean {
  return BOARD_ROLES.includes(role);
}

/**
 * Reads the board for the signed-in session. The back-end token is the only
 * thing that says whose board this is: no organisation, scope or tenant is taken
 * from the caller and none is sent (DEC-130, DEC-132).
 */
export async function readBoard(session: Pick<Session, 'backendToken'>): Promise<Board> {
  const { data } = await fhirFetch<Parameters>('/HealthcareService/$board', {
    token: session.backendToken,
  });
  try {
    return parseBoardParameters(data);
  } catch (error) {
    if (!(error instanceof BoardParseError)) throw error;
    // A board it cannot read is a bad answer from the back end. Nothing from the
    // body is kept in the error.
    throw new FhirError(502, {
      resourceType: 'OperationOutcome',
      issue: [{ severity: 'error', code: 'exception', diagnostics: 'The back end returned a board that could not be read.' }],
    });
  }
}
