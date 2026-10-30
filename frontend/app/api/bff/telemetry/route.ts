import { sessionFromRequest, type Session } from '@/lib/auth/session';
import { ALLOWED_ATTRIBUTES, ALLOWED_EVENTS } from '@/lib/telemetry/events';

// The ingest of the browser's ui.* events (O02). It keeps only what the allow-list names, forwards the
// batch to the OpenTelemetry collector's logs receiver when OTEL_HTTP_ENDPOINT is set (the collector's
// base address), and otherwise discards it. It
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

function tenantIdOf(session: Session): string | undefined {
  const { tenantId } = session as Session & { tenantId?: unknown };
  return typeof tenantId === 'string' && tenantId !== '' ? tenantId : undefined;
}

function attributesOf(value: unknown, tenantId: string | undefined): Record<string, Attribute> {
  const kept: Record<string, Attribute> = {};
  if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
    for (const [key, item] of Object.entries(value)) {
      if (!ALLOWED_ATTRIBUTES.includes(key)) continue;
      if (typeof item === 'number' && Number.isFinite(item)) kept[key] = item;
      else if (typeof item === 'boolean') kept[key] = item;
      else if (typeof item === 'string' && item.length <= MAX_TEXT_CHARS) kept[key] = item;
    }
  }
  if (tenantId !== undefined) kept['tenant.id'] = tenantId;
  return kept;
}

/** The events of a batch that are in scope, each with only its allowed attributes. */
function eventsOf(body: unknown, tenantId: string | undefined): Event[] {
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

// The batch goes to the collector's OTLP logs receiver as OTLP/JSON. ui.* events are log records
// (DEC-331 item 5 keeps them in the logs pipeline), and the collector's receivers accept OTLP only
// (known issue O04). Each event becomes one log record: its name is the body, and its allow-listed
// attributes, plus the event name, are the attributes.
const OTLP_LOGS_PATH = '/v1/logs';
const NANOSECONDS_PER_MILLISECOND = BigInt(1_000_000);

type OtlpValue = { stringValue: string } | { doubleValue: number } | { boolValue: boolean };

function otlpValue(value: Attribute): OtlpValue {
  if (typeof value === 'number') return { doubleValue: value };
  if (typeof value === 'boolean') return { boolValue: value };
  return { stringValue: value };
}

/** The batch as one OTLP/JSON request to the logs receiver. */
export function otlpLogs(events: Event[]): unknown {
  return {
    resourceLogs: [
      {
        resource: { attributes: [{ key: 'service.name', value: { stringValue: 'diucs-browser' } }] },
        scopeLogs: [
          {
            scope: { name: 'diucs.ui' },
            logRecords: events.map((event) => {
              const time = (BigInt(Math.round(event.at)) * NANOSECONDS_PER_MILLISECOND).toString();
              return {
                timeUnixNano: time,
                observedTimeUnixNano: time,
                body: { stringValue: event.name },
                attributes: [
                  { key: 'event.name', value: { stringValue: event.name } },
                  ...Object.entries(event.attributes).map(([key, value]) => ({ key, value: otlpValue(value) })),
                ],
              };
            }),
          },
        ],
      },
    ],
  };
}

async function forward(events: Event[]): Promise<void> {
  const base = process.env.OTEL_HTTP_ENDPOINT;
  if (!base || events.length === 0) return;
  try {
    await fetch(`${base.replace(/\/+$/, '')}${OTLP_LOGS_PATH}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(otlpLogs(events)),
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

  await forward(eventsOf(body, tenantIdOf(session)));
  return new Response(null, { status: 204, headers: NO_STORE });
}
