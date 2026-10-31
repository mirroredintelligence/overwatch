import { backendOrigin } from '@/lib/fhir/hostCall';

// Server only (the ESLint rule that keeps components away from lib/secrets keeps them away from this).
//
// The Twilio webhook forward (DEC-1302). Twilio calls `web`, the one app the internet reaches, at the two
// public paths below; `api` is internal. This passes the form and the signature on and answers with what
// the back end answered. It is a public pre-session door with nothing to prove who is calling: the
// `X-Twilio-Signature` is the authentication, and the BACK END checks it (over its public base URL plus the
// path, with the auth token of the subaccount the number called belongs to) and finds the tenant from that
// number, never from the host, a header or a query. So this module does none of that and must not:
//
// - The path is chosen here, from the two-entry table, and never built from the request. The query string
//   is not forwarded (the back end refuses one).
// - The body is read once as bytes and sent as the same bytes: never parsed, decoded or encoded again, since
//   the signature is over the exact fields.
// - Only `Content-Type` and `X-Twilio-Signature` are sent on. No cookie, no Authorization, no X-Forwarded-*,
//   no tenant header, no edge secret, and the Host is the back end's own (global fetch sends the URL's host).
// - A redirect is a failure (`redirect: 'manual'`), the wait is 10 seconds, the form and the answer are each
//   at most 64 KiB (the back end's own limit for a form).
// - The answer carries the back end's status, body and Content-Type, and `Cache-Control: no-store`; no other
//   header of the back end is passed on. The back end's 500 for a queue that failed passes through as it is,
//   so Twilio's retry is not taken for a replay.
// - The log line is the path name and the status, and nothing else.

export const MAX_FORM_BYTES = 64 * 1024;
export const MAX_ANSWER_BYTES = 64 * 1024;
export const TIMEOUT_MS = 10_000;

/** The two paths, and nothing else, that are forwarded. The back end's REPLY_PATH and STATUS_PATH. */
export const WEBHOOK_PATHS = {
  reply: '/webhooks/sms/twilio',
  status: '/webhooks/sms/twilio/status',
} as const;

export type WebhookTarget = keyof typeof WEBHOOK_PATHS;

const NO_STORE = 'no-store';
// A status whose answer cannot carry a body.
const NO_BODY = new Set([101, 204, 205, 304]);

type Capped = { kind: 'bytes'; bytes: Uint8Array } | { kind: 'too-large' };

function answer(status: number, body: BodyInit | null = null, contentType: string | null = null): Response {
  const headers = new Headers({ 'Cache-Control': NO_STORE });
  if (contentType !== null) headers.set('Content-Type', contentType);
  return new Response(NO_BODY.has(status) ? null : body, { status, headers });
}

function logged(path: string, status: number): void {
  if (status >= 200 && status < 300) return;
  console.warn(`twilio webhook forward: path=${path} status=${status}`);
}

function finish(path: string, response: Response): Response {
  logged(path, response.status);
  return response;
}

/** Reads a body, stopping as soon as it is over `limit` bytes (the rest is never pulled). */
async function readCapped(stream: ReadableStream<Uint8Array> | null, limit: number): Promise<Capped> {
  if (stream === null) return { kind: 'bytes', bytes: new Uint8Array(0) };
  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > limit) {
      // Not waited for: a cancel that is slow to settle must not hold the answer.
      reader.cancel().catch(() => undefined);
      return { kind: 'too-large' };
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return { kind: 'bytes', bytes };
}

/** The answer for a method or path that is not a forward: 404, empty. The same for every one of them. It looks at nothing it is given. */
export function notFound(...ignored: unknown[]): Response {
  void ignored;
  return answer(404);
}

/**
 * Forwards one Twilio POST to the back end and returns the answer for Twilio. Never throws: whatever goes
 * wrong is an empty 4xx or 5xx (Twilio retries a 5xx, and does not retry a 4xx).
 */
export async function forwardTwilioWebhook(request: Request, target: WebhookTarget): Promise<Response> {
  const path = WEBHOOK_PATHS[target];

  const contentType = request.headers.get('content-type');
  if (contentType === null || contentType === '') return finish(path, answer(400));
  const declared = request.headers.get('content-length');
  if (declared !== null && (!/^\d+$/.test(declared) || Number(declared) > MAX_FORM_BYTES)) return finish(path, answer(413));

  let url: URL;
  try {
    url = new URL(path, backendOrigin());
  } catch {
    // The back end's address is not set or not usable: a fault of this app's set-up, not an outage.
    return finish(path, answer(500));
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const form = await readCapped(request.body, MAX_FORM_BYTES);
    if (form.kind === 'too-large') return finish(path, answer(413));

    const headers = new Headers({ 'Content-Type': contentType });
    const signature = request.headers.get('x-twilio-signature');
    if (signature !== null) headers.set('X-Twilio-Signature', signature);

    let upstream: Response;
    try {
      upstream = await fetch(url, {
        method: 'POST',
        headers,
        body: form.bytes as BodyInit,
        redirect: 'manual',
        signal: controller.signal,
      });
    } catch {
      return finish(path, answer(502));
    }

    // A redirect is a failure, never followed. (`opaqueredirect` is what a browser-like client reports.)
    if (upstream.type === 'opaqueredirect' || (upstream.status >= 300 && upstream.status < 400)) {
      upstream.body?.cancel().catch(() => undefined);
      return finish(path, answer(502));
    }

    let body: Capped;
    try {
      body = await readCapped(upstream.body, MAX_ANSWER_BYTES);
    } catch {
      return finish(path, answer(502));
    }
    if (body.kind === 'too-large') return finish(path, answer(502));
    return finish(path, answer(upstream.status, body.bytes as BodyInit, upstream.headers.get('content-type')));
  } catch {
    return finish(path, answer(502));
  } finally {
    clearTimeout(timer);
  }
}
