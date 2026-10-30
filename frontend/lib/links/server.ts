import http from 'node:http';
import https from 'node:https';
import { parseOpenLink, type OpenLink, LinkShapeError } from './model';

// Server-only. The link pages' route handlers and Server Components call the back end's
// link API (`/links/...`, beside `/fhir`) through this module, never the browser.
//
// The tenant is the host a request was addressed to (DEC-134 item 3, DEC-167 item 1), so this
// module sends the browser's host to the back end as its Host header. The global fetch of
// Node ignores a Host header, so the request is made with node:http.

const BASE_URL_VARIABLE = 'DIUCS_FHIR_BASE_URL';
const FHIR_SUFFIX = '/fhir';
const HOST_SHAPE = /^[A-Za-z0-9.-]{1,253}(:\d{1,5})?$/;
const TIMEOUT_MS = 10_000;
const MAX_ANSWER_BYTES = 64 * 1024;

export class LinkApiError extends Error {
  readonly kind: 'unavailable' | 'bad-answer';

  constructor(kind: 'unavailable' | 'bad-answer') {
    super('The link could not be read from the back end.');
    this.name = 'LinkApiError';
    this.kind = kind;
  }
}

/**
 * The origin of the back end: the FHIR base URL without its `/fhir`, because the link routes
 * are not under the FHIR base. The message names the variable, never its value.
 */
export function backendRoot(value: string | undefined): string {
  if (!value) throw new Error(`${BASE_URL_VARIABLE} is not set, so the link pages cannot reach the back end.`);
  const trimmed = value.replace(/\/+$/, '');
  if (!trimmed.endsWith(FHIR_SUFFIX)) {
    throw new Error(`${BASE_URL_VARIABLE} must end in /fhir, because the link routes sit beside it.`);
  }
  return trimmed.slice(0, -FHIR_SUFFIX.length);
}

/**
 * The host a request was addressed to: the Host header, or the host of its own URL when the
 * header is absent (a request built without one). Never a value from the body or the query.
 */
export function hostOf(request: Request): string | null {
  const header = request.headers.get('host');
  if (header !== null) return header;
  try {
    return new URL(request.url).host;
  } catch {
    return null;
  }
}

export type LinkReply = { status: number; body: unknown; retryAfter?: string };

export type LinkCall = {
  method: 'GET' | 'POST';
  /** A path under the back end's origin, already encoded. */
  path: string;
  /** The host the request was addressed to: the tenant's own host. */
  host: string | null;
  body?: unknown;
  csrf?: string;
};

function jsonOrUndefined(text: string): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

/**
 * One call to the back end's link API. Rejects with LinkApiError when the back end cannot be
 * reached, or the host is not a host name; a missing base URL rejects too.
 */
export async function callLinkApi(call: LinkCall): Promise<LinkReply> {
  if (call.host === null || !HOST_SHAPE.test(call.host)) throw new LinkApiError('unavailable');
  const url = new URL(call.path, backendRoot(process.env[BASE_URL_VARIABLE]));
  const payload = call.body === undefined ? undefined : JSON.stringify(call.body);
  const headers: Record<string, string | number> = { Host: call.host, Accept: 'application/json' };
  if (payload !== undefined) {
    headers['Content-Type'] = 'application/json';
    headers['Content-Length'] = Buffer.byteLength(payload);
  }
  if (call.csrf !== undefined) headers['X-CSRF-Token'] = call.csrf;

  // Read at call time from the module object, so a test double of the transport is the one used.
  const transport = url.protocol === 'https:' ? https : http;
  return new Promise<LinkReply>((resolve, reject) => {
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
        response.on('error', () => reject(new LinkApiError('unavailable')));
      },
    );
    request.on('timeout', () => request.destroy(new LinkApiError('unavailable')));
    request.on('error', () => reject(new LinkApiError('unavailable')));
    if (payload !== undefined) request.write(payload);
    request.end();
  });
}

export type LinkState = { kind: 'open'; link: OpenLink } | { kind: 'gone' };

/** The link as the back end sees it for this host: open with its view, or gone (expired, used or unknown). */
export async function readLink(token: string, host: string | null): Promise<LinkState> {
  const reply = await callLinkApi({ method: 'GET', path: `/links/${encodeURIComponent(token)}`, host });
  if (reply.status === 410) return { kind: 'gone' };
  if (reply.status !== 200) throw new LinkApiError('unavailable');
  try {
    return { kind: 'open', link: parseOpenLink(reply.body) };
  } catch (error) {
    if (error instanceof LinkShapeError) throw new LinkApiError('bad-answer');
    throw error;
  }
}

const STATE_WORD = /^[a-z-]{1,24}$/;

/** The fields a page may read, per status. Anything else the back end sent is dropped. */
const FIELDS_BY_STATUS: Record<number, readonly string[]> = {
  200: [
    'bookingStatus',
    'changeToken',
    'serviceName',
    'value',
    'unitLabel',
    'recordedAt',
    'nextDue',
    'state',
    'purpose',
    'recordedValue',
    'asOf',
    'usualMin',
    'usualMax',
    'replyBy',
    'csrfToken',
  ],
  202: ['state'],
  400: ['state'],
  403: ['state'],
  409: ['state', 'reason', 'message'],
  410: ['state'],
  422: ['state', 'usualMin', 'usualMax'],
  429: ['state'],
};

/** What the browser is told: the status, and only the fields a page reads, or a fixed state word. */
export function publicReply(status: number, body: unknown): { status: number; body: Record<string, unknown> } {
  const fields = FIELDS_BY_STATUS[status];
  if (fields === undefined) {
    return { status, body: { state: status >= 500 ? 'error' : 'invalid' } };
  }
  const source = typeof body === 'object' && body !== null ? (body as Record<string, unknown>) : {};
  const out: Record<string, unknown> = {};
  for (const field of fields) {
    if (!(field in source)) continue;
    const value = source[field];
    if (field === 'state' && (typeof value !== 'string' || !STATE_WORD.test(value))) continue;
    out[field] = value;
  }
  return { status, body: out };
}
