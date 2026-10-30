import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { idempotencyKeyOf, invalidRequest, routeId } from '@/lib/lead/bffInput';

// Sends a test prompt to the service's reporter (W18): by its channel, or by the channel the body names
// (text, email or push). Lead only, CSRF on the POST. The back end answers 409 inside a minute of the last one.
// The answer names the channel and the last four digits of the number, never the number.

type Context = { params: Promise<Record<string, string>> };

const CHANNELS = ['text', 'email', 'push'] as const;

async function optionalChannel(request: Request): Promise<{ channel?: string }> {
  const raw = await request.text();
  if (raw.trim() === '') return {};
  let body: unknown;
  try {
    body = JSON.parse(raw);
  } catch {
    throw invalidRequest();
  }
  if (typeof body !== 'object' || body === null || Array.isArray(body)) throw invalidRequest();
  const keys = Object.keys(body);
  if (keys.some((key) => key !== 'channel')) throw invalidRequest();
  const channel = (body as { channel?: unknown }).channel;
  if (channel === undefined) return {};
  if (typeof channel !== 'string' || !(CHANNELS as readonly string[]).includes(channel)) throw invalidRequest();
  return { channel };
}

const post = withBff<Context>(
  async (request, session, context) => {
    const id = await routeId(context, 'id');
    const key = idempotencyKeyOf(request);
    const body = await optionalChannel(request);
    const { data } = await fhirFetch<{ channel?: unknown; numberEnding?: unknown }>(
      `/lead/services/${encodeURIComponent(id)}/test-prompt`,
      { method: 'POST', root: true, body, token: session.backendToken, idempotencyKey: key },
    );
    return Response.json(
      { channel: data.channel, numberEnding: data.numberEnding },
      { headers: { 'Cache-Control': 'no-store' } },
    );
  },
  { idScoped: true, roles: ['lead'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
