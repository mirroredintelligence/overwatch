import { describe, expect, it, vi } from 'vitest';
import { GET } from './route';

describe('GET /api/bff/registrations', () => {
  it('answers 401 without a lead session, and calls nothing upstream', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const response = await GET(new Request('http://localhost/api/bff/registrations?tab=to-review'));
    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ code: 'no-session' });
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });
});
