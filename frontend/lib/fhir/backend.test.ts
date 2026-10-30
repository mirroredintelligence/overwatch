// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { server } from '@/test/msw/server';
import { backendFetch } from './client';

// The admin and identity routes sit beside the /fhir base, not under it (DEC-087): backendFetch calls the
// origin of DIUCS_FHIR_BASE_URL, which must end in /fhir.

const BASE = 'http://backend.test/fhir';
const ROOT = 'http://backend.test';

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BASE);
});

afterEach(() => vi.unstubAllEnvs());

describe('backendFetch', () => {
  it('calls the path beside the FHIR base, sends the bearer token, and reads the JSON', async () => {
    let seen: { url: string; auth: string | null } | undefined;
    server.use(
      http.get(`${ROOT}/admin/report-flags`, ({ request }) => {
        seen = { url: request.url, auth: request.headers.get('authorization') };
        return HttpResponse.json({ resourceType: 'Bundle' });
      }),
    );
    const { data } = await backendFetch<{ resourceType: string }>('/admin/report-flags?status=open', { token: 'tok' });
    expect(data.resourceType).toBe('Bundle');
    expect(seen?.url).toBe(`${ROOT}/admin/report-flags?status=open`);
    expect(seen?.auth).toBe('Bearer tok');
  });

  it('refuses a base that does not end in /fhir, naming the variable and never its value', async () => {
    vi.stubEnv('DIUCS_FHIR_BASE_URL', 'http://backend.test/elsewhere');
    await expect(backendFetch('/admin/report-flags')).rejects.toThrow('DIUCS_FHIR_BASE_URL');
    await expect(backendFetch('/admin/report-flags')).rejects.not.toThrow('backend.test');
  });
});
