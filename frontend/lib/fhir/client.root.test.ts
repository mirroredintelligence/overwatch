// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fhirFetch } from './client';

// The support and console routes sit at the back end's root, outside /fhir (W48, DEC-335).
const ROOT = 'http://backend.test';

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${ROOT}/fhir`);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

function answer(): ReturnType<typeof vi.fn> {
  const spy = vi.fn(async () => new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } }));
  vi.stubGlobal('fetch', spy);
  return spy;
}

describe('fhirFetch with root: true', () => {
  it('calls the back end root, outside /fhir', async () => {
    const spy = answer();

    await fhirFetch('/support/sessions', { root: true, token: 'token-x' });

    expect(String(spy.mock.calls[0]?.[0])).toBe(`${ROOT}/support/sessions`);
  });

  it('keeps calling under /fhir when root is not set', async () => {
    const spy = answer();

    await fhirFetch('/HealthcareService/$board', { token: 'token-x' });

    expect(String(spy.mock.calls[0]?.[0])).toBe(`${ROOT}/fhir/HealthcareService/$board`);
  });
});
