import type { OperationOutcome } from './types';

export type FhirInit = {
  method?: string;
  body?: unknown;
  token?: string;
  idempotencyKey?: string;
  ifMatch?: string;
  traceparent?: string;
};

export type FhirResult<T> = { data: T; etag?: string };

export class FhirError extends Error {
  readonly status: number;
  readonly outcome: OperationOutcome;

  constructor(status: number, outcome: OperationOutcome) {
    super(`FHIR request failed with status ${status}`);
    this.name = 'FhirError';
    this.status = status;
    this.outcome = outcome;
  }
}

// Red stub (DEC-010): the behaviour is written after the tests fail.
export async function fhirFetch<T>(_path: string, _init: FhirInit = {}): Promise<FhirResult<T>> {
  throw new Error('fhirFetch is not implemented yet');
}
