import http from 'node:http';
import https from 'node:https';
import { normaliseHost } from '@/lib/auth/host';

// Server-only. The calls to the back end that have no signed token to say whose they are: the token
// exchange at sign-in and the capacity link API. The tenant for such a call is the HOST the request
// was addressed to (DEC-134 item 3, DEC-167 item 1), so this module sends the browser's host to the
// back end as its Host header. The global fetch of Node ignores a Host header, so the request is made
// with node:http. This file and `client.ts` are the only places the front end talks to the back end.
//
// It never sends an Authorization header, a tenant header, a scope or a network: a call that needs a
// bearer token goes through `fhirFetch`.

const BASE_URL_VARIABLE = 'DIUCS_FHIR_BASE_URL';
const FHIR_SUFFIX = '/fhir';
const TIMEOUT_MS = 10_000;
const MAX_ANSWER_BYTES = 64 * 1024;

export class BackendCallError extends Error {
  readonly kind: 'unavailable' | 'bad-answer';

  constructor(kind: 'unavailable' | 'bad-answer') {
    super('The back end could not be reached.');
    this.name = 'BackendCallError';
    this.kind = kind;
  }
}

/**
 * The origin of the back end: the FHIR base URL without its `/fhir`, because these routes are not
 * under the FHIR base. The message names the variable, never its value.
 */
export function backendRoot(value: string | undefined): string {
  if (!value) throw new Error(`${BASE_URL_VARIABLE} is not set, so the back end cannot be called.`);
  const trimmed = value.replace(/\/+$/, '');
  if (!trimmed.endsWith(FHIR_SUFFIX)) {
    throw new Error(`${BASE_URL_VARIABLE} must end in /fhir, because the routes called here sit beside it.`);
  }
  return trimmed.slice(0, -FHIR_SUFFIX.length);
}

export type BackendReply = { status: number; body: unknown; retryAfter?: string };

export type BackendCall = {
  method: 'GET' | 'POST';
  /** A path under the back end's origin, already encoded. */
  path: string;
  /** The host the request was addressed to: the tenant's own host. */
  host: string | null;
  body?: unknown;
  csrf?: string;
  /** Further request headers, such as `Authorization` or `X-Screen-Secret` (the screen and token routes). */
  headers?: Record<string, string>;
};

function jsonOrUndefined(text: string): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

/**
 * One call to the back end. Rejects with BackendCallError when the back end cannot be reached or the
 * host is not a host name; a missing base URL rejects too.
 */
export async function callBackend(call: BackendCall): Promise<BackendReply> {
  const host = call.host === null ? null : normaliseHost(call.host);
  if (host === null) throw new BackendCallError('unavailable');
  const url = new URL(call.path, backendRoot(process.env[BASE_URL_VARIABLE]));
  const payload = call.body === undefined ? undefined : JSON.stringify(call.body);
  const headers: Record<string, string | number> = { Host: host, Accept: 'application/json' };
  if (payload !== undefined) {
    headers['Content-Type'] = 'application/json';
    headers['Content-Length'] = Buffer.byteLength(payload);
  }
  if (call.csrf !== undefined) headers['X-CSRF-Token'] = call.csrf;
  // Applied last, but never over the host that names the tenant or the length of the body.
  for (const [name, value] of Object.entries(call.headers ?? {})) {
    if (!['host', 'content-length'].includes(name.toLowerCase())) headers[name] = value;
  }

  // Read at call time from the module object, so a test double of the transport is the one used.
  const transport = url.protocol === 'https:' ? https : http;
  return new Promise<BackendReply>((resolve, reject) => {
    const request = transport.request(
      url,
      { method: call.method, headers, timeout: TIMEOUT_MS },
      (response) => {
        const chunks: Buffer[] = [];
        let size = 0;
        response.on('data', (chunk: Buffer) => {
          size += chunk.length;
          if (size <= MAX_ANSWER_BYTES) chunks.push(chunk);
        });
        response.on('end', () => {
          const retry = response.headers['retry-after'];
          resolve({
            status: response.statusCode ?? 0,
            body: jsonOrUndefined(Buffer.concat(chunks).toString('utf8')),
            retryAfter: typeof retry === 'string' ? retry : undefined,
          });
        });
        response.on('error', () => reject(new BackendCallError('unavailable')));
      },
    );
    request.on('timeout', () => request.destroy(new BackendCallError('unavailable')));
    request.on('error', () => reject(new BackendCallError('unavailable')));
    if (payload !== undefined) request.write(payload);
    request.end();
  });
}
