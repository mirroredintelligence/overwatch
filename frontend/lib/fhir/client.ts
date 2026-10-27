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

export async function fhirFetch<T>(path: string, init: FhirInit = {}): Promise<FhirResult<T>> {
  const url = `${baseUrl()}${path.startsWith('/') ? path : `/${path}`}`;
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

  if (!response.ok) {
    const parsed = text ? tryParseJson(text) : { ok: false as const };
    const outcome =
      parsed.ok && isOperationOutcome(parsed.value)
        ? parsed.value
        : outcomeFor('exception', `HTTP ${response.status}`);
    throw new FhirError(response.status, outcome);
  }

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
