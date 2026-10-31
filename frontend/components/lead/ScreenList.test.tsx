import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetLeadPosts, SCREEN_LIST, seenLeadPosts } from '@/test/msw/handlers/lead';
import { server } from '@/test/msw/server';
import { ScreenList } from './ScreenList';

// The lead's list of wall screens and the disconnect (W9I, TEN-072). The answers are the BFF's, which
// are the back end's GET /screens and POST /screens/{id}/revoke (routes_screens.py).

beforeEach(() => {
  resetLeadPosts();
  document.cookie = 'diucs_csrf=csrf-token-1; path=/';
});

const rowOf = async (name: string) => (await screen.findByRole('row', { name: new RegExp(name) })) as HTMLElement;

describe('ScreenList: the list', () => {
  it('shows each screen with its place, its status in words, when it was paired and when it was last seen', async () => {
    render(<ScreenList />);
    const ward = await rowOf('Ward 4 corridor');
    expect(within(ward).getByText('Level 2')).toBeInTheDocument();
    expect(within(ward).getByText('Online')).toBeInTheDocument();
    expect(within(ward).getByText('Tue 27 Oct, 10:00')).toBeInTheDocument();
    expect(within(ward).getByText('Just now')).toBeInTheDocument();

    const reception = await rowOf('Reception');
    expect(within(reception).getByText('Offline')).toBeInTheDocument();
    expect(within(reception).getByText('2 hrs 20 min ago')).toBeInTheDocument();

    const dayRoom = await rowOf('Day room');
    expect(within(dayRoom).getByText('Waiting to connect')).toBeInTheDocument();
    expect(within(dayRoom).getByText('Not seen yet')).toBeInTheDocument();
  });

  it('says a disconnected screen is disconnected, when, and offers no way to disconnect it again', async () => {
    render(<ScreenList />);
    const old = await rowOf('Old canteen screen');
    expect(within(old).getByText('Disconnected')).toBeInTheDocument();
    expect(within(old).getByText('Thu 29 Oct, 16:05')).toBeInTheDocument();
    expect(within(old).queryByRole('button')).not.toBeInTheDocument();
  });

  it('gives each live screen its own disconnect button, named for the screen', async () => {
    render(<ScreenList />);
    await rowOf('Ward 4 corridor');
    expect(screen.getByRole('button', { name: 'Disconnect Ward 4 corridor' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Disconnect Day room' })).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /^Disconnect / })).toHaveLength(3);
  });

  it('has a caption, header cells, and links to add a screen and back to the lead page', async () => {
    render(<ScreenList />);
    const table = await screen.findByRole('table', { name: 'Wall screens in your organisation' });
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Screen', 'Status', 'Paired', 'Last seen', 'Action']);
    expect(screen.getByRole('link', { name: 'Add a screen' })).toHaveAttribute('href', '/lead/screens/new');
    expect(screen.getByRole('link', { name: 'Back to the shift lead page' })).toHaveAttribute('href', '/lead');
  });

  it('says there are no screens, with the way to add one, when the list is empty', async () => {
    server.use(http.get('/api/bff/screens', () => HttpResponse.json({ ...SCREEN_LIST, screens: [] })));
    render(<ScreenList />);
    expect(await screen.findByText('No screens are connected yet.')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('says the screens could not be loaded, never an empty table, for a failed or malformed read', async () => {
    server.use(http.get('/api/bff/screens', () => HttpResponse.json({ code: 'unavailable' }, { status: 503 })));
    const first = render(<ScreenList />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the screens.');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    first.unmount();

    server.use(http.get('/api/bff/screens', () => HttpResponse.json({ nothing: true })));
    render(<ScreenList />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the screens.');
    expect(screen.queryByText('No screens are connected yet.')).not.toBeInTheDocument();
  });

  it('shows no token, hash or secret, and no patient information', async () => {
    render(<ScreenList />);
    await rowOf('Ward 4 corridor');
    const text = document.body.textContent ?? '';
    expect(text).not.toMatch(/token|secret|hash/i);
  });

  it('has no axe violations', async () => {
    const { container } = render(<ScreenList />);
    await rowOf('Ward 4 corridor');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('ScreenList: disconnecting a screen', () => {
  it('asks first, naming the screen and saying what happens, and sends nothing on Cancel', async () => {
    const user = userEvent.setup();
    render(<ScreenList />);
    await user.click(await screen.findByRole('button', { name: 'Disconnect Ward 4 corridor' }));
    const dialog = screen.getByRole('dialog', { name: 'Disconnect Ward 4 corridor?' });
    expect(within(dialog).getByText(/stop showing the board straight away/)).toBeInTheDocument();
    expect(within(dialog).getByText(/pair it again with a new code/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('sends one revoke with the CSRF token and a key, says it is done, and reads the list again', async () => {
    const user = userEvent.setup();
    let reads = 0;
    let revoked = false;
    server.use(
      http.get('/api/bff/screens', () => {
        reads += 1;
        const screens = SCREEN_LIST.screens.map((s) =>
          revoked && s.deviceId === 's-1' ? { ...s, state: 'revoked', revokedAt: '2026-10-30T10:00:00Z' } : s,
        );
        return HttpResponse.json({ ...SCREEN_LIST, screens });
      }),
      http.post('/api/bff/screens/:id/revoke', ({ params }) => {
        revoked = true;
        return HttpResponse.json({ deviceId: String(params.id), status: 'revoked', revokedAt: '2026-10-30T10:00:00Z' });
      }),
    );
    render(<ScreenList />);
    await user.click(await screen.findByRole('button', { name: 'Disconnect Ward 4 corridor' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Disconnect screen' }));

    expect(await screen.findByRole('status')).toHaveTextContent('Ward 4 corridor was disconnected.');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(reads).toBe(2);
    const row = await rowOf('Ward 4 corridor');
    expect(within(row).getByText('Disconnected')).toBeInTheDocument();
    expect(within(row).queryByRole('button')).not.toBeInTheDocument();
  });

  it('posts to the screen’s own revoke route, with the CSRF header and an Idempotency-Key', async () => {
    const user = userEvent.setup();
    render(<ScreenList />);
    await user.click(await screen.findByRole('button', { name: 'Disconnect Day room' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Disconnect screen' }));
    await waitFor(() => expect(seenLeadPosts).toHaveLength(1));
    expect(seenLeadPosts[0]).toMatchObject({ path: '/api/bff/screens/s-2/revoke', csrf: 'csrf-token-1' });
    expect(seenLeadPosts[0]!.idempotencyKey).toBeTruthy();
  });

  it('keeps the dialog open and says so when the back end fails, and a second try uses the same key', async () => {
    const user = userEvent.setup();
    const keys: (string | null)[] = [];
    let fail = true;
    server.use(
      http.post('/api/bff/screens/:id/revoke', ({ request, params }) => {
        keys.push(request.headers.get('idempotency-key'));
        if (fail) return HttpResponse.json({ code: 'unavailable' }, { status: 503 });
        return HttpResponse.json({ deviceId: String(params.id), status: 'revoked', revokedAt: '2026-10-30T10:00:00Z' });
      }),
    );
    render(<ScreenList />);
    await user.click(await screen.findByRole('button', { name: 'Disconnect Reception' }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Disconnect screen' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('The screen could not be disconnected. Try again.');
    fail = false;
    await user.click(within(dialog).getByRole('button', { name: 'Disconnect screen' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Reception was disconnected.');
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  it('asks for a new key for a different screen', async () => {
    const user = userEvent.setup();
    render(<ScreenList />);
    await user.click(await screen.findByRole('button', { name: 'Disconnect Day room' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Disconnect screen' }));
    await screen.findByRole('status');
    await user.click(await screen.findByRole('button', { name: 'Disconnect Reception' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Disconnect screen' }));
    await waitFor(() => expect(seenLeadPosts).toHaveLength(2));
    expect(seenLeadPosts[0]!.idempotencyKey).not.toBe(seenLeadPosts[1]!.idempotencyKey);
  });

  it('says the screen is no longer in the list, and reads the list again, when the back end does not know it (404)', async () => {
    const user = userEvent.setup();
    server.use(http.post('/api/bff/screens/:id/revoke', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    render(<ScreenList />);
    await user.click(await screen.findByRole('button', { name: 'Disconnect Reception' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Disconnect screen' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('That screen is not in the list any more.');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('says the session has ended, with the way to sign in, on a 401 or 403', async () => {
    const user = userEvent.setup();
    server.use(http.post('/api/bff/screens/:id/revoke', () => HttpResponse.json({ code: 'session-ended' }, { status: 401 })));
    render(<ScreenList />);
    await user.click(await screen.findByRole('button', { name: 'Disconnect Reception' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Disconnect screen' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Your session has ended.');
    expect(within(alert).getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/sign-in?next=%2Flead%2Fscreens');
  });

  it('sends one revoke for a double press', async () => {
    const user = userEvent.setup();
    server.use(http.post('/api/bff/screens/:id/revoke', async ({ params }) => {
      await new Promise((resolve) => setTimeout(resolve, 30));
      return HttpResponse.json({ deviceId: String(params.id), status: 'revoked', revokedAt: '2026-10-30T10:00:00Z' });
    }));
    let posts = 0;
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'POST') posts += 1;
    });
    render(<ScreenList />);
    await user.click(await screen.findByRole('button', { name: 'Disconnect Reception' }));
    const confirm = within(screen.getByRole('dialog')).getByRole('button', { name: 'Disconnect screen' });
    await user.dblClick(confirm);
    await screen.findByRole('status');
    expect(posts).toBe(1);
    server.events.removeAllListeners();
  });
});
