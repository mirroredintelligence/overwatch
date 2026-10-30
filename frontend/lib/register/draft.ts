// Stub (red commit).
import type { FieldIssue, StepName } from './types';

export const STEP_FIELDS: Record<StepName, readonly string[]> = {
  organisation: [],
  location: [],
  service: [],
  reporting: [],
  api: [],
};

export function organisationValues(_body: Record<string, unknown>, _locked: { organisationName: string; odsCode: string }) {
  throw new Error('not implemented');
}

export function pageFieldFor(_backendField: string): string {
  throw new Error('not implemented');
}

export function issuesFromOutcome(_outcome: unknown): FieldIssue[] {
  throw new Error('not implemented');
}
