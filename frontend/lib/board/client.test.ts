import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { BOARD_A } from '@/test/fixtures/board';
import { server } from '@/test/msw/server';
import { BoardFetchError, fetchBoardFromBff } from './client';

const URL_ = '*/api/bff/board';
const DATE_HEADER = 'Fri, 23 Oct 2026 13:12:05 GMT';

async function failure(): Promise<BoardFetchError> {
  try {
    await fetchBoardFromBff();
  } catch (error) {
    expect(error).toBeInstanceOf(BoardFetchError);
    return error as BoardFetchError;
  }
  throw new Error('it did not fail');
}

describe('fetchBoardFromBff', () => {
  it('returns the board and the back end clock from the Date header', async () => {
    server.use(http.get(URL_, () => HttpResponse.json(BOARD_A, { headers: { Date: DATE_HEADER } })));

    const result = await fetchBoardFromBff();

    expect(result.board).toEqual(BOARD_A);
    expect(result.serverTime).toBe(Date.parse(DATE_HEADER));
  });

  it('gives a null server time when the answer has no usable Date header, so the caller keeps its last offset', async () => {
    server.use(http.get(URL_, () => HttpResponse.json(BOARD_A, { headers: { Date: 'not a date' } })));
    expect((await fetchBoardFromBff()).serverTime).toBeNull();

    server.use(http.get(URL_, () => HttpResponse.json(BOARD_A, { headers: { Date: '' } })));
    expect((await fetchBoardFromBff()).serverTime).toBeNull();
  });

  it('asks for the board with a plain GET, no query string, no tenant, no store', async () => {
    let seen: Request | undefined;
    server.use(
      http.get(URL_, ({ request }) => {
        seen = request.clone();
        return HttpResponse.json(BOARD_A);
      }),
    );

    await fetchBoardFromBff();

    expect(seen?.method).toBe('GET');
    expect(new URL(seen?.url ?? '').pathname).toBe('/api/bff/board');
    expect(new URL(seen?.url ?? '').search).toBe('');
    expect(seen?.cache).toBe('no-store');
    expect(seen?.headers.get('authorization')).toBeNull();
    for (const name of seen?.headers.keys() ?? []) expect(name).not.toMatch(/tenant|organi[sz]ation/i);
  });

  it.each([401, 403, 404])('says the screen is refused when the BFF answers %i', async (status) => {
    server.use(http.get(URL_, () => HttpResponse.json({ code: 'x', message: 'y' }, { status })));

    const error = await failure();

    expect(error.kind).toBe('refused');
    expect(error.status).toBe(status);
  });

  it('says the answer was unreadable when the BFF answers 502, the back end sent a board it could not read', async () => {
    server.use(http.get(URL_, () => HttpResponse.json({ code: 'exception' }, { status: 502 })));

    const error = await failure();

    expect(error.kind).toBe('unreadable');
    expect(error.status).toBe(502);
  });

  it.each([500, 503, 429])('says the BFF could not be reached for %i', async (status) => {
    server.use(http.get(URL_, () => HttpResponse.json({}, { status })));

    const error = await failure();

    expect(error.kind).toBe('unreachable');
    expect(error.status).toBe(status);
  });

  it('says it could not be reached when the network fails', async () => {
    server.use(http.get(URL_, () => HttpResponse.error()));

    const error = await failure();

    expect(error.kind).toBe('unreachable');
    expect(error.status).toBeNull();
  });

  it('says the answer was unreadable for a 200 that is not JSON', async () => {
    server.use(http.get(URL_, () => new HttpResponse('<html>gateway</html>', { headers: { 'Content-Type': 'text/html' } })));

    expect((await failure()).kind).toBe('unreadable');
  });

  it.each([
    ['a board with a negative count', () => ({ ...BOARD_A, entries: [{ ...BOARD_A.entries[0], used: -3 }] })],
    ['a board with an unknown status', () => ({ ...BOARD_A, entries: [{ ...BOARD_A.entries[0], status: 'busy' }] })],
    ['an empty object', () => ({})],
    ['a list', () => []],
  ])('says the answer was unreadable for 200 with %s', async (_label, body) => {
    server.use(http.get(URL_, () => HttpResponse.json(body())));

    const error = await failure();

    expect(error.kind).toBe('unreadable');
  });

  it('keeps nothing from the answer in its message', async () => {
    server.use(
      http.get(URL_, () => HttpResponse.json({ ...BOARD_A, entries: [{ ...BOARD_A.entries[0], status: 'Secret Ward 7' }] })),
    );

    const error = await failure();

    expect(error.message).not.toContain('Secret Ward 7');
  });

  it('stops when its signal is aborted, as a failure, not a board', async () => {
    server.use(http.get(URL_, async () => new Promise<Response>(() => undefined)));
    const controller = new AbortController();

    const pending = fetchBoardFromBff(controller.signal);
    controller.abort();

    await expect(pending).rejects.toBeInstanceOf(BoardFetchError);
  });
});
