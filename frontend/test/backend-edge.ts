// The back end's own front door, modelled for the tests (WB4). The real stack refuses before any route
// runs, and a stand-in that answers whatever it is sent hides the refusal: a BFF route that POSTs with
// no body and no Content-Type passed every test and answered 415 on a real stack (BodyTypeMiddleware,
// backend/src/diucs/adapters/inbound/fhir_rest/errors.py).
//
// This file copies that rule: a POST or PUT whose body type is not application/json or
// application/fhir+json is refused with 415, whether or not it has a body, except the paths under
// /links/ and /webhooks/ (the link pages and the provider's webhooks, which have their own rules).
// test/setup.ts installs it next to the leak canary and asserts it after every test, so a call the real
// back end would refuse fails the test that made it, whatever the test was checking.
//
// If the rule changes at the back end, change it here in the same commit
// (test/backend-edge.test.ts reads the back end's source and fails when they differ).

const BACKEND_ORIGINS: ReadonlySet<string> = new Set(['http://backend.test']);
export const ACCEPTED_BODY_TYPES: ReadonlySet<string> = new Set(['application/fhir+json', 'application/json']);
export const BODY_METHODS: ReadonlySet<string> = new Set(['POST', 'PUT']);
export const EXEMPT_PATH_PREFIXES: readonly string[] = ['/webhooks/', '/links/'];

export type EdgeRefusal = { status: 415; method: string; url: string };
export type EdgeRequest = { method: string; url: string; headers: Headers };

/** The body type of a request: the Content-Type without parameters, in lower case, or '' when none. */
export function bodyTypeOf(headers: Headers): string {
  return (headers.get('content-type') ?? '').split(';', 1)[0]?.trim().toLowerCase() ?? '';
}

/** The refusal the back end would give this call, or null when it lets it through. Other origins are not its business. */
export function edgeRefusal(request: EdgeRequest): EdgeRefusal | null {
  let url: URL;
  try {
    url = new URL(request.url);
  } catch {
    return null;
  }
  if (!BACKEND_ORIGINS.has(url.origin)) return null;
  const method = request.method.toUpperCase();
  if (!BODY_METHODS.has(method)) return null;
  if (EXEMPT_PATH_PREFIXES.some((prefix) => url.pathname.startsWith(prefix))) return null;
  if (ACCEPTED_BODY_TYPES.has(bodyTypeOf(request.headers))) return null;
  return { status: 415, method, url: url.pathname };
}

const refused: EdgeRefusal[] = [];

export const backendEdge = {
  record(refusal: EdgeRefusal | null): void {
    if (refusal !== null) refused.push(refusal);
  },
  refusals(): EdgeRefusal[] {
    return [...refused];
  },
  /** Throws, naming each call by status, method and path, when the back end would have refused any. */
  assertClean(): void {
    if (refused.length === 0) return;
    const lines = refused.map((r) => `${r.status}: ${r.method} ${r.url}`);
    throw new Error(
      `The back end's body-type rule would have refused ${refused.length} call(s) (a POST or PUT needs Content-Type application/json or application/fhir+json, even with no body):\n${lines.join('\n')}`,
    );
  },
  reset(): void {
    refused.length = 0;
  },
};

type EventSource = {
  events: { on(event: 'request:start', listener: (arguments_: { request: Request }) => void): unknown };
};

/** Watches every request the MSW server sees. */
export function installBackendEdge(server: EventSource): void {
  server.events.on('request:start', ({ request }) => {
    backendEdge.record(edgeRefusal({ method: request.method, url: request.url, headers: request.headers }));
  });
}
