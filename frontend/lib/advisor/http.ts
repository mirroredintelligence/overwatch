// Server-only helpers shared by the advisor BFF route handlers.

// An Idempotency-Key the browser generated for one action: opaque, 8 to 64 URL-safe characters.
const IDEMPOTENCY_KEY = /^[A-Za-z0-9_-]{8,64}$/;

/** The idempotency key on the request, or null when it is missing or malformed. */
export function idempotencyKeyOf(request: Request): string | null {
  const key = request.headers.get('Idempotency-Key');
  return key !== null && IDEMPOTENCY_KEY.test(key) ? key : null;
}

const NO_STORE = { 'Cache-Control': 'no-store' };

export function refuse(status: number, code: string): Response {
  return Response.json({ code }, { status, headers: NO_STORE });
}

export function answer(body: unknown, status = 200): Response {
  return Response.json(body, { status, headers: NO_STORE });
}
