import { describe, expect, it } from 'vitest';
import { FhirError } from '@/lib/fhir/client';
import { toBffError } from './errors';

// Guard tests for DEC-109: the issue code the browser sees is a short
// lower-case code, and a fallback is used when it is absent or unsafe.

describe('toBffError issue code guard (DEC-109)', () => {
  it('uses invalid for a 4xx with no issue', async () => {
    const response = toBffError(new FhirError(409, { resourceType: 'OperationOutcome', issue: [] }));

    expect(response.status).toBe(409);
    expect(await response.json()).toMatchObject({ code: 'invalid' });
  });

  it('uses exception for a 5xx with no issue', async () => {
    const response = toBffError(new FhirError(500, { resourceType: 'OperationOutcome', issue: [] }));

    expect(await response.json()).toMatchObject({ code: 'exception' });
  });

  it('does not echo an issue code that is not lower-case words', async () => {
    const response = toBffError(
      new FhirError(409, {
        resourceType: 'OperationOutcome',
        issue: [{ severity: 'error', code: 'Bad Code synthetic-token-xq', diagnostics: 'x' }],
      }),
    );

    const text = await response.text();

    expect(JSON.parse(text)).toMatchObject({ code: 'invalid' });
    expect(text).not.toContain('synthetic-token-xq');
  });

  it('takes the code of the first issue even when a later issue has a valid code', async () => {
    const response = toBffError(
      new FhirError(409, {
        resourceType: 'OperationOutcome',
        issue: [
          { severity: 'error', code: 'Bad Code synthetic-token-xq', diagnostics: 'x' },
          { severity: 'error', code: 'conflict', diagnostics: 'y' },
        ],
      }),
    );

    expect(await response.json()).toMatchObject({ code: 'invalid' });
  });

  it('takes the first issue code when several issues all have valid codes', async () => {
    const response = toBffError(
      new FhirError(409, {
        resourceType: 'OperationOutcome',
        issue: [
          { severity: 'error', code: 'conflict', diagnostics: 'x' },
          { severity: 'error', code: 'invalid', diagnostics: 'y' },
        ],
      }),
    );

    expect(await response.json()).toMatchObject({ code: 'conflict' });
  });

  it('does not echo an issue code longer than 40 characters', async () => {
    const longCode = 'a'.repeat(41);
    const response = toBffError(
      new FhirError(409, {
        resourceType: 'OperationOutcome',
        issue: [{ severity: 'error', code: longCode, diagnostics: 'x' }],
      }),
    );

    expect(await response.json()).toMatchObject({ code: 'invalid' });
  });

  it('keeps a valid issue code of exactly 40 characters', async () => {
    const code = 'a'.repeat(40);
    const response = toBffError(
      new FhirError(409, {
        resourceType: 'OperationOutcome',
        issue: [{ severity: 'error', code, diagnostics: 'x' }],
      }),
    );

    expect(await response.json()).toMatchObject({ code });
  });
});
