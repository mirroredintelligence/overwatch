import { withTraceparent } from '@/lib/telemetry/trace';

// The browser's calls to the check-in page's BFF (`/api/bff/checkin/[token]`, DEC-1346). Each answers with what the page
// needs and nothing else: a token, a hash or a tenant never comes back through here. The CSRF cookie is HttpOnly and
// only this code's BFF path receives it; the page sends the token it was given in X-CSRF-Token.

export type CheckinRead = { kind: 'ready'; service: string; csrfToken: string } | { kind: 'gone' } | { kind: 'unavailable' };

export type CheckinStep =
  | { kind: 'sent' }
  | { kind: 'on-shift'; service: string; until: string | null }
  | { kind: 'off-shift' }
  | { kind: 'code-wrong' }
  | { kind: 'invalid' }
  | { kind: 'gone' }
  | { kind: 'rate-limited' }
  | { kind: 'failed' };

const base = (token: string) => `/api/bff/checkin/${encodeURIComponent(token)}`;

const isObject = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);

async function bodyOf(response: Response): Promise<Record<string, unknown>> {
  try {
    const parsed = (await response.json()) as unknown;
    return isObject(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

/** The browser's one read of the code: which service it is for, and the token its writes carry. */
export async function readCheckin(token: string): Promise<CheckinRead> {
  let response: Response;
  try {
    response = await fetch(base(token), withTraceparent({ method: 'GET', cache: 'no-store', credentials: 'same-origin' }));
  } catch {
    return { kind: 'unavailable' };
  }
  if (response.status === 410) return { kind: 'gone' };
  if (!response.ok) return { kind: 'unavailable' };
  const body = await bodyOf(response);
  if (typeof body.service !== 'string' || typeof body.csrfToken !== 'string') return { kind: 'unavailable' };
  return { kind: 'ready', service: body.service, csrfToken: body.csrfToken };
}

async function write(token: string, step: 'code' | 'confirm', csrfToken: string, body: Record<string, unknown>): Promise<CheckinStep> {
  let response: Response;
  try {
    response = await fetch(
      `${base(token)}/${step}`,
      withTraceparent({
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
        body: JSON.stringify(body),
        cache: 'no-store',
        credentials: 'same-origin',
      }),
    );
  } catch {
    return { kind: 'failed' };
  }
  const answer = await bodyOf(response);
  switch (response.status) {
    case 200:
      if (answer.state === 'off-shift') return { kind: 'off-shift' };
      if (answer.state === 'on-shift' && typeof answer.service === 'string') {
        return { kind: 'on-shift', service: answer.service, until: typeof answer.until === 'string' ? answer.until : null };
      }
      return { kind: 'failed' };
    case 202:
      return { kind: 'sent' };
    case 400:
      return { kind: 'invalid' };
    case 403:
      return answer.state === 'code-wrong' ? { kind: 'code-wrong' } : { kind: 'failed' };
    case 410:
      return { kind: 'gone' };
    case 429:
      return { kind: 'rate-limited' };
    default:
      return { kind: 'failed' };
  }
}

/** Asks for a six-digit code by text to this number. The answer is the same for any number. */
export function sendCheckinCode(token: string, csrfToken: string, mobile: string): Promise<CheckinStep> {
  return write(token, 'code', csrfToken, { mobile });
}

/** Goes on shift (for `hours`) or off shift with the code that was texted. */
export function confirmCheckin(
  token: string,
  csrfToken: string,
  entry: { mobile: string; code: string; action: 'on' | 'off'; hours?: number },
): Promise<CheckinStep> {
  return write(token, 'confirm', csrfToken, entry);
}
