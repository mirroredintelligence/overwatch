import { normaliseHost } from '@/lib/auth/host';
import { namesTenantInput } from '@/lib/tenant/inputNames';

// The one way browser code stores anything on the device (TEN-050, audit D 3.4 and R9). Nothing
// personal is stored in the browser beyond plain interface state (a chosen tab, a tour seen), and
// this module is the allow-list for that: a short name, a small plain value, never a token, a phone
// number, an email address, a postcode or anything that names a tenant, scope or network.
//
// The tenant is not in the key and not in the value (the browser never needs its id, and must not
// hold it). It is the HOST: one sub-domain is one tenant (DEC-136 item 11), so one browser origin is
// one tenant's, and the key carries the host so a value written on one host is never read on another.
// Sign-out and unpair delete everything here (lib/session/signOut.ts). Every use of `localStorage`
// goes through this module (a scan test holds that, TEN-048).

export const STORAGE_PREFIX = 'diucs:v1:';

const NAME = /^[a-z][a-z0-9]*([.-][a-z0-9]+)*$/;
const MAX_NAME_LENGTH = 40;
const MAX_VALUE_CHARS = 2048;
const MAX_DEPTH = 6;
const MAX_NUMBER = 999_999;

// What interface state is never: a token (three base64url parts, or a long opaque run), a phone
// number or NHS number (seven or more digits, spaces and dashes aside), an email address or a postcode.
const TOKEN_PARTS = /[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/;
const OPAQUE_RUN = /[A-Za-z0-9_-]{40,}/;
const LONG_DIGITS = /\d{7,}/;
const EMAIL = /\S+@\S+/;
const POSTCODE = /\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b/i;

function personal(text: string): boolean {
  const compact = text.replace(/[\s-]/g, '');
  return TOKEN_PARTS.test(text) || OPAQUE_RUN.test(text) || LONG_DIGITS.test(compact) || EMAIL.test(text) || POSTCODE.test(text);
}

/** True for a value that is plain interface state: JSON of plain types, small, shallow, nothing personal. */
function plain(value: unknown, depth = 0): boolean {
  if (depth > MAX_DEPTH) return false;
  if (value === null || typeof value === 'boolean') return true;
  if (typeof value === 'number') return Number.isFinite(value) && Math.abs(value) <= MAX_NUMBER;
  if (typeof value === 'string') return !personal(value);
  if (Array.isArray(value)) return value.every((item) => plain(item, depth + 1));
  if (typeof value === 'object') {
    const proto = Object.getPrototypeOf(value) as unknown;
    if (proto !== Object.prototype && proto !== null) return false;
    return Object.entries(value as Record<string, unknown>).every(
      ([key, item]) => !namesTenantInput(key) && !personal(key) && plain(item, depth + 1),
    );
  }
  return false;
}

export type StoreEnv = {
  /** Null where there is none (server rendering). */
  storage: Storage | null;
  /** The page's host: the tenant. */
  host: string;
};

export type TenantStore = {
  /** The stored value, when this host stored it and the validator accepts it; otherwise undefined (and a bad value is removed). */
  get<T>(name: string, validate: (value: unknown) => value is T): T | undefined;
  /** True when stored. False for a name or value this module refuses, and where storage is unavailable. */
  set(name: string, value: unknown): boolean;
  remove(name: string): void;
  /** The names stored for this host. */
  names(): string[];
  /** Removes every key of the app, on every host. Returns how many. */
  clear(): number;
};

function nameOk(name: unknown): name is string {
  return typeof name === 'string' && name.length <= MAX_NAME_LENGTH && NAME.test(name) && !namesTenantInput(name);
}

export function createTenantStore(env: StoreEnv): TenantStore {
  const host = normaliseHost(env.host);
  const storage = env.storage;
  const prefix = host === null ? null : `${STORAGE_PREFIX}${host}:`;

  // Storage can be missing, blocked or full (a private window, site data cleared): never an error.
  const attempt = <R,>(run: (s: Storage) => R, otherwise: R): R => {
    if (storage === null) return otherwise;
    try {
      return run(storage);
    } catch {
      return otherwise;
    }
  };

  return {
    get(name, validate) {
      if (prefix === null || !nameOk(name)) return undefined;
      const key = `${prefix}${name}`;
      return attempt((s) => {
        const raw = s.getItem(key);
        if (raw === null) return undefined;
        let value: unknown;
        try {
          value = JSON.parse(raw);
        } catch {
          s.removeItem(key);
          return undefined;
        }
        if (!validate(value) || !plain(value)) {
          s.removeItem(key);
          return undefined;
        }
        return value;
      }, undefined);
    },

    set(name, value) {
      if (prefix === null || !nameOk(name) || !plain(value)) return false;
      const text = JSON.stringify(value);
      if (text === undefined || text.length > MAX_VALUE_CHARS) return false;
      return attempt((s) => {
        s.setItem(`${prefix}${name}`, text);
        return true;
      }, false);
    },

    remove(name) {
      if (prefix === null || !nameOk(name)) return;
      attempt((s) => s.removeItem(`${prefix}${name}`), undefined);
    },

    names() {
      if (prefix === null) return [];
      return attempt((s) => {
        const found: string[] = [];
        for (let i = 0; i < s.length; i += 1) {
          const key = s.key(i);
          if (key !== null && key.startsWith(prefix)) found.push(key.slice(prefix.length));
        }
        return found;
      }, []);
    },

    clear() {
      return attempt((s) => {
        const keys: string[] = [];
        for (let i = 0; i < s.length; i += 1) {
          const key = s.key(i);
          if (key !== null && key.startsWith(STORAGE_PREFIX)) keys.push(key);
        }
        for (const key of keys) s.removeItem(key);
        return keys.length;
      }, 0);
    },
  };
}

function browserStorage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}

/** The store of the page the code runs in: the browser's `localStorage` and the page's host. */
export const tenantStore: TenantStore = {
  get: (name, validate) => createTenantStore(current()).get(name, validate),
  set: (name, value) => createTenantStore(current()).set(name, value),
  remove: (name) => createTenantStore(current()).remove(name),
  names: () => createTenantStore(current()).names(),
  clear: () => createTenantStore(current()).clear(),
};

function current(): StoreEnv {
  return { storage: browserStorage(), host: typeof window === 'undefined' ? '' : window.location.host };
}
