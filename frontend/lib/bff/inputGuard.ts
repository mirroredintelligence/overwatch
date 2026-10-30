// Inputs that name a tenant, a scope or a network are refused (TEN-044, DEC-130 item 3, DEC-132).
//
// The tenant of a BFF request is the session's, and the scope is the route (`/api/bff/network/...`),
// so nothing a caller sends may choose either. A query parameter, a header or a JSON or form body key
// that names one is a sign of a client that is wrong or hostile, and is refused with a 400 before the
// handler runs. The check is on KEY NAMES only (a value such as `?q=network` is data), and the names
// are compared without case, dashes, underscores, dots or brackets, so `tenant_id`, `Tenant-Id`,
// `tenant.id` and `tenant[id]` are one name.

const MAX_BODY_BYTES = 128 * 1024;
const MAX_DEPTH = 12;
const MAX_NODES = 5000;
const SEPARATORS = /[-_.[\]\s]/g;

function normalise(name: string): string {
  return name.toLowerCase().replace(SEPARATORS, '');
}

/** True for a key that chooses a tenant, a scope or a network. */
export function namesTenantInput(name: string): boolean {
  const key = normalise(name);
  return key === 'source' || key.startsWith('tenant') || key.startsWith('scope') || key.startsWith('network') || key.startsWith('sourcetenant');
}

const HEADER_NAME = /^(x-)?(tenant|scope|network|source-tenant)/i;

function headersName(request: Request): boolean {
  for (const name of request.headers.keys()) if (HEADER_NAME.test(name)) return true;
  return false;
}

function queryNames(request: Request): boolean {
  try {
    for (const key of new URL(request.url).searchParams.keys()) if (namesTenantInput(key)) return true;
  } catch {
    return true;
  }
  return false;
}

// Reads at most MAX_BODY_BYTES of a copy of the body. Null when it is larger (the check cannot be
// made, so the request is refused).
async function readBounded(request: Request): Promise<string | null> {
  const declared = Number(request.headers.get('content-length'));
  if (Number.isFinite(declared) && declared > MAX_BODY_BYTES) return null;
  const body = request.clone().body;
  if (body === null) return '';
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let size = 0;
  let text = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_BODY_BYTES) {
      // Not awaited: a cancel on one branch of a copied body settles only when the other is read or
      // cancelled too, and the other belongs to the handler, which is never reached on this path.
      void reader.cancel().catch(() => undefined);
      return null;
    }
    text += decoder.decode(value, { stream: true });
  }
  return text + decoder.decode();
}

/** True when a parsed JSON value has a key that names one, or is too deep or too large to check. */
function jsonNames(value: unknown): boolean {
  let nodes = 0;
  const walk = (node: unknown, depth: number): boolean => {
    if (typeof node !== 'object' || node === null) return false;
    nodes += 1;
    if (depth > MAX_DEPTH || nodes > MAX_NODES) return true;
    if (Array.isArray(node)) return node.some((item) => walk(item, depth + 1));
    for (const [key, item] of Object.entries(node)) {
      if (namesTenantInput(key) || walk(item, depth + 1)) return true;
    }
    return false;
  };
  return walk(value, 0);
}

async function bodyNames(request: Request): Promise<boolean> {
  if (request.method === 'GET' || request.method === 'HEAD') return false;
  const type = (request.headers.get('content-type') ?? '').toLowerCase();
  const isJson = type.includes('json');
  const isForm = type.includes('application/x-www-form-urlencoded');
  if (!isJson && !isForm) return false;

  const text = await readBounded(request);
  if (text === null) return true;
  if (isForm) {
    for (const key of new URLSearchParams(text).keys()) if (namesTenantInput(key)) return true;
    return false;
  }
  try {
    return jsonNames(JSON.parse(text));
  } catch {
    // Not JSON: nothing here names anything, and the handler will refuse it in its own words.
    return false;
  }
}

export async function refusesTenantInput(request: Request): Promise<boolean> {
  return queryNames(request) || headersName(request) || (await bodyNames(request));
}
