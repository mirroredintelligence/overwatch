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

describe('toBffError on a route that takes an id (TEN-044)', () => {
  const outcome = (code: string, diagnostics = 'detail'): OperationOutcome => ({
    resourceType: 'OperationOutcome',
    issue: [{ severity: 'error', code, diagnostics }],
  });
  const body = async (response: Response) => (await response.json()) as { code: string; message: string };

  it.each([
    [404, 'not-found'],
    [403, 'forbidden'],
    [403, 'security'],
    [404, 'something-the-back-end-added'],
  ])('answers one 404 for a %s with code %s: no way to tell another tenant\'s id from no id', async (status, code) => {
    const response = toBffError(new FhirError(status, outcome(code)), { idScoped: true });
    expect(response.status).toBe(404);
    expect(await body(response)).toEqual({ code: 'not-found', message: 'We could not find that.' });
  });

  it('does not touch the other statuses', async () => {
    expect(toBffError(new FhirError(409, outcome('conflict')), { idScoped: true }).status).toBe(409);
    expect(toBffError(new FhirError(503, outcome('transient')), { idScoped: true }).status).toBe(503);
    expect(toBffError(new FhirError(401, outcome('login')), { idScoped: true }).status).toBe(401);
  });

  it('keeps a 403 a 403 when the route takes no id', async () => {
    const response = toBffError(new FhirError(403, outcome('forbidden')));
    expect(response.status).toBe(403);
    expect(await body(response)).toMatchObject({ message: 'You cannot do that.' });
  });

  it('gives a 404 the same code whatever the back end called it, on any route', async () => {
    const one = toBffError(new FhirError(404, outcome('not-found')));
    const two = toBffError(new FhirError(404, outcome('not-supported')));
    expect(await body(one)).toEqual(await body(two));
  });

  it('never repeats the back end text on an id route either', async () => {
    const text = await toBffError(new FhirError(404, outcome('not-found', 'No Service/svc-9 in tenant trust-b')), { idScoped: true }).text();
    expect(text).not.toContain('trust-b');
    expect(text).not.toContain('svc-9');
  });
});
