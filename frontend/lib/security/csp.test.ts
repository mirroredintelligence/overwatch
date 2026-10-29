import { describe, expect, it } from 'vitest';
import { buildCsp, securityHeaders } from './csp';

const DIRECTIVES = [
  "default-src 'self'",
  "script-src 'self' 'nonce-abc' 'strict-dynamic'",
  "style-src 'self' 'nonce-abc'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self'",
  "worker-src 'self'",
  "manifest-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
  'upgrade-insecure-requests',
];

describe('buildCsp', () => {
  it('sets a nonce script policy with strict-dynamic, and forbids framing', () => {
    const csp = buildCsp('abc', false);
    expect(csp).toContain("script-src 'self' 'nonce-abc' 'strict-dynamic'");
    expect(csp).toContain("frame-ancestors 'none'");
  });

  it('never allows unsafe-eval or unsafe-inline in production', () => {
    const csp = buildCsp('abc', false);
    expect(csp).not.toContain('unsafe-eval');
    expect(csp).not.toContain('unsafe-inline');
  });

  it('allows unsafe-eval in development only, for the dev server', () => {
    expect(buildCsp('abc', true)).toContain("'unsafe-eval'");
  });

  it('carries every directive the policy names, and nothing else', () => {
    const directives = buildCsp('abc', false)
      .split(';')
      .map((part) => part.trim())
      .filter((part) => part.length > 0);
    expect(directives.sort()).toEqual([...DIRECTIVES].sort());
  });

  it('refuses a nonce that could break out of the header', () => {
    expect(() => buildCsp("a'b", false)).toThrow(/nonce/);
    expect(() => buildCsp('a;b', false)).toThrow(/nonce/);
    expect(() => buildCsp('', false)).toThrow(/nonce/);
  });
});

describe('securityHeaders', () => {
  it.each([
    ['Strict-Transport-Security', 'max-age=63072000; includeSubDomains'],
    ['X-Content-Type-Options', 'nosniff'],
    ['Referrer-Policy', 'no-referrer'],
    ['Permissions-Policy', 'camera=(), microphone=(), geolocation=(), payment=()'],
    ['Cross-Origin-Opener-Policy', 'same-origin'],
  ])('sets %s to its exact value', (name, value) => {
    expect(securityHeaders()[name]).toBe(value);
  });

  it('sets no header that is not in the policy', () => {
    expect(Object.keys(securityHeaders()).sort()).toEqual(
      [
        'Strict-Transport-Security',
        'X-Content-Type-Options',
        'Referrer-Policy',
        'Permissions-Policy',
        'Cross-Origin-Opener-Policy',
      ].sort(),
    );
  });
});
