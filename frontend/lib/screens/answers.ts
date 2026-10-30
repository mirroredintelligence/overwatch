import { ScreenApiError } from './server';

// What the browser is told when a screen route fails: a status, a code and words of our own, never
// anything the back end said, and no detail of what failed.

export const NO_STORE = { 'Cache-Control': 'no-store' };
const GENERIC_NOT_FOUND = 'We could not find that.';
export const THROTTLED_MESSAGE = 'Too many attempts. Wait a few minutes and try again.';
export const UNAVAILABLE_MESSAGE = 'Pairing is not available right now. Try again shortly.';
export const INVALID_MESSAGE = 'Check the screen name and where it is. Do not include patient information.';

export function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return Response.json(body, { status, headers: { ...NO_STORE, ...headers } });
}

export const notFound = (message: string = GENERIC_NOT_FOUND) => json(404, { code: 'not-found', message });
export const refuse = (status: number, code: string, message: string) => json(status, { code, message });

export function screenFailure(error: unknown, options: { notFound?: string } = {}): Response {
  if (error instanceof ScreenApiError) {
    switch (error.kind) {
      case 'not-found':
        return notFound(options.notFound);
      case 'throttled':
        return json(429, { code: 'throttled', message: THROTTLED_MESSAGE }, error.retryAfter === undefined ? {} : { 'Retry-After': error.retryAfter });
      case 'invalid':
        return json(422, { code: 'invalid', field: 'name', message: INVALID_MESSAGE });
      case 'unauthorised':
        return json(401, { code: 'no-session', message: 'Please sign in again.' });
      default:
        return json(503, { code: 'unavailable', message: UNAVAILABLE_MESSAGE });
    }
  }
  // A set-up fault (a missing setting): a fixed word in the log, never a value.
  console.error('screen request failed: fault');
  return json(500, { code: 'exception', message: 'Something went wrong. Try again.' });
}
