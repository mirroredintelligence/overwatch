import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetLeadPosts, SCREEN_LIST, seenLeadPosts } from '@/test/msw/handlers/lead';
import { server } from '@/test/msw/server';
import { ScreenList } from './ScreenList';

// The lead's wall screens page (docs/design/redesign/boards/lead/Screens.dc.html; brief lead-and-setup.md,
// "/lead/screens"): one card per screen with a preview thumbnail, its status in words, where it is, when it was
// last seen and which board it shows; the actions per state; unpair is an inline confirm on the screen's own
// card. The answers are the BFF's, which are the back end's GET /screens, PUT /screens/{id}/board-scope and
// POST /screens/{id}/revoke (routes_screens.py).

beforeEach(() => {
  resetLeadPosts();
  document.cookie = 'overwatch_csrf=csrf-token-1; path=/';
});

const cardOf = async (name: string) => (await screen.findByRole('region', { name })) as HTMLElement;

describe('ScreenList: the list', () => {
  it('has the board’s heading, the add button and one card per screen', async () => {
    render(<ScreenList />);
    expect(screen.getByRole('heading', { level: 1, name: 'Wall screens' })).toBeInTheDocument();
    expect(screen.getByText('The screens that show a live board. A screen shows capacity only, never patient information.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Add a wall screen' })).toHaveAttribute('href', '/lead/screens/new');
    const list = await screen.findByRole('list', { name: 'Wall screens in your organisation' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(6);
    expect(screen.getAllByRole('region')).toHaveLength(6);
  });

  it('shows each screen as a card with its place, its status in words and when it was last seen', async () => {
    render(<ScreenList />);
    const ward = await cardOf('Ward 4 corridor');
    expect(within(ward).getByText('Level 2')).toBeInTheDocument();
    expect(within(ward).getByText('Online')).toBeInTheDocument();
    expect(ward).toHaveTextContent('Shows Our organisation · seen just now');
    expect(within(ward).getByText('just now', { selector: 'time' })).toBeInTheDocument();

    const reception = await cardOf('Reception');
    expect(within(reception).getByText('Not showing the board')).toBeInTheDocument();
    expect(reception).toHaveTextContent('Last seen 2 hrs 20 min ago. Shows Our organisation.');
    expect(within(reception).getByText('2 hrs 20 min ago', { selector: 'time' })).toBeInTheDocument();

    const dayRoom = await cardOf('Day room');
    expect(within(dayRoom).getByText('Waiting for a code')).toBeInTheDocument();
    expect(within(dayRoom).getByText('Not given')).toBeInTheDocument();
    expect(dayRoom).toHaveTextContent('Shows Our organisation · not seen yet');
  });

  it('draws the preview thumbnail as decoration, hidden from screen readers and with no text', async () => {
    render(<ScreenList />);
    const ward = await cardOf('Ward 4 corridor');
    const thumb = ward.querySelector('[data-el="SCREENS-THUMB"]');
    expect(thumb).toHaveAttribute('aria-hidden', 'true');
    expect(thumb?.textContent).toBe('');
  });

  it('says which board each screen shows: the organisation’s own or a network, by name', async () => {
    render(<ScreenList />);
    expect(await cardOf('Ward 4 corridor')).toHaveTextContent('Shows Our organisation');
    expect(await cardOf('Staff room')).toHaveTextContent('Shows Network, West Dorset system');
  });

  it('says a screen set to a network that is no longer open to it shows the organisation’s own board, and why', async () => {
    render(<ScreenList />);
    const lobby = await cardOf('Lobby');
    expect(lobby).toHaveTextContent('Shows Our organisation');
    expect(within(lobby).getByText('Set to Network, Old system, which is no longer open to it.')).toBeInTheDocument();
  });

  it('says a screen that was unpaired is unpaired and when, and offers only to pair it again', async () => {
    render(<ScreenList />);
    const old = await cardOf('Old canteen screen');
    expect(within(old).getByText('Unpaired')).toBeInTheDocument();
    expect(old).toHaveTextContent('Unpaired on Thu 29 Oct, 16:05.');
    expect(within(old).queryByRole('button')).not.toBeInTheDocument();
    expect(within(old).getByRole('link', { name: 'Pair again for Old canteen screen' })).toHaveAttribute('href', '/lead/screens/new');
  });

  it('gives each live screen its own Change the board and Unpair buttons, named for the screen', async () => {
    render(<ScreenList />);
    await cardOf('Ward 4 corridor');
    expect(screen.getByRole('button', { name: 'Change the board for Ward 4 corridor' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Unpair Day room' })).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /^Unpair / })).toHaveLength(5);
    expect(screen.getAllByRole('button', { name: /^Change the board for / })).toHaveLength(5);
  });

  it('shows Pair again for a screen that is offline or was never connected, not for one that is online or waiting', async () => {
    server.use(
      http.get('/api/bff/screens', () =>
        HttpResponse.json({ ...SCREEN_LIST, screens: [...SCREEN_LIST.screens, { ...SCREEN_LIST.screens[0], deviceId: 's-7', name: 'Back door', state: 'never-connected', lastSeenAt: null }] }),
      ),
    );
    render(<ScreenList />);
    const back = await cardOf('Back door');
    expect(within(back).getByText('Never connected')).toBeInTheDocument();
    expect(within(back).getByRole('link', { name: 'Pair again for Back door' })).toBeInTheDocument();
    expect(within(await cardOf('Reception')).getByRole('link', { name: 'Pair again for Reception' })).toBeInTheDocument();
    expect(within(await cardOf('Ward 4 corridor')).queryByRole('link', { name: /Pair again/ })).not.toBeInTheDocument();
    expect(within(await cardOf('Day room')).queryByRole('link', { name: /Pair again/ })).not.toBeInTheDocument();
  });

  it('has the element ids, shared by every card (no screen id in an id)', async () => {
    const { container } = render(<ScreenList />);
    await cardOf('Ward 4 corridor');
    expect(container.querySelector('[data-el="SCREENS-ADD-BTN"]')).toBe(screen.getByRole('link', { name: 'Add a wall screen' }));
    expect(container.querySelectorAll('[data-el="SCREENS-BOARD-BTN"]').length).toBeGreaterThan(1);
    expect(container.querySelectorAll('[data-el="SCREENS-UNPAIR-BTN"]').length).toBeGreaterThan(1);
    expect(container.querySelectorAll('[data-el="SCREENS-REPAIR-BTN"]').length).toBeGreaterThan(0);
    for (const element of container.querySelectorAll('[data-el]')) expect(element.getAttribute('data-el')).toMatch(/^[A-Z0-9]+(-[A-Z0-9]+)*$/);
    expect(container.innerHTML).not.toContain('s-1');
  });

  it('says there are no screens, with the way to add one, when the list is empty', async () => {
    server.use(http.get('/api/bff/screens', () => HttpResponse.json({ ...SCREEN_LIST, screens: [] })));
    render(<ScreenList />);
    expect(await screen.findByText('No screens are connected yet.')).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Wall screens in your organisation' })).not.toBeInTheDocument();
  });

  it('says the screens could not be loaded, never an empty list, for a failed or malformed read', async () => {
    server.use(http.get('/api/bff/screens', () => HttpResponse.json({ code: 'unavailable' }, { status: 503 })));
    const first = render(<ScreenList />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the screens.');
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
    first.unmount();

    server.use(http.get('/api/bff/screens', () => HttpResponse.json({ nothing: true })));
    render(<ScreenList />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the screens.');
    expect(screen.queryByText('No screens are connected yet.')).not.toBeInTheDocument();
  });

  it('shows no token, hash or secret, and no tenant or network identifier', async () => {
    render(<ScreenList />);
    await cardOf('Ward 4 corridor');
    const text = document.body.textContent ?? '';
    expect(text).not.toMatch(/token|secret|hash|net-west|net-gone|tenant/i);
  });

  it('has no axe violations', async () => {
    const { container } = render(<ScreenList />);
    await cardOf('Ward 4 corridor');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('ScreenList: which board a screen shows (ScreenBoardChoice)', () => {
  async function open(name: string) {
    const user = userEvent.setup();
    render(<ScreenList />);
    await user.click(await screen.findByRole('button', { name: `Change the board for ${name}` }));
    return { user, dialog: screen.getByRole('dialog') };
  }

  it('asks which board the screen shows, with the organisation’s own and each network the server offered', async () => {
    const { dialog } = await open('Ward 4 corridor');
    expect(dialog).toHaveAccessibleName('Which board does Ward 4 corridor show?');
    const own = within(dialog).getByRole('radio', { name: 'Our organisation' });
    const network = within(dialog).getByRole('radio', { name: 'Network, West Dorset system' });
    expect(own).toBeChecked();
    expect(network).not.toBeChecked();
    expect(own).toHaveAttribute('data-el', 'SCREENS-BOARD-OWN-RADIO');
    expect(network).toHaveAttribute('data-el', 'SCREENS-BOARD-NETWORK-RADIO');
    expect(within(dialog).getByText('The screen changes the next time it refreshes. Its header always says which board it shows.')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Save' })).toHaveAttribute('data-el', 'SCREENS-BOARD-SAVE-BTN');
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveAttribute('data-el', 'SCREENS-BOARD-CANCEL-BTN');
  });

  it('starts on the board the screen shows now', async () => {
    const { dialog } = await open('Staff room');
    expect(within(dialog).getByRole('radio', { name: 'Network, West Dorset system' })).toBeChecked();
  });

  it('starts on the organisation’s own board, and says so, for a screen set to a network that is no longer open to it', async () => {
    const { dialog } = await open('Lobby');
    expect(within(dialog).getByRole('radio', { name: 'Our organisation' })).toBeChecked();
    expect(within(dialog).getByText(/is set to Network, Old system, which your organisation can no longer see/)).toBeInTheDocument();
  });

  it('offers only the organisation’s own board, with the hint, when it is in no network', async () => {
    server.use(http.get('/api/bff/screens', () => HttpResponse.json({ ...SCREEN_LIST, networks: [], screens: SCREEN_LIST.screens.filter((s) => s.boardScope === 'tenant') })));
    const { dialog } = await open('Ward 4 corridor');
    expect(within(dialog).getAllByRole('radio')).toHaveLength(1);
    expect(within(dialog).getByText('Your organisation is not in a network.')).toBeInTheDocument();
  });

  it('keeps Save off until the board is changed', async () => {
    const { user, dialog } = await open('Ward 4 corridor');
    expect(within(dialog).getByRole('button', { name: 'Save' })).toBeDisabled();
    await user.click(within(dialog).getByRole('radio', { name: 'Network, West Dorset system' }));
    expect(within(dialog).getByRole('button', { name: 'Save' })).toBeEnabled();
  });

  it('sends nothing on Cancel and gives the focus back to the button that opened the dialog', async () => {
    const { user, dialog } = await open('Ward 4 corridor');
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(seenLeadPosts).toHaveLength(0);
    expect(screen.getByRole('button', { name: 'Change the board for Ward 4 corridor' })).toHaveFocus();
  });

  it('puts the choice with the screen’s version as If-Match, the CSRF token and a key, says it is done and reads the list again', async () => {
    let reads = 0;
    let changed = false;
    server.use(
      http.get('/api/bff/screens', () => {
        reads += 1;
        const screens = SCREEN_LIST.screens.map((s) => (changed && s.deviceId === 's-1' ? { ...s, boardScope: 'network', networkId: 'net-west', networkName: 'West Dorset system', scopeVersion: 4 } : s));
        return HttpResponse.json({ ...SCREEN_LIST, screens });
      }),
    );
    const { user, dialog } = await open('Ward 4 corridor');
    changed = true;
    await user.click(within(dialog).getByRole('radio', { name: 'Network, West Dorset system' }));
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Ward 4 corridor now shows Network, West Dorset system.');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(seenLeadPosts).toHaveLength(1);
    expect(seenLeadPosts[0]).toMatchObject({ path: '/api/bff/screens/s-1/board-scope', csrf: 'csrf-token-1', ifMatch: 'W/"1"', body: { boardScope: 'network', networkId: 'net-west' } });
    expect(seenLeadPosts[0]!.idempotencyKey).toBeTruthy();
    expect(reads).toBe(2);
    expect(await cardOf('Ward 4 corridor')).toHaveTextContent('Shows Network, West Dorset system');
  });

  it('sends the screen back to its own board with no network id', async () => {
    const { user, dialog } = await open('Staff room');
    await user.click(within(dialog).getByRole('radio', { name: 'Our organisation' }));
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Staff room now shows Our organisation.');
    expect(seenLeadPosts[0]).toMatchObject({ ifMatch: 'W/"3"', body: { boardScope: 'tenant' } });
    expect(seenLeadPosts[0]!.body).not.toHaveProperty('networkId');
  });

  it('only ever sends a network the server offered', async () => {
    const { user, dialog } = await open('Ward 4 corridor');
    await user.click(within(dialog).getByRole('radio', { name: 'Network, West Dorset system' }));
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(seenLeadPosts).toHaveLength(1));
    expect((seenLeadPosts[0]!.body as { networkId: string }).networkId).toBe(SCREEN_LIST.networks[0]!.id);
  });

  it('says the board was changed by someone else, and reads the list again, on a 412', async () => {
    server.use(http.put('/api/bff/screens/:id/board-scope', () => HttpResponse.json({ code: 'invalid' }, { status: 412 })));
    const { user, dialog } = await open('Ward 4 corridor');
    await user.click(within(dialog).getByRole('radio', { name: 'Network, West Dorset system' }));
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Someone else changed this screen’s board. The list has been read again. Choose again.');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('says the screen or the network is not there any more on a 404', async () => {
    server.use(http.put('/api/bff/screens/:id/board-scope', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    const { user, dialog } = await open('Ward 4 corridor');
    await user.click(within(dialog).getByRole('radio', { name: 'Network, West Dorset system' }));
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('That screen or that board is not available any more. The list has been read again.');
  });

  it('says the session has ended, with the way to sign in, on a 401 or 403', async () => {
    server.use(http.put('/api/bff/screens/:id/board-scope', () => HttpResponse.json({ code: 'session-ended' }, { status: 401 })));
    const { user, dialog } = await open('Ward 4 corridor');
    await user.click(within(dialog).getByRole('radio', { name: 'Network, West Dorset system' }));
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Your session has ended.');
    expect(within(alert).getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/sign-in?next=%2Flead%2Fscreens');
  });

  it('keeps the dialog open on another failure, and a second try sends the same key', async () => {
    const keys: (string | null)[] = [];
    let fail = true;
    server.use(
      http.put('/api/bff/screens/:id/board-scope', ({ request, params }) => {
        keys.push(request.headers.get('idempotency-key'));
        if (fail) return HttpResponse.json({ code: 'unavailable' }, { status: 503 });
        return HttpResponse.json({ deviceId: String(params.id), boardScope: 'network', networkId: 'net-west', networkName: 'West Dorset system', networkAvailable: true, scopeVersion: 2 });
      }),
    );
    const { user, dialog } = await open('Ward 4 corridor');
    await user.click(within(dialog).getByRole('radio', { name: 'Network, West Dorset system' }));
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('The board could not be changed. Try again.');
    fail = false;
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));
    await screen.findByRole('status');
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  it('has no axe violations in the dialog', async () => {
    const { dialog } = await open('Ward 4 corridor');
    expect(await runAxe(dialog)).toHaveNoViolations();
  });
});

describe('ScreenList: unpairing a screen (the inline confirm on the card)', () => {
  const confirmOf = () => screen.getByRole('region', { name: 'Unpair this screen?' });

  it('replaces the screen’s own card with the question, names the screen, says what happens, and is not a dialog', async () => {
    const user = userEvent.setup();
    render(<ScreenList />);
    await user.click(await screen.findByRole('button', { name: 'Unpair Ward 4 corridor' }));
    const confirm = confirmOf();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(within(confirm).getByText('Ward 4 corridor')).toBeInTheDocument();
    expect(within(confirm).getByText('It stops showing the board at once and goes back to asking for a code. You can pair it again later.')).toBeInTheDocument();
    expect(within(confirm).getByRole('button', { name: 'Unpair Ward 4 corridor' })).toHaveAttribute('data-el', 'SCREENS-UNPAIR-CONFIRM-BTN');
    expect(within(confirm).getByRole('button', { name: 'Keep it' })).toHaveAttribute('data-el', 'SCREENS-CLAIM-CANCEL-BTN');
    expect(within(confirm).queryByRole('button', { name: 'Change the board for Ward 4 corridor' })).not.toBeInTheDocument();
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('puts the focus on Keep it, the safe choice, when the question opens', async () => {
    const user = userEvent.setup();
    render(<ScreenList />);
    await user.click(await screen.findByRole('button', { name: 'Unpair Ward 4 corridor' }));
    expect(within(confirmOf()).getByRole('button', { name: 'Keep it' })).toHaveFocus();
  });

  it('closes on Keep it, sends nothing, and gives the card back with its Change the board button', async () => {
    const user = userEvent.setup();
    render(<ScreenList />);
    await user.click(await screen.findByRole('button', { name: 'Unpair Ward 4 corridor' }));
    await user.click(within(confirmOf()).getByRole('button', { name: 'Keep it' }));
    expect(screen.queryByRole('region', { name: 'Unpair this screen?' })).not.toBeInTheDocument();
    expect(seenLeadPosts).toHaveLength(0);
    expect(await cardOf('Ward 4 corridor')).toHaveTextContent('Shows Our organisation');
    expect(screen.getByRole('button', { name: 'Change the board for Ward 4 corridor' })).toBeInTheDocument();
  });

  it('closes on Escape, and sends nothing', async () => {
    const user = userEvent.setup();
    render(<ScreenList />);
    await user.click(await screen.findByRole('button', { name: 'Unpair Ward 4 corridor' }));
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('region', { name: 'Unpair this screen?' })).not.toBeInTheDocument();
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('sends one revoke with the CSRF token and a key, says it is done, and reads the list again', async () => {
    const user = userEvent.setup();
    let reads = 0;
    let revoked = false;
    server.use(
      http.get('/api/bff/screens', () => {
        reads += 1;
        const screens = SCREEN_LIST.screens.map((s) => (revoked && s.deviceId === 's-1' ? { ...s, state: 'revoked', revokedAt: '2026-10-30T10:00:00Z' } : s));
        return HttpResponse.json({ ...SCREEN_LIST, screens });
      }),
      http.post('/api/bff/screens/:id/revoke', ({ params }) => {
        revoked = true;
        return HttpResponse.json({ deviceId: String(params.id), status: 'revoked', revokedAt: '2026-10-30T10:00:00Z' });
      }),
    );
    render(<ScreenList />);
    await user.click(await screen.findByRole('button', { name: 'Unpair Ward 4 corridor' }));
    await user.click(within(confirmOf()).getByRole('button', { name: 'Unpair Ward 4 corridor' }));

    expect(await screen.findByRole('status')).toHaveTextContent('Ward 4 corridor was unpaired.');
    expect(screen.queryByRole('region', { name: 'Unpair this screen?' })).not.toBeInTheDocument();
    expect(reads).toBe(2);
    const card = await cardOf('Ward 4 corridor');
    expect(within(card).getByText('Unpaired')).toBeInTheDocument();
    expect(within(card).queryByRole('button')).not.toBeInTheDocument();
  });

  it('posts to the screen’s own revoke route, with the CSRF header and an Idempotency-Key', async () => {
    const user = userEvent.setup();
    render(<ScreenList />);
    await user.click(await screen.findByRole('button', { name: 'Unpair Day room' }));
    await user.click(within(confirmOf()).getByRole('button', { name: 'Unpair Day room' }));
    await waitFor(() => expect(seenLeadPosts).toHaveLength(1));
    expect(seenLeadPosts[0]).toMatchObject({ path: '/api/bff/screens/s-2/revoke', csrf: 'csrf-token-1' });
    expect(seenLeadPosts[0]!.idempotencyKey).toBeTruthy();
  });

  it('keeps the question open and says so when the back end fails, and a second try uses the same key', async () => {
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
    await user.click(await screen.findByRole('button', { name: 'Unpair Reception' }));
    const confirm = confirmOf();
    await user.click(within(confirm).getByRole('button', { name: 'Unpair Reception' }));
    expect(await within(confirm).findByRole('alert')).toHaveTextContent('The screen could not be unpaired. Try again.');
    fail = false;
    await user.click(within(confirm).getByRole('button', { name: 'Unpair Reception' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Reception was unpaired.');
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  it('asks for a new key for a different screen', async () => {
    const user = userEvent.setup();
    render(<ScreenList />);
    await user.click(await screen.findByRole('button', { name: 'Unpair Day room' }));
    await user.click(within(confirmOf()).getByRole('button', { name: 'Unpair Day room' }));
    await screen.findByRole('status');
    await user.click(await screen.findByRole('button', { name: 'Unpair Reception' }));
    await user.click(within(confirmOf()).getByRole('button', { name: 'Unpair Reception' }));
    await waitFor(() => expect(seenLeadPosts).toHaveLength(2));
    expect(seenLeadPosts[0]!.idempotencyKey).not.toBe(seenLeadPosts[1]!.idempotencyKey);
  });

  it('says the screen is no longer in the list, and reads the list again, when the back end does not know it (404)', async () => {
    const user = userEvent.setup();
    server.use(http.post('/api/bff/screens/:id/revoke', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    render(<ScreenList />);
    await user.click(await screen.findByRole('button', { name: 'Unpair Reception' }));
    await user.click(within(confirmOf()).getByRole('button', { name: 'Unpair Reception' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('That screen is not in the list any more.');
    expect(screen.queryByRole('region', { name: 'Unpair this screen?' })).not.toBeInTheDocument();
  });

  it('says the session has ended, with the way to sign in, on a 401 or 403', async () => {
    const user = userEvent.setup();
    server.use(http.post('/api/bff/screens/:id/revoke', () => HttpResponse.json({ code: 'session-ended' }, { status: 401 })));
    render(<ScreenList />);
    await user.click(await screen.findByRole('button', { name: 'Unpair Reception' }));
    await user.click(within(confirmOf()).getByRole('button', { name: 'Unpair Reception' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Your session has ended.');
    expect(within(alert).getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/sign-in?next=%2Flead%2Fscreens');
  });

  it('sends one revoke for a double press', async () => {
    const user = userEvent.setup();
    server.use(
      http.post('/api/bff/screens/:id/revoke', async ({ params }) => {
        await new Promise((resolve) => setTimeout(resolve, 30));
        return HttpResponse.json({ deviceId: String(params.id), status: 'revoked', revokedAt: '2026-10-30T10:00:00Z' });
      }),
    );
    let posts = 0;
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'POST') posts += 1;
    });
    render(<ScreenList />);
    await user.click(await screen.findByRole('button', { name: 'Unpair Reception' }));
    const confirm = within(confirmOf()).getByRole('button', { name: 'Unpair Reception' });
    await user.dblClick(confirm);
    await screen.findByRole('status');
    expect(posts).toBe(1);
    server.events.removeAllListeners();
  });
});
