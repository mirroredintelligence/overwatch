import { describe, expect, it } from 'vitest';
import { FhirError } from '@/lib/fhir/client';
import type { OperationOutcome } from '@/lib/fhir/types';
import { toBffError } from './errors';

const conflict: OperationOutcome = {
  resourceType: 'OperationOutcome',
  issue: [{ severity: 'error', code: 'conflict', diagnostics: 'secret detail from the back end' }],
};

describe('toBffError', () => {
  it('turns a FhirError into a Response with the same status and the issue code', async () => {
    const response = toBffError(new FhirError(409, conflict));

    expect(response.status).toBe(409);
    expect(response.headers.get('content-type')).toContain('application/json');
    const body = (await response.json()) as { code: string; message: string };
    expect(body.code).toBe('conflict');
    expect(typeof body.message).toBe('string');
    expect(body.message.length).toBeGreaterThan(0);
  });

  it('never returns the back end diagnostics text', async () => {
    const response = toBffError(new FhirError(409, conflict));

    const text = await response.text();

    expect(text).not.toContain('secret');
    expect(text).not.toContain('diagnostics');
  });

  it('answers 500 with code exception for an unknown error, without its message', async () => {
    const response = toBffError(new Error('database password leaked here'));

    expect(response.status).toBe(500);
    const text = await response.text();
    expect(JSON.parse(text)).toMatchObject({ code: 'exception' });
    expect(text).not.toContain('password');
  });

  it('keeps the status of a transient back-end failure', async () => {
    const response = toBffError(
      new FhirError(503, {
        resourceType: 'OperationOutcome',
        issue: [{ severity: 'error', code: 'transient', diagnostics: 'Back end unreachable' }],
      }),
    );

    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({ code: 'transient' });
  });
});
