import { sessionFromRequest } from '@/lib/auth/session';
import { ALLOWED_ATTRIBUTES, ALLOWED_EVENTS } from '@/lib/telemetry/events';

// The ingest of the browser's ui.* events (O02). It keeps only what the allow-list names, forwards the
// batch to the OpenTelemetry collector when OTEL_HTTP_ENDPOINT is set, and otherwise discards it. It
// answers 204 for a batch it accepts, and never says what it kept or dropped.
//
// Tenancy: the browser never sends a tenant. The tenant.id attribute is written here, from the
// session, and any tenant.id the browser sent is dropped. No CSRF header is checked: sendBeacon cannot
// set one, and the endpoint changes no state. It requires a session and accepts only the allow-list.

const NO_STORE = { 'Cache-Control': 'no-store' };
const MAX_BODY_CHARS = 16 * 1024;
const MAX_EVENTS = 50;
const MAX_TEXT_CHARS = 100;

type Attribute = string | number | boolean;
type Event = { name: string; at: number; attributes: Record<string, Attribute> };

function attributesOf(value: unknown, tenantId: string): Record<string, Attribute> {
  const kept: Record<string, Attribute> = {};
  if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
    for (const [key, item] of Object.entries(value)) {
      if (!ALLOWED_ATTRIBUTES.includes(key)) continue;
      if (typeof item === 'number' && Number.isFinite(item)) kept[key] = item;
      else if (typeof item === 'boolean') kept[key] = item;
      else if (typeof item === 'string' && item.length <= MAX_TEXT_CHARS) kept[key] = item;
    }
  }
  kept['tenant.id'] = tenantId;
  return kept;
}

/** The events of a batch that are in scope, each with only its allowed attributes. */
function eventsOf(body: unknown, tenantId: string): Event[] {
  if (typeof body !== 'object' || body === null || !Array.isArray((body as { events?: unknown }).events)) {
    return [];
  }
  const events: Event[] = [];
  for (const item of (body as { events: unknown[] }).events.slice(0, MAX_EVENTS)) {
    if (typeof item !== 'object' || item === null) continue;
    const { name, at, attributes } = item as Record<string, unknown>;
    if (typeof name !== 'string' || !ALLOWED_EVENTS.includes(name)) continue;
    if (typeof at !== 'number' || !Number.isFinite(at)) continue;
    events.push({ name, at, attributes: attributesOf(attributes, tenantId) });
  }
  return events;
}

async function forward(events: Event[]): Promise<void> {
  const endpoint = process.env.OTEL_HTTP_ENDPOINT;
  if (!endpoint || events.length === 0) return;
  try {
    await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ events }),
      cache: 'no-store',
    });
  } catch {
    // The collector being down loses this batch. The browser is not told, and nothing is retried.
  }
}

export async function POST(request: Request): Promise<Response> {
  const origin = request.headers.get('origin');
  if (origin !== null && origin !== new URL(request.url).origin) {
    return new Response(null, { status: 403, headers: NO_STORE });
  }
  const session = await sessionFromRequest(request);
  if (!session) return new Response(null, { status: 401, headers: NO_STORE });

  const text = await request.text();
  if (text.length > MAX_BODY_CHARS) return new Response(null, { status: 413, headers: NO_STORE });
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    return new Response(null, { status: 400, headers: NO_STORE });
  }

  await forward(eventsOf(body, session.tenantId));
  return new Response(null, { status: 204, headers: NO_STORE });
}
