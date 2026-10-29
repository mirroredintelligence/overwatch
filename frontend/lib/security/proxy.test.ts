import { NextRequest } from 'next/server';
import { describe, expect, it } from 'vitest';
import { proxy } from '@/proxy';
import { securityHeaders } from './csp';

function nonceIn(response: Response): string {
  const csp = response.headers.get('content-security-policy') ?? '';
  const match = /'nonce-([^']+)'/.exec(csp);
  if (match === null) throw new Error('the response carries no nonce');
  return match[1];
}

describe('proxy', () => {
  it('gives each request its own nonce', async () => {
    const first = nonceIn(await proxy(new NextRequest('http://localhost/screen')));
    const second = nonceIn(await proxy(new NextRequest('http://localhost/screen')));
    expect(first).not.toEqual(second);
  });

  it('passes the same nonce to the page in x-nonce, for Next to apply', async () => {
    const response = await proxy(new NextRequest('http://localhost/screen'));
    expect(response.headers.get('x-middleware-request-x-nonce')).toBe(nonceIn(response));
  });

  it('sets the policy and every other security header on the response', async () => {
    const response = await proxy(new NextRequest('http://localhost/screen'));
    expect(response.headers.get('content-security-policy')).toContain("frame-ancestors 'none'");
    for (const [name, value] of Object.entries(securityHeaders())) {
      expect(response.headers.get(name)).toBe(value);
    }
  });
});
