import { type LinkAnswer, type LinkAnswered, type LinkView, parseLinkAnswered, parseLinkView } from './model';

// The browser's calls to the link pages' BFF (`/api/bff/links/[token]`). Each answers with what the
// page needs to show, and nothing else: a token, a hash or a tenant never comes back through here.

export type AnswerOutcome =
  | { kind: 'recorded'; answered: LinkAnswered }
  | { kind: 'out-of-range'; usualMin: number; usualMax: number }
  | { kind: 'send-number' }
  | { kind: 'gone' }
  | { kind: 'rate-limited' }
  | { kind: 'failed' };

const base = (token: string) => `/api/bff/links/${encodeURIComponent(token)}`;

export type LinkRead = { kind: 'open'; view: LinkView } | { kind: 'gone' } | { kind: 'unavailable' };

/**
 * Reads the link through the BFF: the browser's own request, so the CSRF cookie for this link is set
 * by a response the browser asked for. One back-end read per page view (DEC-167 item 8 limits them).
 */
export async function readLinkView(token: string): Promise<LinkRead> {
  let response: Response;
  try {
    response = await fetch(base(token), { method: 'GET', cache: 'no-store', credentials: 'same-origin' });
  } catch {
    return { kind: 'unavailable' };
  }
  if (response.status === 410) return { kind: 'gone' };
  if (!response.ok) return { kind: 'unavailable' };
  try {
    return { kind: 'open', view: parseLinkView(await response.json()) };
  } catch {
    return { kind: 'unavailable' };
  }
}

async function bodyOf(response: Response): Promise<unknown> {
  try {
    return (await response.json()) as unknown;
  } catch {
    return undefined;
  }
}

/** Sends one answer. The outcome says what the page should show; nothing from the answer is kept. */
export async function sendAnswer(token: string, csrf: string, answer: LinkAnswer): Promise<AnswerOutcome> {
  let response: Response;
  try {
    response = await fetch(base(token), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      body: JSON.stringify(answer),
      cache: 'no-store',
      credentials: 'same-origin',
    });
  } catch {
    return { kind: 'failed' };
  }
  const body = await bodyOf(response);
  switch (response.status) {
    case 200:
      try {
        return { kind: 'recorded', answered: parseLinkAnswered(body) };
      } catch {
        return { kind: 'failed' };
      }
    case 422: {
      const range = body as { usualMin?: unknown; usualMax?: unknown } | undefined;
      if (typeof range?.usualMin === 'number' && typeof range.usualMax === 'number') {
        return { kind: 'out-of-range', usualMin: range.usualMin, usualMax: range.usualMax };
      }
      return { kind: 'failed' };
    }
    case 409:
      return { kind: 'send-number' };
    case 410:
      return { kind: 'gone' };
    case 429:
      return { kind: 'rate-limited' };
    default:
      return { kind: 'failed' };
  }
}

/** Asks for a new link to an expired link. The back end answers 202 for every token; 429 when the budget is spent. */
export async function requestRenew(token: string): Promise<'accepted' | 'rate-limited' | 'failed'> {
  try {
    const response = await fetch(`${base(token)}/renew`, { method: 'POST', cache: 'no-store', credentials: 'same-origin' });
    if (response.status === 202) return 'accepted';
    return response.status === 429 ? 'rate-limited' : 'failed';
  } catch {
    return 'failed';
  }
}
