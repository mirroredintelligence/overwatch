import type { Parameters } from '@/lib/fhir/types';
import type { Board } from './types';

// Stub (DEC-010): the red commit holds this so the tests fail on an assertion.
export class BoardParseError extends Error {}

export function parseBoardParameters(parameters: Parameters): Board {
  void parameters;
  return { entries: [], pressure: '', allLimitedOrWorse: false, generatedAt: '', organisation: null };
}
