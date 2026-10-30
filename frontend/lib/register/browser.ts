// The registration pages' calls to the BFF, from the browser. Nothing here names a tenant: the
// session and the registration are the only things the BFF needs, and both are in its cookies.
// The CSRF header name is written out here, because lib/auth/csrf.ts is server-only.

import { isStepName } from './steps';
import type { FieldIssue, RegistrationView, StepName } from './types';

export type StepOutcome = { kind: 'saved'; status: string } | { kind: 'errors'; errors: FieldIssue[] } | { kind: 'failed' };

export type LoadOutcome = { kind: 'open'; view: RegistrationView } | { kind: 'unavailable' } | { kind: 'signed-out' };

const CSRF_HEADER = 'X-CSRF-Token';
const base = (id: string) => `/api/bff/registrations/${encodeURIComponent(id)}`;

async function bodyOf(response: Response): Promise<Record<string, unknown>> {
  try {
    const parsed = (await response.json()) as unknown;
    return typeof parsed === 'object' && parsed !== null ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

function fieldIssues(value: unknown): FieldIssue[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (item): item is FieldIssue =>
      typeof item === 'object' && item !== null && typeof (item as FieldIssue).field === 'string' && typeof (item as FieldIssue).message === 'string',
  );
}

/** The CSRF token of this session, from the BFF's session route. Null when there is no session. */
export async function sessionCsrf(): Promise<string | null> {
  try {
    const response = await fetch('/api/bff/session', { cache: 'no-store', credentials: 'same-origin' });
    if (!response.ok) return null;
    const body = await bodyOf(response);
    return typeof body.csrfToken === 'string' ? body.csrfToken : null;
  } catch {
    return null;
  }
}

/** The registration as the BFF shows it: its status, the invitation, and the saved steps. */
export async function loadRegistration(id: string): Promise<LoadOutcome> {
  let response: Response;
  try {
    response = await fetch(base(id), { cache: 'no-store', credentials: 'same-origin' });
  } catch {
    return { kind: 'unavailable' };
  }
  if (response.status === 401) return { kind: 'signed-out' };
  if (!response.ok) return { kind: 'unavailable' };
  const body = await bodyOf(response);
  if (typeof body.id !== 'string' || typeof body.status !== 'string' || typeof body.invitation !== 'object' || body.invitation === null) {
    return { kind: 'unavailable' };
  }
  return { kind: 'open', view: body as unknown as RegistrationView };
}

/** Saves one step. `values` are the screen's answers; the BFF checks and maps them. */
export async function saveStep(id: string, step: StepName, values: Record<string, unknown>, csrf: string): Promise<StepOutcome> {
  if (!isStepName(step)) return { kind: 'failed' };
  let response: Response;
  try {
    response = await fetch(`${base(id)}/steps/${step}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', [CSRF_HEADER]: csrf },
      body: JSON.stringify(values),
      cache: 'no-store',
      credentials: 'same-origin',
    });
  } catch {
    return { kind: 'failed' };
  }
  const body = await bodyOf(response);
  if (response.status === 200 && typeof body.status === 'string') return { kind: 'saved', status: body.status };
  if (response.status === 422) return { kind: 'errors', errors: fieldIssues(body.errors) };
  return { kind: 'failed' };
}
