// Stub (red commit).
import type { FieldIssue, RegistrationView, StepName } from './types';

export type StepOutcome =
  | { kind: 'saved'; status: string }
  | { kind: 'errors'; errors: FieldIssue[] }
  | { kind: 'failed' };

export async function sessionCsrf(): Promise<string | null> {
  throw new Error('not implemented');
}

export async function loadRegistration(_id: string): Promise<{ kind: 'open'; view: RegistrationView } | { kind: 'unavailable' } | { kind: 'signed-out' }> {
  throw new Error('not implemented');
}

export async function saveStep(_id: string, _step: StepName, _values: Record<string, unknown>, _csrf: string): Promise<StepOutcome> {
  throw new Error('not implemented');
}
