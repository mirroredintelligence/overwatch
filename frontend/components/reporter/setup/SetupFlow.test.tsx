import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { seenBffRequests, resetReporterRequests } from '@/test/msw/handlers/reporter';
import { server } from '@/test/msw/server';
import { SetupFlow } from './SetupFlow';

// Full-suite runs share the machine: a PIN or form test clicks many keys, so it gets more time.
vi.setConfig({ testTimeout: 20_000 });

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

const INVITE = 'invite-token-sample';
const EXPIRED_TEXT = 'Invitations work for 48 hours. Ask your shift lead to send you a new one.';

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
  resetReporterRequests();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('SetupFlow', () => {
  it('welcomes the reporter with the service, the time it takes and the five steps, and passes axe', async () => {
    const { container } = render(<SetupFlow step="welcome" invite={INVITE} />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Set up capacity reporting for UCR West' })).toBeInTheDocument();
    expect(screen.getByText('About 3 minutes')).toBeInTheDocument();
    expect(
      screen.getByText('You can stop at any point and come back to the link in your text. It works for 48 hours.'),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Start' }));
    expect(push).toHaveBeenCalledWith(`/setup?step=number&invite=${INVITE}`);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('names the service in the top bar once the invitation is read', async () => {
    render(<SetupFlow step="welcome" invite={INVITE} />);
    await screen.findByRole('heading', { level: 1 });
    expect(within(screen.getByRole('banner')).getByText('UCR West')).toBeInTheDocument();
    expect(within(screen.getByRole('banner')).getByText('Overwatch')).toBeInTheDocument();
  });

  it('shows the invitation as a shimmer with a spoken label while it is read', () => {
    render(<SetupFlow step="welcome" invite={INVITE} />);
    const status = screen.getByRole('status');
    expect(status).toHaveTextContent('Opening set-up');
    expect(status).toHaveAttribute('aria-busy', 'true');
  });

  it('lists the five steps as numbered cards, each with the time it takes (R2, Set-up welcome)', async () => {
    render(<SetupFlow step="welcome" invite={INVITE} />);
    const list = await screen.findByRole('list', { name: 'Set-up steps' });
    const items = within(list).getAllByRole('listitem');
    expect(items.map((item) => item.textContent?.replace(/^\d/, ''))).toEqual([
      'Check your number30 sec',
      'Choose how we contact you1 min',
      'Add to home screenApp only',
      'Allow notificationsApp only',
      'Create a PIN30 sec',
    ]);
  });

  it('draws no progress on the welcome page and "Step 1 of 5" on the number and code pages, "Step 2 of 5" on the channel page', async () => {
    const { unmount } = render(<SetupFlow step="welcome" invite={INVITE} />);
    await screen.findByRole('heading', { level: 1 });
    expect(screen.queryByLabelText(/^Step \d of 5$/)).toBeNull();
    unmount();
    const number = render(<SetupFlow step="number" invite={INVITE} />);
    await screen.findByRole('heading', { level: 1 });
    expect(screen.getByLabelText('Step 1 of 5')).toBeInTheDocument();
    number.unmount();
    const code = render(<SetupFlow step="code" invite={INVITE} />);
    await screen.findByRole('heading', { level: 1 });
    expect(screen.getByLabelText('Step 1 of 5')).toBeInTheDocument();
    code.unmount();
    render(<SetupFlow step="channel" invite={INVITE} />);
    await screen.findByRole('heading', { level: 1 });
    expect(screen.getByLabelText('Step 2 of 5')).toBeInTheDocument();
  });

  it('moves focus to the page heading on each step', async () => {
    render(<SetupFlow step="channel" invite={INVITE} />);
    const heading = await screen.findByRole('heading', { level: 1, name: 'How should we contact you?' });
    await waitFor(() => expect(heading).toHaveFocus());
  });

  it('asks for the code under the heading Enter your code, folds the number into a summary row and says which number it went to (R3)', async () => {
    render(<SetupFlow step="code" invite={INVITE} />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Enter your code' })).toBeInTheDocument();
    expect(screen.getByText('We sent a 6-digit code to 07xxx xxx456.')).toBeInTheDocument();
    expect(screen.getByText('Code sent just now')).toBeInTheDocument();
    expect(screen.getByText('Step 1 of 5 · Check your number')).toBeInTheDocument();
    expect(
      screen.getByText(/The code works for 10 minutes\. After 5 wrong tries, ask for a new one\./),
    ).toBeInTheDocument();
  });

  it('draws the code as one input, wakes Check code only when all six digits are in, and says so', async () => {
    const { container } = render(<SetupFlow step="code" invite={INVITE} />);
    const field = await screen.findByRole('textbox', { name: '6-digit code' });
    expect(container.querySelectorAll('input')).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Check code' })).toBeDisabled();
    expect(screen.getByText('The button wakes up when all 6 digits are in.')).toBeInTheDocument();
    await userEvent.type(field, '48291');
    expect(screen.getByRole('button', { name: 'Check code' })).toBeDisabled();
    await userEvent.type(field, '3');
    expect(screen.getByRole('button', { name: 'Check code' })).toBeEnabled();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('offers "This is not my number" as a closed disclosure that says what to do', async () => {
    render(<SetupFlow step="code" invite={INVITE} />);
    const summary = await screen.findByText('This is not my number');
    const details = summary.closest('details');
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute('open');
    await userEvent.click(summary);
    expect(screen.getByText('Ask the shift lead to send a new invitation to the right number. Do not carry on.')).toBeVisible();
  });

  it('says a 6-digit code goes to the masked number, shown on its own (R3, Check your number)', async () => {
    render(<SetupFlow step="number" invite={INVITE} />);
    expect(await screen.findByText('We will send a 6-digit code to this number.')).toBeInTheDocument();
    expect(screen.getByText('07xxx xxx456')).toHaveAttribute('data-el', 'ONB-MASKED-NUMBER');
    expect(screen.getByText('Step 1 of 5 · Check your number')).toBeInTheDocument();
  });

  it('shows the masked number and never the full number', async () => {
    const { container } = render(<SetupFlow step="number" invite={INVITE} />);
    expect(await screen.findByText('07xxx xxx456')).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/07\d{9}/);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows the resend button only after 60 seconds', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<SetupFlow step="code" invite={INVITE} />);
    expect(await screen.findByText(/Send a new code in 0:/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send a new code' })).toBeNull();
    // A second at a time, so each tick is one render (the countdown is one interval).
    for (let second = 0; second < 55; second += 1) {
      await act(async () => {
        vi.advanceTimersByTime(1000);
      });
    }
    expect(screen.queryByRole('button', { name: 'Send a new code' })).toBeNull();
    for (let second = 0; second < 10; second += 1) {
      await act(async () => {
        vi.advanceTimersByTime(1000);
      });
    }
    expect(await screen.findByRole('button', { name: 'Send a new code' })).toBeInTheDocument();
  });

  it('says how many tries are left after a wrong code', async () => {
    render(<SetupFlow step="code" invite={INVITE} />);
    await userEvent.click(await screen.findByRole('textbox', { name: '6-digit code' }));
    await userEvent.paste('000001');
    await userEvent.click(screen.getByRole('button', { name: 'Check code' }));
    expect(await screen.findByText('That code is not right. You have 4 tries left.')).toBeInTheDocument();
  });

  it('says to send a new code and disables Check code when no tries are left', async () => {
    server.use(http.post('/api/bff/identity/invitation-code/verify', () => HttpResponse.json({ ok: false, triesLeft: 0 })));
    render(<SetupFlow step="code" invite={INVITE} />);
    await userEvent.click(await screen.findByRole('textbox', { name: '6-digit code' }));
    await userEvent.paste('000002');
    await userEvent.click(screen.getByRole('button', { name: 'Check code' }));
    expect(await screen.findByText('Too many tries. Send a new code.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Check code' })).toBeDisabled();
  });

  it('offers the channel as three radio cards in a radio group, with App notification recommended and chosen (R4)', async () => {
    const { container } = render(<SetupFlow step="channel" invite={INVITE} />);
    const group = await screen.findByRole('radiogroup', { name: 'How we contact you' });
    const radios = within(group).getAllByRole('radio');
    expect(radios.map((radio) => (radio as HTMLInputElement).value)).toEqual(['app', 'text', 'email']);
    expect(within(group).getByRole('radio', { name: /App notification/ })).toBeChecked();
    expect(within(group).getByText('Recommended')).toBeInTheDocument();
    expect(within(group).getByText('A notification opens the app. Needs adding to your home screen.')).toBeInTheDocument();
    expect(within(group).getByText('A text with a link. Works on any phone.')).toBeInTheDocument();
    expect(within(group).getByText('An email with a link.')).toBeInTheDocument();
    expect(screen.getByText('Step 2 of 5')).toBeInTheDocument();
    expect(screen.getByText('You can change this later in Settings.')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('moves the choice between the radio cards with the arrow keys', async () => {
    render(<SetupFlow step="channel" invite={INVITE} />);
    const app = await screen.findByRole('radio', { name: /App notification/ });
    app.focus();
    await userEvent.keyboard('{ArrowDown}');
    expect(screen.getByRole('radio', { name: /Text message/ })).toBeChecked();
  });

  it('posts Text as the channel and goes to the done page', async () => {
    render(<SetupFlow step="channel" invite={INVITE} />);
    await userEvent.click(await screen.findByRole('radio', { name: /Text message/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/setup/done?channel=text'));
    // Before sign-in the channel is recorded for the phone's device (W8E): the session-bound route is not used.
    expect(seenBffRequests.find((r) => r.path === '/api/bff/identity/channel')?.body).toEqual({ channel: 'text' });
    expect(seenBffRequests.some((r) => r.path === '/api/bff/reporter/channel')).toBe(false);
  });

  it('asks for the invitation’s code with the link’s token only, and checks it with the token and the code only', async () => {
    render(<SetupFlow step="number" invite={INVITE} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Send code' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith(`/setup?step=code&invite=${INVITE}`));
    expect(seenBffRequests.find((r) => r.path === '/api/bff/identity/invitation-code')?.body).toEqual({ invite: INVITE });
    const { unmount } = render(<SetupFlow step="code" invite={INVITE} />);
    await userEvent.click(await screen.findByRole('textbox', { name: '6-digit code' }));
    await userEvent.paste('482913');
    await userEvent.click(screen.getByRole('button', { name: 'Check code' }));
    await waitFor(() => expect(seenBffRequests.some((r) => r.path === '/api/bff/identity/invitation-code/verify')).toBe(true));
    expect(seenBffRequests.find((r) => r.path === '/api/bff/identity/invitation-code/verify')?.body).toEqual({ invite: INVITE, code: '482913' });
    unmount();
  });

  it('says the code could not be sent when the back end says no, and does not move on', async () => {
    server.use(http.post('/api/bff/identity/invitation-code', () => HttpResponse.json({ code: 'unavailable' }, { status: 503 })));
    render(<SetupFlow step="number" invite={INVITE} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Send code' }));
    expect(await screen.findByText('We could not send a code. Try again shortly.')).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it('says to check the number again when the phone’s code has timed out (the channel answers needs-code)', async () => {
    server.use(http.post('/api/bff/identity/channel', () => HttpResponse.json({ code: 'needs-code' }, { status: 403 })));
    render(<SetupFlow step="channel" invite={INVITE} />);
    await userEvent.click(await screen.findByRole('radio', { name: /Text message/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect(await screen.findByText('That took too long. Check your number again to carry on.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Check my number again' }));
    expect(push).toHaveBeenCalledWith(`/setup?step=number&invite=${INVITE}`);
  });

  it('shows the Expired state for an invitation the back end will not use (410), and “could not check” for a failure', async () => {
    server.use(http.get('/api/bff/invitations/:token', () => HttpResponse.json({ state: 'expired' }, { status: 410 })));
    const { unmount } = render(<SetupFlow step="welcome" invite={INVITE} />);
    expect(await screen.findByRole('heading', { level: 1, name: 'This invitation has expired' })).toBeInTheDocument();
    expect(screen.getByText(EXPIRED_TEXT)).toBeInTheDocument();
    unmount();
    server.use(http.get('/api/bff/invitations/:token', () => HttpResponse.json({ code: 'unavailable' }, { status: 503 })));
    render(<SetupFlow step="welcome" invite={INVITE} />);
    expect(await screen.findByText('We could not check this invitation. Try again shortly.')).toBeInTheDocument();
    expect(screen.queryByText(/has expired/)).toBeNull();
  });

  it('shows the Expired state with no request made when there is no usable token', () => {
    render(<SetupFlow step="welcome" invite="" />);
    expect(screen.getByRole('heading', { level: 1, name: 'This invitation has expired' })).toBeInTheDocument();
    expect(screen.getByText(EXPIRED_TEXT)).toBeInTheDocument();
    expect(seenBffRequests).toHaveLength(0);
  });

  it('sends App to the home-screen guide', async () => {
    render(<SetupFlow step="channel" invite={INVITE} />);
    await userEvent.click(await screen.findByRole('radio', { name: /App notification/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/setup/home-screen'));
  });

  it('skips the channel step for an exec invitation', async () => {
    server.use(
      http.get('/api/bff/invitations/:token', () =>
        HttpResponse.json({ service: 'ICB board', role: 'exec', maskedPhone: '07xxx xxx456', expiresAt: '2026-11-01T10:00:00Z', state: 'valid' }),
      ),
    );
    render(<SetupFlow step="code" invite={INVITE} />);
    await userEvent.click(await screen.findByRole('textbox', { name: '6-digit code' }));
    await userEvent.paste('482913');
    await userEvent.click(screen.getByRole('button', { name: 'Check code' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/setup/home-screen'));
    expect(push).not.toHaveBeenCalledWith(expect.stringContaining('step=channel'));
  });
});
