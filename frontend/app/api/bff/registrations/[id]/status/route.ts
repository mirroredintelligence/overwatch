import { withBff } from '@/lib/bff/handler';
import { readStatus } from '@/lib/register/backend';
import { bffJson, refuse } from '@/lib/register/requests';

// The applicant's status after submitting (W27). The BFF passes on the fields the page shows, and
// nothing else the back end holds about the registration.

type Context = { params: Promise<{ id: string }> };

const ID = /^[A-Za-z0-9-]{1,64}$/;

function text(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

function strings(value: unknown): string[] | undefined {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : undefined;
}

const get = withBff<Context>(
  async (_request, session, context) => {
    const { id } = await context.params;
    if (!ID.test(id)) return refuse(404, 'not-found', 'We could not find that.');
    const raw = (await readStatus(session.backendToken, id)) as Record<string, unknown>;
    const body: Record<string, unknown> = { status: text(raw.status), serviceName: text(raw.serviceName) };
    if (text(raw.submittedAt)) body.submittedAt = raw.submittedAt;
    if (strings(raw.notes)) body.notes = strings(raw.notes);
    const from = raw.noteFrom as { role?: unknown; at?: unknown } | undefined;
    if (from && text(from.role) && text(from.at)) body.noteFrom = { role: from.role, at: from.at };
    if (text(raw.reason)) body.reason = raw.reason;
    if (text(raw.firstPromptAt)) body.firstPromptAt = raw.firstPromptAt;
    const details = raw.details as Record<string, unknown> | undefined;
    if (details) {
      const kept: Record<string, string> = {};
      for (const key of ['spoaPhone', 'criteriaOwner', 'reportingPhoneEnding'] as const) {
        if (text(details[key])) kept[key] = details[key] as string;
      }
      body.details = kept;
    }
    return bffJson(200, body);
  },
  { roles: ['reporter'] },
);

export async function GET(request: Request, context: Context): Promise<Response> {
  return get(request, context);
}
