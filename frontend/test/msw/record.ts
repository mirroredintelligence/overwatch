// Keeps every request a BFF mock sees, so a test can assert what was sent and what was not.

export type SeenRequest = {
  method: string;
  path: string;
  search: string;
  body: unknown;
  csrf: string | null;
  idempotencyKey: string | null;
};

export async function recordInto(into: SeenRequest[], request: Request): Promise<SeenRequest> {
  const url = new URL(request.url);
  const text = request.method === 'GET' ? '' : await request.text();
  let body: unknown = undefined;
  if (text !== '') {
    try {
      body = JSON.parse(text) as unknown;
    } catch {
      body = text;
    }
  }
  const seen: SeenRequest = {
    method: request.method,
    path: url.pathname,
    search: url.search,
    body,
    csrf: request.headers.get('X-CSRF-Token'),
    idempotencyKey: request.headers.get('Idempotency-Key'),
  };
  into.push(seen);
  return seen;
}
