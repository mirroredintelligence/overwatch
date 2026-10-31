import type { OperationOutcome } from './types';

// Split from client.ts so a module the browser also loads can name the error without pulling in the
// server-only client (which reaches node:net through the visitor address, DEC-1311).
export class FhirError extends Error {
  readonly status: number;
  readonly outcome: OperationOutcome;
  /**
   * The JSON body of a refusal that is not an OperationOutcome (the reporter routes answer their own
   * `{result}` and `{code}` bodies on a 409), so a route can read what the back end said. Never shown
   * as it is: a route picks the fields it knows.
   */
  readonly payload?: unknown;
  /** The back end's `Retry-After` of a 429 or 503, whole seconds as text, or undefined. */
  readonly retryAfter?: string;

  constructor(status: number, outcome: OperationOutcome, extra: { payload?: unknown; retryAfter?: string } = {}) {
    super(`FHIR request failed with status ${status}`);
    this.name = 'FhirError';
    this.status = status;
    this.outcome = outcome;
    if (extra.payload !== undefined) this.payload = extra.payload;
    if (extra.retryAfter !== undefined) this.retryAfter = extra.retryAfter;
  }
}
