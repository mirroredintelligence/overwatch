import { describe, expect, it } from 'vitest';
import { normaliseHost, requestHost } from './host';

describe('normaliseHost', () => {
  it.each([
    ['tenant-a.example.test', 'tenant-a.example.test'],
    ['Tenant-A.Example.Test', 'tenant-a.example.test'],
    ['tenant-a.example.test:3000', 'tenant-a.example.test:3000'],
    ['tenant-a.example.test.', 'tenant-a.example.test'],
    ['localhost:20000', 'localhost:20000'],
    ['127.0.0.1:8080', '127.0.0.1:8080'],
  ])('reads %s as %s', (given, expected) => {
    expect(normaliseHost(given)).toBe(expected);
  });

  it.each([
    '',
    ' ',
    'a.test/path',
    'a.test?x=1',
    'a.test#x',
    'user@a.test',
    'a b.test',
    'a.test:',
    'a.test:99999x',
    'a.test:123456',
    '-a.test',
    'a..test',
    '.a.test',
    'a_b.test',
    'a.test\n',
    'a.test,b.test',
    'x'.repeat(300),
    '[::1]',
  ])('refuses %j', (given) => {
    expect(normaliseHost(given)).toBeNull();
  });

  it('refuses what is not text', () => {
    for (const value of [null, undefined, 7, {}, ['a.test']]) {
      expect(normaliseHost(value as unknown as string)).toBeNull();
    }
  });
});

describe('requestHost', () => {
  it('is the Host header, and nothing else a caller can add', () => {
    const request = new Request('https://elsewhere.test/x', {
      headers: {
        Host: 'tenant-a.example.test',
        'X-Forwarded-Host': 'tenant-b.example.test',
        Forwarded: 'host=tenant-b.example.test',
        'X-Tenant': 'tenant-b.example.test',
        'X-Original-Host': 'tenant-b.example.test',
      },
    });
    expect(requestHost(request)).toBe('tenant-a.example.test');
  });

  it('is the host of the address when the request has no Host header', () => {
    expect(requestHost(new Request('https://tenant-b.example.test:8443/x'))).toBe('tenant-b.example.test:8443');
  });

  it('is null for a Host header that is not a host name, even when the address is fine', () => {
    const request = new Request('https://tenant-a.example.test/x', { headers: { Host: 'tenant-a.example.test/evil' } });
    expect(requestHost(request)).toBeNull();
  });
});
