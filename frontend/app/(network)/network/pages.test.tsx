import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getSession, ROLES, type Role, type Session } from '@/lib/auth/session';
import { networkBffHandlers } from '@/test/msw/handlers/networkBff';
import { server } from '@/test/msw/server';
import { sessionFor } from '@/test/requests';
import { TENANTS } from '@/test/tenants';
import NetworkBoardPage from './board/page';
import NetworkHistoryPage from './history/page';
import NetworkPhonesPage from './phones/page';
import NetworkServicesPage from './services/page';
import NetworkServicePage from './services/[id]/page';
import NetworkSystemNowPage from './system-now/page';
import NetworkWeekPage from './week/page';

// The network pages (TEN-070, TEN-071, W17, W43, TEN-082): each is a page of the five roles that see a
// network (the week of two), takes no input, and sends anyone else to sign in (the proxy guards them too).

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

const PAGES: [string, () => Promise<React.ReactElement>, string[]][] = [
  ['/network/board', () => NetworkBoardPage(), ['advisor', 'clinical', 'lead', 'owner', 'exec']],
  ['/network/history', () => NetworkHistoryPage(), ['advisor', 'clinical', 'lead', 'owner', 'exec']],
  ['/network/services', () => NetworkServicesPage(), ['advisor', 'clinical', 'lead', 'owner', 'exec']],
  ['/network/services/[id]', () => NetworkServicePage({ params: Promise.resolve({ id: 'lst-0001' }) }), ['advisor', 'clinical', 'lead', 'owner', 'exec']],
  ['/network/system-now', () => NetworkSystemNowPage(), ['advisor', 'clinical', 'lead', 'owner', 'exec']],
  ['/network/phones', () => NetworkPhonesPage(), ['advisor', 'clinical', 'lead', 'owner', 'exec']],
  ['/network/week', () => NetworkWeekPage(), ['lead', 'exec']],
];

const as = (role: Role | null) => vi.mocked(getSession).mockResolvedValue(role === null ? null : (sessionFor(TENANTS.A, role) as Session));

beforeEach(() => server.use(...networkBffHandlers));
afterEach(() => vi.mocked(getSession).mockReset());

describe.each(PAGES)('%s', (_path, page, allowed) => {
  it('sends a visitor with no session to sign in', async () => {
    as(null);
    await expect(page()).rejects.toMatchObject({ url: '/sign-in' });
  });

  it.each(ROLES.filter((role) => !allowed.includes(role)))('does not show the page to the role %s', async (role) => {
    as(role);
    await expect(page()).rejects.toBeInstanceOf(Redirected);
  });

  it.each(allowed)('shows the page to the role %s, which names no network, tenant or scope in its address', async (role) => {
    as(role as Role);
    const { container } = render(await page());
    expect(await screen.findByRole('region', { name: 'Which board you are viewing' }, { timeout: 4000 })).toBeInTheDocument();
    expect(container.innerHTML).not.toMatch(/net-sample|trust-/);
  });
});

describe('the service page', () => {
  it('treats a reference that cannot be one as a service that is not there', async () => {
    as('advisor');
    render(await NetworkServicePage({ params: Promise.resolve({ id: '../../x' }) }));
    expect(await screen.findByText('Network view not available')).toBeInTheDocument();
  });
});
