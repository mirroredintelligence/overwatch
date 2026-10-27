import { describe, expect, it } from 'vitest';
import { server } from './server';

describe('MSW test server', () => {
  it('is set up to reject any request that no handler mocks', async () => {
    const failure = await fetch('http://backend.test/fhir/NotMocked').then(
      () => new Error('the request was answered'),
      (error: unknown) => error,
    );

    expect(failure).toBeInstanceOf(Error);
    expect((failure as Error).message).toContain('onUnhandledRequest');
  });

  it('provides the per-test handler helpers', () => {
    expect(typeof server.use).toBe('function');
    expect(typeof server.resetHandlers).toBe('function');
  });
});
