import { describe, expect, it, vi } from 'vitest';
import { directoryIdFromIssuer, lookupDirectoryId, normaliseLookupDomain } from './directoryLookup';

const ID = 'c5901e0b-8d43-4ae8-97c3-ca6c52573a33';

function answering(body: unknown, init: { ok?: boolean } = {}) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status: init.ok === false ? 404 : 200 }));
}

describe('normaliseLookupDomain', () => {
  it('takes a domain in any case, with spaces and a trailing dot, and refuses anything that is not a domain', () => {
    expect(normaliseLookupDomain('  Example.NHS.uk. ')).toBe('example.nhs.uk');
    for (const bad of ['', 'localhost', '10.0.0.1', 'a b.example', 'https://example.nhs.uk', 'example.nhs.uk/x', '-x.example.uk', 'x..uk']) {
      expect(normaliseLookupDomain(bad), bad).toBeNull();
    }
  });
});

describe('directoryIdFromIssuer', () => {
  it('reads the tenant id of a Microsoft issuer, lower case', () => {
    expect(directoryIdFromIssuer(`https://login.microsoftonline.com/${ID.toUpperCase()}/v2.0`)).toBe(ID);
  });

  it('gives nothing for any other issuer or shape', () => {
    for (const bad of [undefined, 42, 'https://evil.example/' + ID + '/v2.0', `https://login.microsoftonline.com/${ID}/v1.0`, 'https://login.microsoftonline.com/common/v2.0']) {
      expect(directoryIdFromIssuer(bad), String(bad)).toBeNull();
    }
  });
});

describe('lookupDirectoryId', () => {
  it('asks the domain’s OpenID configuration, refusing redirects, and returns its tenant id', async () => {
    const fetcher = answering({ issuer: `https://login.microsoftonline.com/${ID}/v2.0` });
    expect(await lookupDirectoryId('Example.nhs.uk', fetcher as unknown as typeof fetch)).toBe(ID);
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('https://login.microsoftonline.com/example.nhs.uk/v2.0/.well-known/openid-configuration');
    expect(init.redirect).toBe('error');
  });

  it('gives nothing for a domain that is not one, without calling out', async () => {
    const fetcher = answering({});
    expect(await lookupDirectoryId('not a domain', fetcher as unknown as typeof fetch)).toBeNull();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('gives nothing when the domain has no directory, or the answer is not one', async () => {
    expect(await lookupDirectoryId('example.nhs.uk', answering({}, { ok: false }) as unknown as typeof fetch)).toBeNull();
    expect(await lookupDirectoryId('example.nhs.uk', answering({ issuer: 'nope' }) as unknown as typeof fetch)).toBeNull();
  });

  it('gives nothing when the call fails or the answer is not JSON', async () => {
    const broken = vi.fn(async () => {
      throw new TypeError('fetch failed');
    });
    expect(await lookupDirectoryId('example.nhs.uk', broken as unknown as typeof fetch)).toBeNull();
    const notJson = vi.fn(async () => new Response('<html>', { status: 200 }));
    expect(await lookupDirectoryId('example.nhs.uk', notJson as unknown as typeof fetch)).toBeNull();
  });
});
