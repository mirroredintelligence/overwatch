import type { Session } from '@/lib/auth/session';
import { FhirError, fhirFetch } from '@/lib/fhir/client';
import { IDEMPOTENCY_KEY } from './answers';

// The reporter BFF routes' calls to the back end's `/reporter/...` routes (W7C, W8E). Every call
// carries the reporter's token (the session's, renewed by `withBff`) and nothing that names a tenant;
// every answer is read through a parser that keeps only the fields a screen uses, and an answer that is
// not the shape the back end promised is a 502, never data. The BFF does not decide which services a
// reporter holds: the back end reads them from the graph at the time of the request (DEC-814).

const NO_STORE = { 'Cache-Control': 'no-store' };

/** The back end answered with something that is not its contract: a fault, shown as one. */
export function badAnswer(): FhirError {
  return new FhirError(502, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'exception', diagnostics: 'The back end answered in a shape this side does not know.' }] });
}

export function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return Response.json(body, { status, headers: { ...NO_STORE, ...headers } });
}

export function plain(status: number, code: string): Response {
  return Response.json({ code }, { status, headers: NO_STORE });
}

/** The screen's Idempotency-Key, or null when it sent none that is one. */
export function keyOf(request: Request): string | null {
  const key = request.headers.get('Idempotency-Key');
  return key !== null && IDEMPOTENCY_KEY.test(key) ? key : null;
}

/** True when a body is an object with no field beyond `allowed`. */
export function onlyFields(body: unknown, allowed: readonly string[]): body is Record<string, unknown> {
  return typeof body === 'object' && body !== null && !Array.isArray(body) && Object.keys(body).every((k) => allowed.includes(k));
}

export async function readJson(request: Request): Promise<unknown> {
  return request.json().catch(() => undefined) as Promise<unknown>;
}

type Call<T> = {
  method?: 'GET' | 'POST';
  body?: unknown;
  key?: string;
  parse: (body: unknown) => T | null;
  /** Failures the route answers itself (a 409 with a body the screen needs), before the generic mapping. */
  onRefused?: (error: FhirError) => Response | null;
};

/** Calls `/reporter/...` (or another root route) as the signed-in reporter and answers the parsed result. */
export async function reporterCall<T>(session: Session, path: string, call: Call<T>): Promise<Response> {
  let data: unknown;
  try {
    ({ data } = await fhirFetch<unknown>(path, {
      method: call.method ?? (call.body === undefined ? 'GET' : 'POST'),
      body: call.body,
      token: session.backendToken,
      root: true,
      idempotencyKey: call.key,
    }));
  } catch (error) {
    if (error instanceof FhirError && call.onRefused !== undefined) {
      const answered = call.onRefused(error);
      if (answered !== null) return answered;
    }
    throw error;
  }
  const parsed = call.parse(data);
  if (parsed === null) throw badAnswer();
  return json(parsed);
}
