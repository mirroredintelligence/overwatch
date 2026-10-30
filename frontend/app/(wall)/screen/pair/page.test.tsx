import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getSession, type Role, type Session } from '@/lib/auth/session';
import { ScreenClientError } from '@/lib/screens/client';
import WallPairPage, { metadata } from './page';

class Redirected extends Error {
  constructor(readonly url: string) {
    super(`redirected to ${url}`);
  }
}

vi.mock('next/navigation', () => ({
  redirect: (url: string) => {
    throw new Redirected(url);
  },
  useRouter: () => ({ replace: vi.fn() }),
}));

vi.mock('@/lib/auth/session', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/auth/session')>()),
  getSession: vi.fn(),
}));

vi.mock('@/lib/screens/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/screens/client')>()),
  renewSession: vi.fn(async () => {
    throw new (await import('@/lib/screens/client')).ScreenClientError('not-found');
  }),
  startPairing: vi.fn(() => new Promise(() => {})),
  pollPairing: vi.fn(),
}));

function session(role: Role): Session {
  return { role, tenantId: 'trust-a', host: 'app.test', services: [], sub: 'dev-1', backendToken: 'a.b.c', expiresAt: new Date(Date.now() + 3_600_000).toISOString() };
}

beforeEach(() => {
  vi.mocked(getSession).mockResolvedValue(null);
});

describe('the wall screen pairing page /screen/pair', () => {
  it('is titled for the wall screen and is not for search engines', () => {
    expect(metadata.title).toBe('DIUCS capacity wall screen');
    expect(metadata.robots).toMatchObject({ index: false });
  });

  it('shows the pairing screen to a display with no session, and needs no sign-in', async () => {
    render(await WallPairPage());
    expect(screen.getByRole('heading', { level: 1, name: 'DIUCS capacity wall screen' })).toBeInTheDocument();
    expect(getSession).toHaveBeenCalled();
  });

  it('sends a display that already has a wall session to the board', async () => {
    vi.mocked(getSession).mockResolvedValue(session('wall'));
    await expect(WallPairPage()).rejects.toMatchObject({ url: '/screen' });
  });

  it('does not treat a staff session as a paired screen, and shows the pairing screen', async () => {
    vi.mocked(getSession).mockResolvedValue(session('lead'));
    render(await WallPairPage());
    expect(screen.getByRole('heading', { level: 1, name: 'DIUCS capacity wall screen' })).toBeInTheDocument();
  });

  it('takes no input: the address, a query string or a header cannot name a screen, an organisation or a code', () => {
    expect(WallPairPage.length).toBe(0);
    expect(ScreenClientError).toBeDefined();
  });
});
