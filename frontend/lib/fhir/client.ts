import { namesTenantInput } from '@/lib/tenant/inputNames';
import { newTraceparent } from './traceparent';
import type { OperationOutcome } from './types';

// Server-only client for the back end's FHIR R4B API. Route handlers and
// Server Components call it; the browser never does (contracts.md, Front end).
//
// Tenancy (TEN-045, DEC-130, DEC-134 item 2): every call carries the signed-in person's back-end
// token and no other statement of who is asking. The token is required (a call with none is a fault,
// refused before anything is sent), the tenant is never sent as a header, a query key or a body field
// (the caller has no place to put one and a path that names one is refused), and no answer is stored
// by any cache (`cache: 'no-store'`, so Next.js never keeps one across people or tenants). The calls
// that have no token (the link pages and the sign-in exchange) are in hostCall.ts.

export type FhirInit = {
  /** Defaults to GET, or POST when a body is given. */
  method?: string;
  /** Serialised as JSON. */
  body?: unknown;
  /** Sent as `Authorization: Bearer <token>`. Required: a call with none is refused (TokenRequired). */
  token: string;
  idempotencyKey?: string;
  /** An ETag such as `W/"3"`. */
  ifMatch?: string;
  /** Passed through unchanged; otherwise a new one is generated. */
  traceparent?: string;
};

export type FhirResult<T> = { data: T; etag?: string };

export class FhirError extends Error {
  readonly status: number;
  readonly outcome: OperationOutcome;

  constructor(status: number, outcome: OperationOutcome) {
    super(`FHIR request failed with status ${status}`);
    this.name = 'FhirError';
    this.status = status;
    this.outcome = outcome;
  }
}

const FHIR_MEDIA_TYPE = 'application/fhir+json; fhirVersion=4.3';
const BASE_URL_VARIABLE = 'DIUCS_FHIR_BASE_URL';

/** A call made with no usable token. A fault in the caller, never an answer to show a person. */
export class TokenRequired extends Error {
  constructor() {
    super('A back-end token is required for this call.');
    this.name = 'TokenRequired';
  }
}

/** A path that could reach beyond the FHIR base, or that names a tenant, scope or network. */
export class PathRefused extends Error {
  constructor() {
    super('The back-end path is not allowed.');
    this.name = 'PathRefused';
  }
}

// A bearer token as the back end issues it (base64url parts joined by dots) and as the tests write
// them: no space, no control character, bounded.
const TOKEN_SHAPE = /^[A-Za-z0-9._~+/=-]{1,8192}$/;
// The characters a FHIR path may hold: segments of unreserved characters, `$` for an operation, and
// percent signs (checked below), then an optional query.
const PATH_SHAPE = /^(\/[A-Za-z0-9._~!$&'()*+,;=:@%-]*)+(\?[A-Za-z0-9._~!$&'()*+,;=:@%/?|-]*)?$/;
const ENCODED_DANGER = /%(2e|2f|5c|00)/i;

function checkedToken(token: unknown): string {
  if (typeof token !== 'string' || !TOKEN_SHAPE.test(token)) throw new TokenRequired();
  return token;
}

/**
 * The path, when it stays under the FHIR base: it starts with one slash, holds no second slash in a
 * row, no backslash, no fragment, no dot segment (also written %2e) and nothing that decodes to a
 * slash; and its query names no tenant, scope or network.
 */
function checkedPath(path: string): string {
  if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//') || !PATH_SHAPE.test(path)) {
    throw new PathRefused();
  }
  const [route = '', query = ''] = path.split('?', 2);
  if (route.includes('//') || ENCODED_DANGER.test(route)) throw new PathRefused();
  if (route.split('/').some((segment) => segment === '.' || segment === '..')) throw new PathRefused();
  for (const key of new URLSearchParams(query).keys()) if (namesTenantInput(key)) throw new PathRefused();
  return path;
}

function baseUrl(): string {
  // Read at call time, so a missing value fails the request that needs it.
  // The message names the variable only, never a URL.
  const value = process.env[BASE_URL_VARIABLE];
  if (!value) {
    throw new Error(`${BASE_URL_VARIABLE} is not set, so the back end cannot be called.`);
  }
  return value.replace(/\/+$/, '');
}

function outcomeFor(code: string, diagnostics: string): OperationOutcome {
  return {
    resourceType: 'OperationOutcome',
    issue: [{ severity: 'error', code, diagnostics }],
  };
}

function isOperationOutcome(value: unknown): value is OperationOutcome {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as { resourceType?: unknown; issue?: unknown };
  return candidate.resourceType === 'OperationOutcome' && Array.isArray(candidate.issue);
}

function tryParseJson(text: string): { ok: true; value: unknown } | { ok: false } {
  try {
    return { ok: true, value: JSON.parse(text) as unknown };
  } catch {
    return { ok: false };
  }
}

/** The outcome of a failed answer: the back end's own OperationOutcome, or a plain one naming the status only. */
function failureOutcome(status: number, text: string): OperationOutcome {
  const parsed = text ? tryParseJson(text) : { ok: false as const };
  return parsed.ok && isOperationOutcome(parsed.value) ? parsed.value : outcomeFor('exception', `HTTP ${status}`);
}

export async function fhirFetch<T>(path: string, init: FhirInit): Promise<FhirResult<T>> {
  const token = checkedToken(init?.token);
  const url = `${baseUrl()}${checkedPath(path)}`;
  const hasBody = init.body !== undefined;

  const headers = new Headers({
    Accept: FHIR_MEDIA_TYPE,
    traceparent: init.traceparent ?? newTraceparent(),
  });
  headers.set('Authorization', `Bearer ${token}`);
  if (init.idempotencyKey) headers.set('Idempotency-Key', init.idempotencyKey);
  if (init.ifMatch) headers.set('If-Match', init.ifMatch);
  if (hasBody) headers.set('Content-Type', FHIR_MEDIA_TYPE);

  let response: Response;
  let text: string;
  try {
    response = await fetch(url, {
      method: init.method ?? (hasBody ? 'POST' : 'GET'),
      headers,
      body: hasBody ? JSON.stringify(init.body) : undefined,
      // Never kept by Next.js or a proxy: an answer is for one person and one tenant.
      cache: 'no-store',
    });
    text = await response.text();
  } catch {
    // Covers a failed request and a body that cannot be read. The error
    // itself is not kept: it can carry the URL or the network detail.
    throw new FhirError(503, outcomeFor('transient', 'The back end could not be reached.'));
  }

  if (!response.ok) throw new FhirError(response.status, failureOutcome(response.status, text));

  const etag = response.headers.get('ETag') ?? undefined;
  if (response.status === 204 || text === '') {
    return { data: undefined as T, etag };
  }

  const parsed = tryParseJson(text);
  if (!parsed.ok) {
    throw new FhirError(
      502,
      outcomeFor('exception', 'The back end returned a body that is not JSON.'),
    );
  }
  return { data: parsed.value as T, etag };
}

export type FhirStreamInit = Pick<FhirInit, 'token' | 'traceparent'> & {
  /** Aborting closes the connection to the back end. */
  signal?: AbortSignal;
};

const EVENT_STREAM = 'text/event-stream';

/**
 * Opens a server-sent event stream (a GET) and returns its body without reading
 * it, so a route handler can relay it as it arrives. It checks the answer before
 * anything is relayed: a refusal or failure is a FhirError with the back end's
 * status, and a 200 that is not an event stream is a 502.
 */
export async function fhirStream(
  path: string,
  init: FhirStreamInit,
): Promise<{ body: ReadableStream<Uint8Array> }> {
  const token = checkedToken(init?.token);
  const url = `${baseUrl()}${checkedPath(path)}`;
  const headers = new Headers({ Accept: EVENT_STREAM, traceparent: init.traceparent ?? newTraceparent() });
  headers.set('Authorization', `Bearer ${token}`);

  let response: Response;
  try {
    response = await fetch(url, { method: 'GET', headers, signal: init.signal, cache: 'no-store' });
  } catch {
    // The error itself is not kept: it can carry the URL or the network detail.
    throw new FhirError(503, outcomeFor('transient', 'The back end could not be reached.'));
  }

  if (!response.ok) {
    let text = '';
    try {
      text = await response.text();
    } catch {
      text = '';
    }
    throw new FhirError(response.status, failureOutcome(response.status, text));
  }

  const isStream = (response.headers.get('Content-Type') ?? '').toLowerCase().startsWith(EVENT_STREAM);
  if (!isStream || response.body === null) {
    void response.body?.cancel().catch(() => undefined);
    throw new FhirError(502, outcomeFor('exception', 'The back end did not return an event stream.'));
  }
  return { body: response.body };
}
