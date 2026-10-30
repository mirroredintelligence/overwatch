// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fakeBackendToken } from '@/test/backendToken';
import { FhirError, fhirFetch } from '@/lib/fhir/client';
import { ONLY_IN_A, SHARED_IDS, TENANTS } from '@/test/tenants';
import { canary } from '@/test/leak-canary';
import { BACKEND_BASE } from './board';

// The tenant-aware back end stand-in (TEN-047): the same identifier gives each tenant its own record,
// another tenant's record is a 404 like a record that is nowhere, and no readable token is a 401.

const tokenFor = (tenant: { id: string }) => fakeBackendToken({ tenant: tenant.id });

async function read(path: string, token: string) {
  canary.expect(TENANTS.A.id);
  canary.expect(TENANTS.B.id);
  return fhirFetch<Record<string, unknown>>(path, { token });
}

async function failure(call: Promise<unknown>): Promise<FhirError> {
  const error = await call.then(
    () => null,
    (e: unknown) => e,
  );
  expect(error).toBeInstanceOf(FhirError);
  return error as FhirError;
}

beforeEach(() => vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE));

describe('tenantDataHandlers', () => {
  it('answers each tenant with its own record for an identifier both hold', async () => {
    const a = await read(`/HealthcareService/${SHARED_IDS.serviceId}`, tokenFor(TENANTS.A));
    const b = await read(`/HealthcareService/${SHARED_IDS.serviceId}`, tokenFor(TENANTS.B));
    expect(a.data).toMatchObject({ id: 's1', name: 'Alder Community Beds' });
    expect(b.data).toMatchObject({ id: 's1', name: 'Birch Community Beds' });
    const caseA = await read(`/ServiceRequest/${SHARED_IDS.caseReference}`, tokenFor(TENANTS.A));
    const caseB = await read(`/ServiceRequest/${SHARED_IDS.caseReference}`, tokenFor(TENANTS.B));
    expect(caseA.data.note).not.toBe(caseB.data.note);
  });

  it('answers a record that is only in tenant A as a 404 to tenant B, the same as a record that is nowhere', async () => {
    const other = await failure(read(`/HealthcareService/${ONLY_IN_A.serviceId}`, tokenFor(TENANTS.B)));
    const nowhere = await failure(read('/HealthcareService/nowhere-1', tokenFor(TENANTS.B)));
    expect(other.status).toBe(404);
    expect(other.outcome).toEqual(nowhere.outcome);
    expect(ONLY_IN_A.caseReference).toBe('4822');
    expect((await failure(read(`/ServiceRequest/${ONLY_IN_A.caseReference}`, tokenFor(TENANTS.B)))).status).toBe(404);
  });

  it('answers a token it cannot read, and a tenant it does not know, without a record', async () => {
    expect((await failure(read('/HealthcareService/s1', 'opaque-test-token'))).status).toBe(401);
    canary.expect('nobody');
    expect((await failure(read('/HealthcareService/s1', fakeBackendToken({ tenant: 'nobody' })))).status).toBe(404);
  });

  it('does not take over the board: the board route is still the board stand-in’s', async () => {
    const response = await read('/HealthcareService/$board', 'token-for-organisation-a').catch((e: unknown) => e);
    expect(response).not.toBeInstanceOf(FhirError);
  });
});
