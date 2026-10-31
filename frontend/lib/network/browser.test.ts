import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { server } from '@/test/msw/server';
import { networkBffHandlers, resetNetworkBff, seenNetworkBff } from '@/test/msw/handlers/networkBff';
import { parsePhones } from './parse';
import { fetchNetworkBoard, networkEventsUrl, NetworkFetchError, readNetworkList, readNetworkView } from './browser';

// TEN-068/070: the browser's reads of its own BFF's network routes. The one place a network id is put on
// a request is the `networkId` query key of these routes (the id the server offered); never a header, never
// a body, never storage.

describe('networkEventsUrl', () => {
  it('is the BFF stream with the network id as the one query key', () => {
    expect(networkEventsUrl('net-sample')).toBe('/api/bff/network/events?networkId=net-sample');
  });
});

describe('readNetworkList', () => {
  it('reads the networks and the own organisation name', async () => {
    server.use(...networkBffHandlers);
    resetNetworkBff();
    const result = await readNetworkList();
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data.networks.map((n) => n.id)).toEqual(['net-sample']);
      expect(result.data.ownOrganisation).toBe('Sample Area A');
    }
    expect(seenNetworkBff).toEqual([{ path: '/api/bff/network', query: '' }]);
  });

  it('says the status when it is refused, and is not ok for an answer it cannot read', async () => {
    server.use(http.get('/api/bff/network', () => HttpResponse.json({ code: 'forbidden' }, { status: 403 })));
    expect(await readNetworkList()).toMatchObject({ ok: false, status: 403 });
    server.use(http.get('/api/bff/network', () => HttpResponse.json({ surprise: true })));
    expect(await readNetworkList()).toMatchObject({ ok: false, code: 'unreadable' });
  });
});

describe('readNetworkView', () => {
  it('reads a view of a network, naming it by networkId only', async () => {
    server.use(...networkBffHandlers);
    resetNetworkBff();
    const result = await readNetworkView('phones', 'net-sample', (body) => parsePhones(body, 'bff'));
    expect(result.ok).toBe(true);
    expect(seenNetworkBff).toEqual([{ path: '/api/bff/network/phones', query: 'networkId=net-sample' }]);
  });

  it('adds the history flag for the history of the directory', async () => {
    server.use(...networkBffHandlers);
    resetNetworkBff();
    await readNetworkView('directory', 'net-sample', () => 1, 'history=true');
    expect(seenNetworkBff[0]?.query).toBe('networkId=net-sample&history=true');
  });

  it('is not ok for a 404, whatever the body says', async () => {
    server.use(http.get('/api/bff/network/phones', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    expect(await readNetworkView('phones', 'net-sample', (body) => parsePhones(body, 'bff'))).toMatchObject({ ok: false, status: 404 });
  });
});

describe('fetchNetworkBoard', () => {
  it('reads the board and the back end’s clock from the Date header', async () => {
    server.use(...networkBffHandlers);
    const fetched = await fetchNetworkBoard('net-sample');
    expect(fetched.board.entries).toHaveLength(4);
    expect(fetched.serverTime === null || typeof fetched.serverTime === 'number').toBe(true);
  });

  it.each([
    [401, 'refused'],
    [403, 'refused'],
    [404, 'refused'],
    [502, 'unreadable'],
    [503, 'unreachable'],
    [500, 'unreachable'],
  ])('a %s is %s', async (status, kind) => {
    server.use(http.get('/api/bff/network/board', () => HttpResponse.json({ code: 'x' }, { status })));
    const error = await fetchNetworkBoard('net-sample').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(NetworkFetchError);
    expect(error).toMatchObject({ kind, status });
  });

  it('a body that is not a board is unreadable, with nothing of the body in the error', async () => {
    server.use(http.get('/api/bff/network/board', () => HttpResponse.json({ entries: 'Secret-Value-9' })));
    const error = (await fetchNetworkBoard('net-sample').catch((e: unknown) => e)) as Error;
    expect(error).toMatchObject({ kind: 'unreadable' });
    expect(error.message).not.toContain('Secret-Value-9');
  });
});
