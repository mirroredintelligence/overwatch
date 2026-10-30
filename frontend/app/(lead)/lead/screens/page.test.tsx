import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getSession, type Role, type Session } from '@/lib/auth/session';
import WallScreensPage, { metadata } from './page';

class Redirected extends Error {
  constructor(readonly url: string) {
    super(`redirected to ${url}`);
  }
}

vi.mock('next/navigation', () => ({
  redirect: (url: string) => {
    throw new Redirected(url);
  },
}));

vi.mock('@/lib/auth/session', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/auth/session')>()),
  getSession: vi.fn(),
}));

function session(role: Role): Session {
  return { role, tenantId: 'trust-a', host: 'app.test', services: [], sub: 'stf-1', backendToken: 'a.b.c', expiresAt: new Date(Date.now() + 3_600_000).toISOString() };
}

beforeEach(() => {
  vi.mocked(getSession).mockResolvedValue(session('lead'));
});

describe('the lead page /lead/screens', () => {
  it('is titled for the page and is not for search engines', () => {
    expect(metadata.title).toBe('Wall screens - DIUCS capacity');
    expect(metadata.robots).toMatchObject({ index: false });
  });

  it('shows the list to a shift lead', async () => {
    render(await WallScreensPage());
    expect(screen.getByRole('heading', { level: 1, name: 'Wall screens' })).toBeInTheDocument();
    expect(await screen.findByRole('table', { name: 'Wall screens in your organisation' })).toBeInTheDocument();
  });

  it('sends nobody to the list unless they are a lead, even if the proxy let them through', async () => {
    for (const role of ['advisor', 'clinical', 'owner', 'exec', 'wall', 'support', 'audit', 'reporter'] as const) {
      vi.mocked(getSession).mockResolvedValue(session(role));
      await expect(WallScreensPage()).rejects.toMatchObject({ url: '/sign-in?next=%2Flead%2Fscreens' });
    }
    vi.mocked(getSession).mockResolvedValue(null);
    await expect(WallScreensPage()).rejects.toMatchObject({ url: '/sign-in?next=%2Flead%2Fscreens' });
  });
});
