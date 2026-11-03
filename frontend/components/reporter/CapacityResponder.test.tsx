import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { parseLinkView, type LinkView } from '@/lib/links/model';
import { runAxe } from '@/test/a11y';
import { EMPTY_VIEW, LINK, RECORDED_VIEW, THANKS_SEALED, csrfFor, renewCsrfFor } from '@/test/fixtures/links';
import { resetLinkRequests, seenBackendRequests, seenBffPosts, seenBffRenewCsrf } from '@/test/msw/handlers/links';
import { server } from '@/test/msw/server';
import { CapacityResponder } from './CapacityResponder';

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const viewOf = (token: string, fields: Record<string, unknown> = RECORDED_VIEW): LinkView =>
  parseLinkView({ ...fields, csrfToken: csrfFor(token) });

function renderFor(token: string, fields?: Record<string, unknown>) {
  return render(<CapacityResponder token={token} view={viewOf(token, fields)} />);
}

const FIGURE_BOX = 'Referrals in the next 2 hrs';
const figureOf = (container: HTMLElement) => container.querySelector('[data-figure]')?.getAttribute('data-figure');

beforeEach(() => {
  resetLinkRequests();
  push.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('CapacityResponder with a figure on record (artboard B1)', () => {
  it('shows the figure card: label, reply-by tag, the figure with its unit, when it was recorded and "Still right?"', async () => {
    const { container } = renderFor(LINK.recorded);
    expect(screen.getByRole('heading', { level: 1, name: 'UCR West' })).toBeInTheDocument();
    expect(screen.getByText('Capacity update')).toBeInTheDocument();
    expect(screen.getByText('Reply by 10:30')).toBeInTheDocument();
    expect(figureOf(container)).toBe('3');
    expect(screen.getByText('referrals in the next 2 hrs')).toBeInTheDocument();
    expect(screen.getByText('Recorded at 08:15. Still right?')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('offers one primary, a different number, and closed to referrals, and says what the link is', () => {
    renderFor(LINK.recorded);
    expect(screen.getByRole('button', { name: 'Yes, still 3' })).toHaveAttribute('data-el', 'REP-LINK-CONFIRM-BTN');
    expect(screen.getByRole('button', { name: 'Send a different number' })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByRole('button', { name: 'We are closed to referrals' })).toBeInTheDocument();
    expect(
      screen.getByText('This link works once and is for this phone. It closes at 10:30. Next update due 12:00.'),
    ).toBeInTheDocument();
    // The number controls stay shut until the person chooses to send a different number.
    expect(screen.queryByRole('textbox')).toBeNull();
  });

  it('puts the page in the link frame: the mark and "No login needed"', () => {
    renderFor(LINK.recorded);
    expect(screen.getByText('Overwatch')).toBeInTheDocument();
    expect(screen.getByText('No login needed')).toBeInTheDocument();
  });

  it('makes no POST while it renders', () => {
    renderFor(LINK.recorded);
    expect(seenBffPosts).toHaveLength(0);
    expect(seenBackendRequests.filter((r) => r.method === 'POST')).toHaveLength(0);
  });

  it('posts a confirm with the CSRF header, then opens the thank-you page with the sealed detail', async () => {
    renderFor(LINK.recorded);
    await userEvent.click(screen.getByRole('button', { name: 'Yes, still 3' }));
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(seenBffPosts).toEqual([{ token: LINK.recorded, body: { action: 'confirm' }, csrf: csrfFor(LINK.recorded) }]);
    const href = String(push.mock.calls[0]?.[0]);
    const address = new URL(href, 'https://x.test');
    // The address holds no link token and no figure in the clear: only the sealed detail (KI-179).
    expect(address.pathname).toBe('/l/thanks');
    expect(address.searchParams.get('d')).toBe(THANKS_SEALED);
    expect(href).not.toContain(LINK.recorded);
    expect(href).not.toContain('UCR');
  });
});

describe('a different number (artboard B1, board 2)', () => {
  it('opens the number controls in place, keeps the figure where it is, and moves focus to the heading', async () => {
    const { container } = renderFor(LINK.recorded);
    await userEvent.click(screen.getByRole('button', { name: 'Send a different number' }));
    expect(screen.getByRole('textbox', { name: FIGURE_BOX })).toHaveValue('3');
    expect(screen.getByText('New number of referrals')).toBeInTheDocument();
    expect(screen.getByText('referrals, usual range 0 to 8')).toBeInTheDocument();
    expect(figureOf(container)).toBe('3');
    expect(screen.getByText('Recorded at 08:15')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'UCR West' })).toHaveFocus();
    // One primary only: the confirm button is gone while the numbers are open.
    expect(screen.queryByRole('button', { name: 'Yes, still 3' })).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('steps up to 4, never moves the figure, and sends 4 with a button that says so', async () => {
    const { container } = renderFor(LINK.recorded);
    await userEvent.click(screen.getByRole('button', { name: 'Send a different number' }));
    await userEvent.click(screen.getByRole('button', { name: 'Increase by one' }));
    expect(screen.getByRole('textbox', { name: FIGURE_BOX })).toHaveValue('4');
    expect(figureOf(container)).toBe('3');
    await userEvent.click(screen.getByRole('button', { name: 'Send 4' }));
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(seenBffPosts.at(-1)?.body).toEqual({ action: 'number', value: 4 });
  });

  it('goes back to the first screen with Back, and posts nothing', async () => {
    renderFor(LINK.recorded);
    await userEvent.click(screen.getByRole('button', { name: 'Send a different number' }));
    await userEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByRole('button', { name: 'Yes, still 3' })).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(seenBffPosts).toHaveLength(0);
  });

  it('disables the send button, saying why, when the box is emptied', async () => {
    renderFor(LINK.recorded);
    await userEvent.click(screen.getByRole('button', { name: 'Send a different number' }));
    await userEvent.clear(screen.getByRole('textbox', { name: FIGURE_BOX }));
    expect(screen.getByRole('button', { name: 'Choose a number to send' })).toBeDisabled();
  });

  it('opens the number controls from the start on a wide screen, in the same page', () => {
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: true,
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }));
    renderFor(LINK.recorded);
    expect(screen.getByRole('textbox', { name: FIGURE_BOX })).toHaveValue('3');
    expect(screen.getByRole('button', { name: 'Yes, still 3' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send 3' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send a different number' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Back' })).toBeNull();
  });
});

describe('a figure far outside the usual range: ask once (artboard B2, board 2)', () => {
  async function sendNine() {
    renderFor(LINK.recorded);
    await userEvent.click(screen.getByRole('button', { name: 'Send a different number' }));
    const box = screen.getByRole('textbox', { name: FIGURE_BOX });
    await userEvent.clear(box);
    await userEvent.type(box, '9');
    await userEvent.click(screen.getByRole('button', { name: 'Send 9' }));
    await screen.findByText('Is 9 right?');
  }

  it('asks "Is 9 right?" with the figure and what happens next, and records nothing yet', async () => {
    await sendNine();
    expect(
      screen.getByText('That is far above your usual range of 0 to 8. If it is right, send it. The shift lead will be told so they can check.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Yes, send 9' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Change the number' })).toBeInTheDocument();
    expect(screen.getByText('Nothing is recorded until you press a button.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'UCR West' })).toHaveFocus();
    expect(push).not.toHaveBeenCalled();
  });

  it('sends the figure again, as a confirmed figure, with "Yes, send 9"', async () => {
    await sendNine();
    await userEvent.click(screen.getByRole('button', { name: 'Yes, send 9' }));
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(seenBffPosts.at(-1)?.body).toEqual({ action: 'number', value: 9, confirmOutOfRange: true });
  });

  it('goes back to the number controls with "Change the number", and a changed figure is asked about afresh', async () => {
    await sendNine();
    await userEvent.click(screen.getByRole('button', { name: 'Change the number' }));
    const box = screen.getByRole('textbox', { name: FIGURE_BOX });
    expect(box).toHaveValue('9');
    await userEvent.click(screen.getByRole('button', { name: 'Decrease by one' }));
    await userEvent.click(screen.getByRole('button', { name: 'Send 8' }));
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(seenBffPosts.at(-1)?.body).toEqual({ action: 'number', value: 8 });
  });
});

describe('closed to referrals: confirm once (artboard B2, board 3)', () => {
  it('asks "Tell advisors UCR West is closed?" first, and posts nothing', async () => {
    const { container } = renderFor(LINK.recorded);
    await userEvent.click(screen.getByRole('button', { name: 'We are closed to referrals' }));
    expect(screen.getByRole('heading', { level: 1, name: 'Tell advisors UCR West is closed?' })).toHaveFocus();
    expect(screen.getByText('Closed to referrals')).toBeInTheDocument();
    expect(
      screen.getByText('Advisors will not be offered UCR West. It shows as closed on the board until you send a number.'),
    ).toBeInTheDocument();
    expect(seenBffPosts).toHaveLength(0);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('sends "closed" only after "Yes, we are closed"', async () => {
    renderFor(LINK.recorded);
    await userEvent.click(screen.getByRole('button', { name: 'We are closed to referrals' }));
    await userEvent.click(screen.getByRole('button', { name: 'Yes, we are closed' }));
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(seenBffPosts.at(-1)?.body).toEqual({ action: 'closed' });
  });

  it('goes back with "No, go back", and posts nothing', async () => {
    renderFor(LINK.recorded);
    await userEvent.click(screen.getByRole('button', { name: 'We are closed to referrals' }));
    await userEvent.click(screen.getByRole('button', { name: 'No, go back' }));
    expect(screen.getByRole('button', { name: 'Yes, still 3' })).toBeInTheDocument();
    expect(seenBffPosts).toHaveLength(0);
  });
});

describe('sending', () => {
  it('says "Sending your answer." in a polite status and disables the buttons, so nothing posts twice', async () => {
    let posted = 0;
    server.use(
      http.post('/api/bff/links/:token', () => {
        posted += 1;
        return new Promise<Response>(() => undefined);
      }),
    );
    renderFor(LINK.recorded);
    await userEvent.click(screen.getByRole('button', { name: 'Yes, still 3' }));
    expect(screen.getByRole('status')).toHaveTextContent('Sending your answer.');
    expect(screen.getByRole('button', { name: 'Yes, still 3' })).toBeDisabled();
    await waitFor(() => expect(posted).toBe(1));
  });
});

describe('messages the back end gives', () => {
  it('says to send the number when the back end will not take a confirm, opens the number controls, and records nothing', async () => {
    renderFor(LINK.stale);
    await userEvent.click(screen.getByRole('button', { name: 'Yes, still 3' }));
    expect(await screen.findByText('Please send the number.')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: FIGURE_BOX })).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it('says to wait when the tenant’s link budget is used up', async () => {
    renderFor(LINK.limited);
    await userEvent.click(screen.getByRole('button', { name: 'Yes, still 3' }));
    expect(await screen.findByText('Too many tries. Wait a few minutes, then try again.')).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it('shows the expired page when the link is used or expires after this page loaded', async () => {
    renderFor(LINK.recorded);
    server.use(http.post('/api/bff/links/:token', () => HttpResponse.json({ state: 'used' }, { status: 410 })));
    await userEvent.click(screen.getByRole('button', { name: 'Yes, still 3' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'This link has expired' })).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Send me a new link' })).toBeNull();
  });

  it('offers a new link, with the renewal CSRF token the closed answer carried', async () => {
    renderFor(LINK.recorded);
    server.use(
      http.post('/api/bff/links/:token', () =>
        HttpResponse.json({ state: 'expired', csrfToken: renewCsrfFor(LINK.recorded) }, { status: 410 }),
      ),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Yes, still 3' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Send me a new link' }));
    expect(await screen.findByText('We have sent a new link.')).toBeInTheDocument();
    expect(seenBffRenewCsrf).toEqual([renewCsrfFor(LINK.recorded)]);
  });
});

describe('bad signal and failures (artboard B3, board 3; St)', () => {
  // The first POST fails with no answer at all (no signal); the next is recorded. Every POST is kept.
  const sent: { body: unknown; csrf: string | null }[] = [];
  const failOnce = () => {
    sent.length = 0;
    server.use(
      http.post('/api/bff/links/:token', async ({ request }) => {
        sent.push({ body: await request.json(), csrf: request.headers.get('x-csrf-token') });
        if (sent.length === 1) return HttpResponse.error();
        return HttpResponse.json({ serviceName: 'UCR West', value: 4, unitLabel: 'referrals in the next 2 hrs', recordedAt: '2026-10-23T09:12:00Z', nextDue: null, thanks: THANKS_SEALED });
      }),
    );
  };

  async function fourNotSent() {
    renderFor(LINK.recorded);
    await userEvent.click(screen.getByRole('button', { name: 'Send a different number' }));
    await userEvent.click(screen.getByRole('button', { name: 'Increase by one' }));
    await userEvent.click(screen.getByRole('button', { name: 'Send 4' }));
  }

  it('with no signal, says so, keeps the number on screen as "Not sent yet", and never spins', async () => {
    vi.spyOn(window.navigator, 'onLine', 'get').mockReturnValue(false);
    failOnce();
    await fourNotSent();
    expect(await screen.findByText('No signal. Not sent yet.')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Nothing has been lost. Your number is still here.');
    expect(screen.getByText('Not sent yet')).toBeInTheDocument();
    expect(screen.getByText('4', { selector: '[data-figure]' })).toBeInTheDocument();
    expect(screen.getByText('The link stays open until 10:30. Keep this page open, or reply to the text with the number.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again now' })).toBeEnabled();
    expect(push).not.toHaveBeenCalled();
  });

  it('sends the same answer again, with the same CSRF token, on "Try again now"', async () => {
    vi.spyOn(window.navigator, 'onLine', 'get').mockReturnValue(false);
    failOnce();
    await fourNotSent();
    await userEvent.click(await screen.findByRole('button', { name: 'Try again now' }));
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(sent).toHaveLength(2);
    expect(sent[1]).toEqual(sent[0]);
    expect(sent[0]).toEqual({ body: { action: 'number', value: 4 }, csrf: csrfFor(LINK.recorded) });
  });

  it('says "Back online." once when the signal returns, and keeps the number', async () => {
    const online = vi.spyOn(window.navigator, 'onLine', 'get').mockReturnValue(false);
    failOnce();
    await fourNotSent();
    await screen.findByText('No signal. Not sent yet.');
    online.mockReturnValue(true);
    act(() => {
      window.dispatchEvent(new Event('online'));
    });
    expect(await screen.findByText('Back online.')).toBeInTheDocument();
    expect(screen.queryByText('No signal. Not sent yet.')).toBeNull();
    expect(screen.getByText('4', { selector: '[data-figure]' })).toBeInTheDocument();
  });

  it('with a signal but a failed request, says it could not send, what was kept, and the way forward', async () => {
    server.use(http.post('/api/bff/links/:token', () => HttpResponse.json({}, { status: 503 })));
    renderFor(LINK.recorded);
    await userEvent.click(screen.getByRole('button', { name: 'Yes, still 3' }));
    expect(await screen.findByText('We could not send that.')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Your number is still here. Try again, or phone the shift lead.');
    expect(screen.getByRole('button', { name: 'Try again now' })).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });
});

describe('CapacityResponder with no figure yet (artboard B2, board 1)', () => {
  const EMPTY = EMPTY_VIEW as unknown as Record<string, unknown>;

  it('asks how many can be taken, with the number controls open and the send button disabled', async () => {
    const { container } = renderFor(LINK.empty, EMPTY);
    expect(screen.getByRole('heading', { level: 1, name: 'UCR West' })).toBeInTheDocument();
    expect(screen.getByText('First update')).toBeInTheDocument();
    expect(screen.getByText('Reply by 08:30')).toBeInTheDocument();
    expect(screen.getByText('How many referrals can you take in the next 2 hrs?')).toBeInTheDocument();
    expect(figureOf(container)).toBeUndefined();
    expect(screen.getByRole('textbox', { name: FIGURE_BOX })).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Choose a number to send' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'We are closed to referrals' })).toBeInTheDocument();
    expect(screen.getByText('This link works once and closes at 08:30. Next update due 10:00.')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('enables the button, which then names the number, once a number is chosen, and sends it', async () => {
    renderFor(LINK.empty, EMPTY);
    await userEvent.type(screen.getByRole('textbox', { name: FIGURE_BOX }), '4');
    const send = await screen.findByRole('button', { name: 'Send 4' });
    expect(send).toBeEnabled();
    await userEvent.click(send);
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(seenBffPosts.at(-1)?.body).toEqual({ action: 'number', value: 4 });
  });
});

describe('CapacityResponder accessibility', () => {
  it('labels the stepper, and names every button with words', async () => {
    renderFor(LINK.recorded);
    await userEvent.click(screen.getByRole('button', { name: 'Send a different number' }));
    expect(screen.getByRole('textbox', { name: FIGURE_BOX })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Decrease by one' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Increase by one' })).toBeInTheDocument();
  });
});
