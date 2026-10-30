import { describe, expect, it } from 'vitest';
import { bffGet, bffPost } from './client';
import { SAMPLE_CSRF } from '@/test/msw/handlers/staff';
import { seenRegistrationRequests, resetRegistrationRequests } from '@/test/msw/handlers/registrations';

describe('the browser BFF client', () => {
  it('reads a body through a parser and returns the parsed value', async () => {
    resetRegistrationRequests();
    const result = await bffGet('/api/bff/registrations/r1', (value) => (value as { serviceName: string }).serviceName);
    expect(result).toEqual({ ok: true, data: 'UCR East' });
  });

  it('posts with the CSRF token and the idempotency key it was given', async () => {
    resetRegistrationRequests();
    const result = await bffPost('/api/bff/scope', { name: 'x', category: 'reablement', flag: 'later', reason: 'r' }, 'key-1');
    expect(result.ok).toBe(true);
    const seen = seenRegistrationRequests.at(-1);
    expect(seen?.csrf).toBe(SAMPLE_CSRF);
    expect(seen?.idempotencyKey).toBe('key-1');
  });
});
