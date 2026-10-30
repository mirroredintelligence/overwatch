import { FhirError } from '@/lib/fhir/client';

// Turns any error thrown by a route handler into the response the browser
// sees. The body holds a code and a fixed message only: never the back end's
// diagnostics, a URL, or an error's own text (DIUCS privacy rules).
//
// Another tenant's record reads as NotFound (DEC-130 item 7), never Forbidden: on a route that takes
// an id (`idScoped`), a 403 and a 404 from the back end are the same 404 with the same words, so a
// caller cannot tell an id that is in another tenant from an id that is nowhere.

type BffErrorBody = { code: string; message: string };

export type BffErrorOptions = {
  /** The route takes an id from the caller: a refusal must not say that the id exists. */
  idScoped?: boolean;
};

const MESSAGES: Record<number, string> = {
  400: 'The request was not valid.',
  401: 'Please sign in again.',
  403: 'You cannot do that.',
  404: 'We could not find that.',
  409: 'That changed while you were working. Reload and try again.',
  412: 'That changed while you were working. Reload and try again.',
  422: 'The request could not be processed.',
  428: 'The request needs the latest version. Reload and try again.',
  503: 'The service is unavailable. Try again shortly.',
};

const FALLBACK_CLIENT_MESSAGE = 'The request could not be completed.';
const FALLBACK_SERVER_MESSAGE = 'Something went wrong. Try again.';
const NOT_FOUND_CODE = 'not-found';

// FHIR issue codes are short lower-case words. Anything else is not echoed.
const ISSUE_CODE = /^[a-z-]{1,40}$/;

function messageFor(status: number): string {
  return MESSAGES[status] ?? (status >= 500 ? FALLBACK_SERVER_MESSAGE : FALLBACK_CLIENT_MESSAGE);
}

function codeFor(error: FhirError): string {
  const code = error.outcome.issue?.[0]?.code;
  if (typeof code === 'string' && ISSUE_CODE.test(code)) return code;
  return error.status >= 500 ? 'exception' : 'invalid';
}

export function toBffError(error: unknown, options: BffErrorOptions = {}): Response {
  let status =
    error instanceof FhirError && error.status >= 400 && error.status <= 599 ? error.status : 500;
  if (options.idScoped === true && status === 403) status = 404;
  // A 404 has one code, whatever the back end called it, so two kinds of "not here" cannot differ.
  const code =
    status === 404
      ? NOT_FOUND_CODE
      : error instanceof FhirError && status === error.status
        ? codeFor(error)
        : 'exception';
  const body: BffErrorBody = { code, message: messageFor(status) };

  return Response.json(body, { status, headers: { 'Content-Type': 'application/json' } });
}
