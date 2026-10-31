// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BACKEND_ROOT, LINK, RECORDED_VIEW, TENANT_HOST, csrfFor } from '@/test/fixtures/links';
import { seenBackendRequests, resetLinkRequests } from '@/test/msw/handlers/links';
import { server } from '@/test/msw/server';
import { backendRoot, callLinkApi, LinkApiError, publicReply, readLink } from './server';

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
});

describe('backendRoot', () => {
  it('is the origin of the FHIR base URL, because the link routes sit beside /fhir', () => {
    expect(backendRoot('http://127.0.0.1:4010/fhir')).toBe('http://127.0.0.1:4010');
    expect(backendRoot('https://api.example.test/fhir/')).toBe('https://api.example.test');
  });

  it('names the variable, and never its value, when the base URL does not end in /fhir', () => {
    expect(() => backendRoot('https://api.example.test/other')).toThrow(/DIUCS_FHIR_BASE_URL/);
    expect(() => backendRoot(undefined)).toThrow(/DIUCS_FHIR_BASE_URL/);
    try {
      backendRoot('https://api.example.test/other');
    } catch (error) {
      expect((error as Error).message).not.toContain('api.example.test');
    }
  });
});

describe('callLinkApi', () => {
  it('sends the browser’s host to the back end, so the tenant is the host the link was sent to', async () => {
    resetLinkRequests();
    await callLinkApi({ method: 'GET', path: `/links/${LINK.recorded}`, host: TENANT_HOST });
    const last = seenBackendRequests.at(-1);
    expect(last?.host).toBe(TENANT_HOST);
  });

  it('refuses a host that is not a plain host name, without calling the back end', async () => {
    resetLinkRequests();
    await expect(
      callLinkApi({ method: 'GET', path: `/links/${LINK.recorded}`, host: 'tenant.example.test/evil' }),
    ).rejects.toBeInstanceOf(LinkApiError);
    expect(seenBackendRequests).toHaveLength(0);
  });

  it('refuses a missing host the same way', async () => {
    await expect(callLinkApi({ method: 'GET', path: `/links/${LINK.recorded}`, host: null })).rejects.toBeInstanceOf(
      LinkApiError,
    );
  });

  it('answers a back end that cannot be reached as unavailable', async () => {
    server.use(http.get(`${BACKEND_ROOT}/links/:token`, () => HttpResponse.error()));
    await expect(callLinkApi({ method: 'GET', path: `/links/${LINK.recorded}`, host: TENANT_HOST })).rejects.toMatchObject({
      kind: 'unavailable',
    });
  });

  it('sends the CSRF token as X-CSRF-Token when one is given', async () => {
    let seen: string | null = null;
    server.use(
      http.post(`${BACKEND_ROOT}/links/:token`, ({ request }) => {
        seen = request.headers.get('x-csrf-token');
        return HttpResponse.json({ state: 'forbidden' }, { status: 403 });
      }),
    );
    await callLinkApi({
      method: 'POST',
      path: `/links/${LINK.recorded}`,
      host: TENANT_HOST,
      body: { action: 'confirm' },
      csrf: csrfFor(LINK.recorded),
    });
    expect(seen).toBe(csrfFor(LINK.recorded));
  });
});

describe('readLink', () => {
  it('reads an open link and returns its view', async () => {
    const result = await readLink(LINK.recorded, TENANT_HOST);
    expect(result).toMatchObject({
      kind: 'open',
      link: { kind: 'capacity', view: { serviceName: RECORDED_VIEW.serviceName, recordedValue: 3 } },
    });
  });

  it('reads a 410 as gone, with its closed state word', async () => {
    await expect(readLink(LINK.expired, TENANT_HOST)).resolves.toMatchObject({ kind: 'gone', closed: { state: 'expired', kind: null } });
    await expect(readLink(LINK.used, TENANT_HOST)).resolves.toMatchObject({ kind: 'gone', closed: { state: 'used' } });
    // A closed booking link also says what it knows of its closing (KI-169, KI-648, KI-664).
    await expect(readLink(LINK.bookingCancelled, TENANT_HOST)).resolves.toMatchObject({
      kind: 'gone',
      closed: { state: 'cancelled', kind: 'booking', reference: '4821', cancelledAt: '2026-10-23T13:40:00Z', coordinationPhone: '0300 123 4567' },
    });
  });

  it('answers a 503 as unavailable, not as gone', async () => {
    await expect(readLink(LINK.down, TENANT_HOST)).rejects.toMatchObject({ kind: 'unavailable' });
  });
});

describe('publicReply', () => {
  it('keeps only the fields the page reads, so no tenant or other field goes to the browser', () => {
    const reply = publicReply(200, { serviceName: 'UCR West', value: 3, tenantId: 'tenant-a', stack: 'x' });
    expect(reply).toEqual({ status: 200, body: { serviceName: 'UCR West', value: 3 } });
  });

  it('answers any status outside the link API as a fixed error', () => {
    expect(publicReply(500, { diagnostics: 'a path' })).toEqual({ status: 500, body: { state: 'error' } });
  });

  it('passes a state word and the refusal fields for a known status', () => {
    expect(publicReply(422, { state: 'out-of-range', usualMin: 0, usualMax: 8, extra: 1 })).toEqual({
      status: 422,
      body: { state: 'out-of-range', usualMin: 0, usualMax: 8 },
    });
    expect(publicReply(410, { state: 'used', closedAt: '2026-10-23T11:30:00Z' })).toEqual({
      status: 410,
      body: { state: 'used', closedAt: '2026-10-23T11:30:00Z' },
    });
  });
});


describe('publicReply: what a closed link and a booking answer may tell the browser (WB4)', () => {
  const detail = {
    kind: 'booking',
    reference: '4821',
    closedAt: '2026-10-23T13:40:00Z',
    confirmedAt: '2026-10-23T13:19:00Z',
    cancelledAt: '2026-10-23T13:40:00Z',
    coordinationPhone: '0300 123 4567',
  };

  it('passes the closing details of a closed link on a 410 and of a refused answer on a 409', () => {
    expect(publicReply(410, { state: 'cancelled', ...detail }).body).toEqual({ state: 'cancelled', ...detail });
    expect(publicReply(409, { state: 'withdrawn', ...detail }).body).toMatchObject({ state: 'withdrawn', ...detail });
  });

  it('drops anything else the back end put in a closed answer', () => {
    const { body } = publicReply(410, { state: 'expired', ...detail, postcode: 'DT4 8XX', caseId: 'case-1001', tenant: 't-1' });
    expect(JSON.stringify(body)).not.toMatch(/DT4|case-1001|t-1/);
  });

  it('passes the time of a confirmation, or of any other answer, on a 200', () => {
    expect(publicReply(200, { bookingStatus: 'confirmed', changeToken: 'tok', confirmedAt: '2026-10-23T13:19:00Z' }).body).toEqual({
      bookingStatus: 'confirmed',
      changeToken: 'tok',
      confirmedAt: '2026-10-23T13:19:00Z',
    });
    expect(publicReply(200, { bookingStatus: 'withdrawn', respondedAt: '2026-10-23T13:41:00Z' }).body).toEqual({
      bookingStatus: 'withdrawn',
      respondedAt: '2026-10-23T13:41:00Z',
    });
  });

  it('says nothing more than the word on a 400 or a 403', () => {
    expect(publicReply(400, { state: 'invalid', ...detail }).body).toEqual({ state: 'invalid' });
    expect(publicReply(403, { state: 'forbidden', ...detail }).body).toEqual({ state: 'forbidden' });
  });
});

describe('closedOf: the closed link the BFF passes on', () => {
  it('reads the state word and the details of a 410 body, and says expired for a body it cannot read', async () => {
    const { closedOf } = await import('./server');
    expect(closedOf({ state: 'cancelled', kind: 'booking', reference: '4821', cancelledAt: '2026-10-23T13:40:00Z' })).toMatchObject({
      state: 'cancelled',
      kind: 'booking',
      cancelledAt: '2026-10-23T13:40:00Z',
    });
    expect(closedOf(undefined).state).toBe('expired');
    expect(closedOf({ state: 'used' }).state).toBe('used');
  });
});
