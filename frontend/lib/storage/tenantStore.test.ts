import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createTenantStore, STORAGE_PREFIX } from './tenantStore';

// The one way browser code stores anything on the device (TEN-050, audit D 3.4 and R9). It is a
// small allow-list of plain interface state, per host (one host is one tenant, so the browser never
// needs the tenant id), and it refuses anything that looks like a token, a phone number, an email
// address, a postcode or a tenant name. Sign-out and unpair wipe it (lib/session/signOut.ts).

const HOST_A = 'tenant-a.example.test';
const HOST_B = 'tenant-b.example.test';

function memoryStorage(): Storage {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (key) => data.get(key) ?? null,
    key: (index) => [...data.keys()][index] ?? null,
    removeItem: (key) => void data.delete(key),
    setItem: (key, value) => void data.set(key, String(value)),
  };
}

const isBool = (value: unknown): value is boolean => typeof value === 'boolean';
const isTab = (value: unknown): value is 'late' | 'all' => value === 'late' || value === 'all';

let storage: Storage;
beforeEach(() => {
  storage = memoryStorage();
});

describe('get and set', () => {
  it('stores a value under a prefixed key for this host and reads it back', () => {
    const store = createTenantStore({ storage, host: HOST_A });
    expect(store.set('lead.tab', 'late')).toBe(true);
    expect(store.get('lead.tab', isTab)).toBe('late');
    expect(storage.getItem(`${STORAGE_PREFIX}${HOST_A}:lead.tab`)).toBe('"late"');
  });

  it('keeps one host’s values out of another host’s reads', () => {
    createTenantStore({ storage, host: HOST_A }).set('tour.seen', true);
    expect(createTenantStore({ storage, host: HOST_B }).get('tour.seen', isBool)).toBeUndefined();
  });

  it('returns undefined for a key that was never set', () => {
    expect(createTenantStore({ storage, host: HOST_A }).get('tour.seen', isBool)).toBeUndefined();
  });

  it('removes and returns undefined for a stored value the validator refuses', () => {
    const store = createTenantStore({ storage, host: HOST_A });
    storage.setItem(`${STORAGE_PREFIX}${HOST_A}:lead.tab`, '"somewhere-else"');
    expect(store.get('lead.tab', isTab)).toBeUndefined();
    expect(storage.getItem(`${STORAGE_PREFIX}${HOST_A}:lead.tab`)).toBeNull();
  });

  it('removes and returns undefined for a stored value that is not JSON', () => {
    const store = createTenantStore({ storage, host: HOST_A });
    storage.setItem(`${STORAGE_PREFIX}${HOST_A}:lead.tab`, '{not json');
    expect(store.get('lead.tab', isTab)).toBeUndefined();
    expect(storage.length).toBe(0);
  });

  it('removes one value', () => {
    const store = createTenantStore({ storage, host: HOST_A });
    store.set('tour.seen', true);
    store.remove('tour.seen');
    expect(store.get('tour.seen', isBool)).toBeUndefined();
  });

  it('lists the names it holds for this host, without the prefix', () => {
    const store = createTenantStore({ storage, host: HOST_A });
    store.set('tour.seen', true);
    store.set('lead.tab', 'all');
    createTenantStore({ storage, host: HOST_B }).set('other.name', true);
    expect(store.names().sort()).toEqual(['lead.tab', 'tour.seen']);
  });
});

describe('what it refuses to store', () => {
  const store = () => createTenantStore({ storage, host: HOST_A });

  it.each([
    'Lead.tab',
    'lead tab',
    '',
    '1abc',
    'a'.repeat(41),
    'lead/tab',
    '../x',
    'lead..tab',
    'lead.',
    'tenant.id',
    'networkName',
    'scope',
  ])('refuses the name %j', (name) => {
    expect(store().set(name, true)).toBe(false);
    expect(storage.length).toBe(0);
    expect(store().get(name, isBool)).toBeUndefined();
  });

  it.each([
    ['a back-end token', 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.signaturesignaturesignature'],
    ['a long opaque secret', 'A'.repeat(48)],
    ['a mobile number', '07700 900123'],
    ['a number with a country code', '+44 7700 900123'],
    ['a run of digits', '4821904455'],
    ['an email address', 'sample.person@example.test'],
    ['a postcode', 'DT4 8XX'],
    ['a postcode with no space', 'DT48XX'],
    ['an NHS number', '943 476 5919'],
  ])('refuses %s as a value, and as a value inside an object or a list', (_name, value) => {
    expect(store().set('note.draft', value)).toBe(false);
    expect(store().set('note.draft', { text: value })).toBe(false);
    expect(store().set('note.draft', ['ok', value])).toBe(false);
    expect(storage.length).toBe(0);
  });

  it('refuses an object that has a key naming a tenant, a scope or a network, at any depth', () => {
    for (const value of [{ tenant: 'x' }, { a: { scopeId: 'x' } }, [{ network: 'n' }], { sourceTenantId: 'x' }]) {
      expect(store().set('view.state', value)).toBe(false);
    }
    expect(storage.length).toBe(0);
  });

  it('refuses a value over 2 KiB, one nested too deep, and one that is not JSON', () => {
    expect(store().set('view.state', 'x '.repeat(1200))).toBe(false);
    let deep: unknown = 1;
    for (let i = 0; i < 10; i += 1) deep = { a: deep };
    expect(store().set('view.state', deep as never)).toBe(false);
    for (const value of [undefined, () => 1, Symbol('x'), 10n, new Date(), new Map()]) {
      expect(store().set('view.state', value as never)).toBe(false);
    }
    expect(storage.length).toBe(0);
  });

  it('refuses a number that is longer than any interface state would be', () => {
    expect(store().set('view.count', 12345678)).toBe(false);
    expect(store().set('view.count', 12)).toBe(true);
  });

  it('accepts plain interface state: booleans, short words, small numbers, small lists', () => {
    expect(store().set('tour.seen', true)).toBe(true);
    expect(store().set('lead.tab', 'late')).toBe(true);
    expect(store().set('view.filters', { district: 'north', onlyOpen: true, page: 2 })).toBe(true);
    expect(store().set('view.order', ['name', 'time'])).toBe(true);
  });
});

describe('when storage is not there', () => {
  it('does not throw and says no: private windows, blocked storage, a full disk', () => {
    const blocked = {
      getItem: () => { throw new Error('blocked'); },
      setItem: () => { throw new Error('quota'); },
      removeItem: () => { throw new Error('blocked'); },
      key: () => { throw new Error('blocked'); },
      clear: () => { throw new Error('blocked'); },
      get length(): number { throw new Error('blocked'); },
    } as unknown as Storage;
    const store = createTenantStore({ storage: blocked, host: HOST_A });
    expect(store.set('tour.seen', true)).toBe(false);
    expect(store.get('tour.seen', isBool)).toBeUndefined();
    expect(() => store.remove('tour.seen')).not.toThrow();
    expect(store.names()).toEqual([]);
    expect(store.clear()).toBe(0);
  });

  it('does nothing with no storage at all (server rendering)', () => {
    const store = createTenantStore({ storage: null, host: HOST_A });
    expect(store.set('tour.seen', true)).toBe(false);
    expect(store.get('tour.seen', isBool)).toBeUndefined();
    expect(store.clear()).toBe(0);
  });

  it('refuses a host that is not a host name', () => {
    const store = createTenantStore({ storage, host: 'a.test/evil' });
    expect(store.set('tour.seen', true)).toBe(false);
  });
});

describe('clear', () => {
  it('removes every key of the app on every host, and leaves other keys alone', () => {
    createTenantStore({ storage, host: HOST_A }).set('tour.seen', true);
    createTenantStore({ storage, host: HOST_B }).set('tour.seen', true);
    storage.setItem(`${STORAGE_PREFIX}old-version-or-unknown-key`, 'x');
    storage.setItem('unrelated', 'keep');
    expect(createTenantStore({ storage, host: HOST_A }).clear()).toBe(3);
    expect(storage.length).toBe(1);
    expect(storage.getItem('unrelated')).toBe('keep');
  });

  it('is safe to call twice', () => {
    const store = createTenantStore({ storage, host: HOST_A });
    store.set('tour.seen', true);
    expect(store.clear()).toBe(1);
    expect(store.clear()).toBe(0);
  });
});

describe('the default store', () => {
  it('uses the browser’s localStorage and the page’s host', async () => {
    window.localStorage.clear();
    vi.resetModules();
    const { tenantStore } = await import('./tenantStore');
    expect(tenantStore.set('tour.seen', true)).toBe(true);
    expect(window.localStorage.key(0)).toBe(`${STORAGE_PREFIX}${window.location.host}:tour.seen`);
    tenantStore.clear();
    expect(window.localStorage.length).toBe(0);
  });
});
