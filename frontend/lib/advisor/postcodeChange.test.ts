import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { BLANK_CASE, CASE_ETAG } from '@/test/msw/handlers/advisor';
import { server } from '@/test/msw/server';
import { resetCsrfCache } from './browser';
import type { CaseView } from './codes';
import { canChangePostcode, changePostcode } from './postcodeChange';

const VIEW = {
  ...BLANK_CASE,
  referrerType: 'gp',
  ageBand: '80+',
  postcode: 'DT4',
  needs: ['frailty'],
  urgency: 'within-2-hrs',
  etag: CASE_ETAG,
} as unknown as CaseView;

type Put = { url: string; ifMatch: string | null; key: string | null; body: unknown };
let puts: Put[];

beforeEach(() => {
  resetCsrfCache();
  puts = [];
});

function savesWith(status: number) {
  server.use(
    http.put('/api/bff/cases/:ref', async ({ request }) => {
      puts.push({ url: new URL(request.url).pathname, ifMatch: request.headers.get('if-match'), key: request.headers.get('idempotency-key'), body: await request.json() });
      return HttpResponse.json(status === 200 ? VIEW : { code: 'x' }, { status });
    }),
  );
}

describe('canChangePostcode', () => {
  it('needs every coded part and an ETag, and an open case', () => {
    expect(canChangePostcode(VIEW)).toBe(true);
    expect(canChangePostcode(null)).toBe(false);
    expect(canChangePostcode({ ...VIEW, etag: null })).toBe(false);
    expect(canChangePostcode({ ...VIEW, needs: [] })).toBe(false);
    expect(canChangePostcode({ ...VIEW, ageBand: null })).toBe(false);
    expect(canChangePostcode({ ...VIEW, closed: true })).toBe(false);
  });
});

describe('changePostcode', () => {
  it('saves the normalised postcode with the coded parts as they are, the ETag read and one key', async () => {
    savesWith(200);
    expect(await changePostcode(VIEW, ' dt48xx ')).toBe('saved');
    expect(puts).toHaveLength(1);
    expect(puts[0]).toMatchObject({ url: `/api/bff/cases/${VIEW.id}`, ifMatch: CASE_ETAG });
    expect(puts[0].key).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
    expect(puts[0].body).toEqual({ referrerType: 'gp', ageBand: '80+', postcode: 'DT4 8XX', needs: ['frailty'], urgency: 'within-2-hrs', scores: [] });
  });

  it('refuses something that is not a full postcode, and sends nothing', async () => {
    savesWith(200);
    expect(await changePostcode(VIEW, 'DT4 8X')).toBe('invalid');
    expect(await changePostcode(VIEW, '')).toBe('invalid');
    expect(puts).toHaveLength(0);
  });

  it('a stale ETag is a conflict, and any other refusal is a failure', async () => {
    savesWith(412);
    expect(await changePostcode(VIEW, 'DT4 8XX')).toBe('conflict');
    savesWith(500);
    expect(await changePostcode(VIEW, 'DT4 8XX')).toBe('failed');
  });

  it('a case that cannot be saved from here is a failure, and sends nothing', async () => {
    savesWith(200);
    expect(await changePostcode({ ...VIEW, etag: null }, 'DT4 8XX')).toBe('failed');
    expect(puts).toHaveLength(0);
  });
});
