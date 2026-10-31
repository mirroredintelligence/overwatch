import http from 'node:http';
import https from 'node:https';
import { normaliseHost } from '@/lib/auth/host';
import { getSecret, SecretConfigurationError, SecretNotFoundError, vaultConfigured } from '@/lib/secrets';

// Server-only. The calls to the back end that have no signed token to say whose they are: the token
// exchange at sign-in and the capacity link API. The tenant for such a call is the HOST the request
// was addressed to (DEC-134 item 3, DEC-167 item 1), so this module sends the browser's host to the
// back end as its Host header. The global fetch of Node ignores a Host header, so the request is made
// with node:http. This file and `client.ts` are the only places the front end talks to the back end.
//
// Two ways to say which tenant the call is for:
// - Locally and in tests the back end is reached directly, so the Host header carries it.
// - Behind the platform ingress (Azure Container Apps) the back end is addressed by its own internal
//   name: ingress routes on Host, so a Host naming the tenant would reach the wrong app. When
//   there is an `edge-origin` secret (Key Vault on the pilot, DEC-1304; DIUCS_EDGE_ORIGIN_SECRET when
//   there is no vault, as in local runs and tests) the tenant host goes in X-Forwarded-Host with the secret in X-Edge-Auth, which the back end's edge
//   middleware accepts only with the matching secret, and the visitor's address in CF-Connecting-IP.
//
// It never sends an Authorization header, a tenant header, a scope or a network: a call that needs a
// bearer token goes through `fhirFetch`.

const BASE_URL_VARIABLE = 'DIUCS_FHIR_BASE_URL';
const EDGE_SECRET = 'edge-origin';
const HEADER_SAFE = /^[\x21-\x7e]+$/;
const EDGE_HEADERS = ['x-forwarded-host', 'x-edge-auth', 'cf-connecting-ip'];
const ONE_ADDRESS = /^[0-9a-fA-F:.]{2,45}$/;
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

/**
 * The origin of the back end from this process's own setting. The one place besides `callBackend` that reads
 * the variable, for the calls that are not JSON calls with a tenant host (the Twilio webhook forward,
 * `lib/webhooks/forward.ts`). Throws as `backendRoot` does when it is not set.
 */
export function backendOrigin(): string {
  return backendRoot(process.env[BASE_URL_VARIABLE]);
}

export type BackendReply = { status: number; body: unknown; retryAfter?: string };

export type BackendCall = {
  method: 'GET' | 'POST';
  /** A path under the back end's origin, already encoded. */
  path: string;
  /** The host the request was addressed to: the tenant's own host. */
  host: string | null;
  /** The visitor's address, passed on behind the platform ingress for the rate limits. One address only. */
  clientIp?: string;
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
 * The edge secret, or null when this run has none and does not need one (no vault, no plain variable: the
 * back end is reached directly). With a vault a secret that is missing or unreadable is a fault, never a
 * call without the edge header: that call would resolve the tenant from the API's own host. A value that
 * could not be a header value is a fault too (the message names the secret, never the value).
 */
async function edgeSecret(): Promise<string | null> {
  let value: string;
  try {
    value = await getSecret(EDGE_SECRET);
  } catch (error) {
    if (error instanceof SecretNotFoundError && !vaultConfigured()) return null;
    throw error;
  }
  if (!HEADER_SAFE.test(value)) throw new SecretConfigurationError(`The secret ${EDGE_SECRET} is not a valid header value.`);
  return value;
}

/**
 * One call to the back end. Rejects with BackendCallError when the back end cannot be reached or the
 * host is not a host name; a missing base URL rejects too, and so does an edge secret that is missing or unreadable when there is a vault
 * (with that error, not BackendCallError: it is a fault of this app's set-up, not an outage of the back end).
 */
export async function callBackend(call: BackendCall): Promise<BackendReply> {
  const host = call.host === null ? null : normaliseHost(call.host);
  if (host === null) throw new BackendCallError('unavailable');
  const url = new URL(call.path, backendRoot(process.env[BASE_URL_VARIABLE]));
  const payload = call.body === undefined ? undefined : JSON.stringify(call.body);
  const edge = await edgeSecret();
  const headers: Record<string, string | number> = { Accept: 'application/json' };
  if (edge !== null) {
    headers['X-Forwarded-Host'] = host;
    headers['X-Edge-Auth'] = edge;
    if (call.clientIp !== undefined && ONE_ADDRESS.test(call.clientIp)) headers['CF-Connecting-IP'] = call.clientIp;
  } else {
    headers.Host = host;
  }
  if (payload !== undefined) {
    headers['Content-Type'] = 'application/json';
    headers['Content-Length'] = Buffer.byteLength(payload);
  } else if (call.method === 'POST') {
    // A POST with no body still names its body type: the back end answers 415 to one that does not (WB4).
    headers['Content-Type'] = 'application/json';
    headers['Content-Length'] = 0;
  }
  if (call.csrf !== undefined) headers['X-CSRF-Token'] = call.csrf;
  // Applied last, but never over the host that names the tenant, the edge headers or the length of the body.
  for (const [name, value] of Object.entries(call.headers ?? {})) {
    if (!['host', 'content-length', ...EDGE_HEADERS].includes(name.toLowerCase())) headers[name] = value;
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
