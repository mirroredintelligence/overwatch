import { newTraceparent } from './traceparent';
import type { OperationOutcome } from './types';

// Server-only client for the back end's FHIR R4B API. Route handlers and
// Server Components call it; the browser never does (contracts.md, Front end).

export type FhirInit = {
  /** Defaults to GET, or POST when a body is given. */
  method?: string;
  /** Serialised as JSON. */
  body?: unknown;
  /** Sent as `Authorization: Bearer <token>`. */
  token?: string;
  idempotencyKey?: string;
  /** An ETag such as `W/"3"`. */
  ifMatch?: string;
  /** Passed through unchanged; otherwise a new one is generated. */
  traceparent?: string;
  /**
   * The path is from the back end's root, not under /fhir (the terminology routes, R16). Only
   * this flag changes the base; the path is still checked to start with a slash.
   */
  root?: boolean;
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

/** The back end's origin and any prefix before /fhir: the base without its trailing /fhir. */
function rootUrl(): string {
  return baseUrl().replace(/\/fhir$/, '');
}

export async function fhirFetch<T>(path: string, init: FhirInit = {}): Promise<FhirResult<T>> {
  const url = `${init.root ? rootUrl() : baseUrl()}${path.startsWith('/') ? path : `/${path}`}`;
  const hasBody = init.body !== undefined;

  const headers = new Headers({
    Accept: FHIR_MEDIA_TYPE,
    traceparent: init.traceparent ?? newTraceparent(),
  });
  if (init.token) headers.set('Authorization', `Bearer ${init.token}`);
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
  init: FhirStreamInit = {},
): Promise<{ body: ReadableStream<Uint8Array> }> {
  const url = `${baseUrl()}${path.startsWith('/') ? path : `/${path}`}`;
  const headers = new Headers({ Accept: EVENT_STREAM, traceparent: init.traceparent ?? newTraceparent() });
  if (init.token) headers.set('Authorization', `Bearer ${init.token}`);

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
