import { render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getSession, type Role, type Session } from '@/lib/auth/session';
import { BOARD_A } from '@/test/fixtures/board';
import { BACKEND_BASE, TOKEN_ORG_A } from '@/test/msw/handlers/board';
import { networkBffHandlers } from '@/test/msw/handlers/networkBff';
import { server } from '@/test/msw/server';
import { sessionFor } from '@/test/requests';
import { TENANTS } from '@/test/tenants';
import ExecHomePage from './page';
import ExecServicesPage from './services/page';
import ExecServicePage from './services/[id]/page';

// WB11 (docs/design/network-ui.md section 9, "Exec home" and "Exec service detail"): the executive's own home,
// service list and service detail say which board they are, and offer the switch to the network variant when
// the organisation is in a network. The pages are otherwise as they were: the executive's alerts stay the
// organisation's own, and the service detail has no alert subscription to take away.

class Redirected extends Error {
  constructor(readonly url: string) {
    super(`redirected to ${url}`);
  }
}

vi.mock('next/navigation', () => ({
  redirect: (url: string) => {
    throw new Redirected(url);
  },
  notFound: () => {
    throw new Error('not found');
  },
  useRouter: () => ({ replace: vi.fn() }),
}));

vi.mock('@/lib/auth/session', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/auth/session')>()),
  getSession: vi.fn(),
}));

const as = (role: Role) => vi.mocked(getSession).mockResolvedValue(sessionFor(TENANTS.A, role, { sub: 'u', backendToken: TOKEN_ORG_A }) as Session);

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  server.use(...networkBffHandlers);
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.mocked(getSession).mockReset();
});

describe('the executive’s pages in a network', () => {
  it('home: says it shows our organisation and offers the network home', async () => {
    as('exec');
    render(await ExecHomePage());
    const header = await screen.findByRole('region', { name: 'Which board you are viewing' });
    expect(header).toHaveTextContent('Showing: Our organisation');
    const nav = await within(header).findByRole('navigation', { name: 'Choose the board' });
    expect(within(nav).getByRole('link', { name: 'Network' })).toHaveAttribute('href', '/network/home');
    expect(within(nav).getByRole('link', { name: 'Our organisation' })).toHaveAttribute('href', '/planning');
  });

  it('services: offers the network’s services', async () => {
    as('exec');
    render(await ExecServicesPage());
    const nav = await screen.findByRole('navigation', { name: 'Choose the board' });
    expect(within(nav).getByRole('link', { name: 'Network' })).toHaveAttribute('href', '/network/services');
    expect(within(nav).getByRole('link', { name: 'Our organisation' })).toHaveAttribute('href', '/planning/services');
  });

  it('service detail: offers the network’s services, and has no alert subscription of its own', async () => {
    as('exec');
    render(await ExecServicePage({ params: Promise.resolve({ id: BOARD_A.entries[0]!.serviceId }) }));
    const nav = await screen.findByRole('navigation', { name: 'Choose the board' });
    expect(within(nav).getByRole('link', { name: 'Network' })).toHaveAttribute('href', '/network/services');
    expect(screen.queryByRole('button', { name: /subscribe|alert me|notify/i })).toBeNull();
  });

  it('shows no switch to a lead, who has no network home', async () => {
    as('lead');
    render(await ExecHomePage());
    await screen.findByRole('region', { name: 'Which board you are viewing' });
    expect(screen.queryByRole('navigation', { name: 'Choose the board' })).toBeNull();
  });
});
