import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getSession, type Role, type Session } from '@/lib/auth/session';
import { resetProfileCache } from '@/lib/tenant/profile';
import { sessionFor } from '@/test/requests';
import { TENANTS } from '@/test/tenants';
import { GENERATED_AT } from '@/test/fixtures/board';
import { BOARD_BODY, OWN_ORGANISATION } from '@/test/fixtures/network';
import { BACKEND_BASE, TOKEN_ORG_A } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import WallScreenPage from './page';

// TEN-072: the wall's page reads the board the screen's administrator chose (docs/design/network-ui.md section
// 6): its own organisation's, or a network's, and the own board with a warning when the network closed to it.

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

const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');

function signedIn(role: Role): Session {
  return sessionFor(TENANTS.A, role, { sub: 'screen-1', backendToken: TOKEN_ORG_A });
}

beforeEach(() => {
  resetProfileCache();
  vi.stubEnv('OVERWATCH_FHIR_BASE_URL', BACKEND_BASE);
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date(GENERATED_AT));
  vi.mocked(getSession).mockResolvedValue(signedIn('wall'));
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
  vi.mocked(getSession).mockReset();
});

describe('wall screen page: which board', () => {
  it('shows the network a screen is set to: its name in the header and as the heading, and each row’s organisation', async () => {
    server.use(
      http.get(`${ROOT}/screens/me/board-scope`, () => HttpResponse.json({ boardScope: 'network', fallback: false, scopeVersion: 3, networkName: 'West Dorset system' })),
      http.get(`${ROOT}/screens/me/network-board`, () => HttpResponse.json(BOARD_BODY)),
    );
    render(await WallScreenPage());
    expect(screen.getByText('Showing: Network, West Dorset system')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'West Dorset system capacity' })).toBeInTheDocument();
    expect(screen.getAllByText(OWN_ORGANISATION).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Your organisation').length).toBeGreaterThan(0);
    expect(screen.getByText('Virtual ward frailty')).toBeInTheDocument();
  });

  it('shows the own board with the warning when the network is no longer open to the screen', async () => {
    server.use(http.get(`${ROOT}/screens/me/board-scope`, () => HttpResponse.json({ boardScope: 'tenant', fallback: true, fallbackReason: 'network-unavailable', scopeVersion: 4 })));
    render(await WallScreenPage());
    expect(screen.getByRole('alert')).toHaveTextContent('No longer showing the network board. Showing: Our organisation.');
    expect(screen.getByText('Showing: Our organisation')).toBeInTheDocument();
  });

  it('shows the own board, with no warning, for a screen on its own board', async () => {
    render(await WallScreenPage());
    expect(screen.getByText('Showing: Our organisation')).toBeInTheDocument();
    expect(screen.queryByText(/No longer showing/)).toBeNull();
  });

  it('sends a screen the back end refuses (revoked) to reconnect, as for the board', async () => {
    server.use(http.get(`${ROOT}/screens/me/board-scope`, () => HttpResponse.json({}, { status: 404 })));
    await expect(WallScreenPage()).rejects.toMatchObject({ url: '/screen/reconnect' });
  });

  it('shows no figure and says what to do when the network board cannot be read for another reason', async () => {
    server.use(
      http.get(`${ROOT}/screens/me/board-scope`, () => HttpResponse.json({ boardScope: 'network', fallback: false, scopeVersion: 3, networkName: 'West Dorset system' })),
      http.get(`${ROOT}/screens/me/network-board`, () => HttpResponse.json({}, { status: 503 })),
    );
    render(await WallScreenPage());
    expect(screen.queryByText('Virtual ward frailty')).toBeNull();
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });
});
