import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getSession, type Role, type Session } from '@/lib/auth/session';
import { runAxe } from '@/test/a11y';
import { BOARD_A, BOARD_B, GENERATED_AT } from '@/test/fixtures/board';
import {
  BACKEND_BASE,
  BOARD_URL,
  resetSeenBoardRequests,
  seenBoardRequests,
  TOKEN_ORG_A,
  TOKEN_ORG_B,
} from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import WallScreenPage from './page';

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

function signedIn(role: Role, backendToken: string = TOKEN_ORG_A): Session {
  return {
    role,
    services: [],
    sub: 'screen-1',
    backendToken,
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  };
}

function as(session: Session | null) {
  vi.mocked(getSession).mockResolvedValue(session);
}

async function redirectOf(): Promise<string> {
  try {
    await WallScreenPage();
  } catch (error) {
    if (error instanceof Redirected) return error.url;
    throw error;
  }
  throw new Error('the page did not redirect');
}

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  resetSeenBoardRequests();
  // The wall now judges a board by the clock (W06): the sample board is the
  // sample time, so the clock is set to it. Only Date is faked.
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date(GENERATED_AT));
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
  vi.mocked(getSession).mockReset();
});

describe('wall screen page: signed in', () => {
  it('shows the board for the paired screen: heading, nine tiles in order, legend and footer', async () => {
    as(signedIn('wall'));

    const { container } = render(await WallScreenPage());

    expect(screen.getByRole('heading', { level: 1, name: 'Dorset urgent care capacity' })).toBeInTheDocument();
    expect(
      Array.from(container.querySelectorAll('[data-el="WALL-TILE"]')).map((t) => t.getAttribute('data-service-id')),
    ).toEqual(BOARD_A.entries.map((e) => e.serviceId));
    expect(screen.getByText('Updated 9 min ago · next due 14:30')).toBeInTheDocument();
    expect(screen.getByText('Not updated for 4 hrs 10 min · was due 12:00')).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Status key' })).toBeInTheDocument();
    expect(screen.getByText('No patient information on this screen')).toBeInTheDocument();
  });

  it.each<Role>(['wall', 'advisor', 'lead', 'exec'])('shows the board to a %s session', async (role) => {
    as(signedIn(role));

    render(await WallScreenPage());

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('urgent care capacity');
  });

  it('reads the board with the session token, as a GET with no query string', async () => {
    as(signedIn('wall'));

    await WallScreenPage();

    expect(seenBoardRequests).toHaveLength(1);
    expect(seenBoardRequests[0].method).toBe('GET');
    expect(seenBoardRequests[0].headers.get('authorization')).toBe(`Bearer ${TOKEN_ORG_A}`);
    expect(new URL(seenBoardRequests[0].url).search).toBe('');
  });

  it('takes no input: it has no props, so no URL or query string can choose an organisation', async () => {
    as(signedIn('wall'));

    expect(WallScreenPage.length).toBe(0);
    // Even if a framework passed a query string, it would be ignored.
    const page = await (WallScreenPage as unknown as (p: unknown) => Promise<React.ReactElement>)({
      searchParams: Promise.resolve({ tenant: TOKEN_ORG_B, organisation: 'Neighbouring' }),
      params: Promise.resolve({ tenant: TOKEN_ORG_B }),
    });
    render(page);

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Dorset urgent care capacity');
    expect(seenBoardRequests[0].headers.get('authorization')).toBe(`Bearer ${TOKEN_ORG_A}`);
  });

  it('never renders another organisation’s services on a screen paired to this one', async () => {
    as(signedIn('wall', TOKEN_ORG_A));

    const { container } = render(await WallScreenPage());

    expect(container.querySelectorAll('[data-el="WALL-TILE"]')).toHaveLength(BOARD_A.entries.length);
    for (const e of BOARD_B.entries) {
      expect(container.textContent).not.toContain(e.name);
      expect(container.innerHTML).not.toContain(e.serviceId);
    }
    expect(container.textContent).not.toContain('Neighbouring');
  });

  it('shows the other organisation’s board, and only that, for a screen paired to it', async () => {
    as(signedIn('wall', TOKEN_ORG_B));

    const { container } = render(await WallScreenPage());

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Neighbouring urgent care capacity');
    expect(container.querySelectorAll('[data-el="WALL-TILE"]')).toHaveLength(BOARD_B.entries.length);
    for (const e of BOARD_A.entries) expect(container.textContent).not.toContain(e.name);
  });

  it('has no accessibility violations', async () => {
    as(signedIn('wall'));

    const { container } = render(await WallScreenPage());

    expect(container.querySelectorAll('[data-el="WALL-TILE"]')).toHaveLength(BOARD_A.entries.length);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('wall screen page: the board is judged by the clock (W06)', () => {
  it('shows the board as current, with no banner, when it was just built', async () => {
    as(signedIn('wall'));

    const { container } = render(await WallScreenPage());

    expect(screen.queryByRole('alert')).toBeNull();
    expect(container.textContent).not.toContain('Last known');
  });

  it('shows Last known at the first paint, with the banner, when the back end serves a board that is already old', async () => {
    as(signedIn('wall'));
    vi.setSystemTime(new Date(Date.parse(GENERATED_AT) + 30 * 60_000));

    const { container } = render(await WallScreenPage());

    expect(screen.getByRole('alert')).toHaveTextContent('Tool offline since 14:12');
    for (const tile of container.querySelectorAll('[data-el="WALL-TILE"]')) {
      expect(tile).toHaveAttribute('data-status', 'last-known');
    }
    expect(container.textContent).not.toMatch(/Updated \d+ min ago/);
  });

  it('shows Last known, not a clean board, when the back end serves a board dated in the future', async () => {
    as(signedIn('wall'));
    vi.setSystemTime(new Date(Date.parse(GENERATED_AT) - 30 * 60_000));

    render(await WallScreenPage());

    expect(screen.getByRole('alert')).toBeInTheDocument();
  });
});

describe('wall screen page: not allowed to see the board', () => {
  it('redirects to /screen/pair with no session, and does not call the back end', async () => {
    as(null);

    expect(await redirectOf()).toBe('/screen/pair');
    expect(seenBoardRequests).toHaveLength(0);
  });

  it.each<Role>(['reporter', 'anonymous-link', 'support', 'audit', 'clinical', 'owner'])(
    'redirects a %s session to /screen/pair and does not call the back end',
    async (role) => {
      as(signedIn(role));

      expect(await redirectOf()).toBe('/screen/pair');
      expect(seenBoardRequests).toHaveLength(0);
    },
  );

  it.each([401, 403, 404])('redirects to /screen/pair when the back end answers %i', async (status) => {
    as(signedIn('wall'));
    server.use(http.get(BOARD_URL, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [] }, { status })));

    expect(await redirectOf()).toBe('/screen/pair');
  });
});

describe('wall screen page: the board cannot be read', () => {
  it.each([500, 502, 503])('shows Board unavailable and no figure when the back end answers %i', async (status) => {
    as(signedIn('wall'));
    server.use(http.get(BOARD_URL, () => HttpResponse.json({}, { status })));

    const { container } = render(await WallScreenPage());

    expect(screen.getByRole('alert')).toHaveTextContent('Board unavailable');
    expect(container.querySelector('[data-el="WALL-TILE"]')).toBeNull();
  });

  it('shows Board unavailable when the back end cannot be reached', async () => {
    as(signedIn('wall'));
    server.use(http.get(BOARD_URL, () => HttpResponse.error()));

    render(await WallScreenPage());

    expect(screen.getByRole('alert')).toHaveTextContent('Board unavailable');
  });

  it('shows Board unavailable, not a guess, when the board is not in the shape it expects', async () => {
    as(signedIn('wall'));
    server.use(http.get(BOARD_URL, () => HttpResponse.json({ resourceType: 'Parameters', parameter: [{ name: 'entry' }] })));

    const { container } = render(await WallScreenPage());

    expect(within(container).getByRole('alert')).toHaveTextContent('Board unavailable');
    expect(container.querySelector('[data-el="WALL-TILE"]')).toBeNull();
  });
});
