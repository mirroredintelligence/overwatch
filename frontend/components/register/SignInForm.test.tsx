import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { bffRegistration, seenBffRegistration } from '@/test/msw/handlers/registration';
import { server } from '@/test/msw/server';
import { SignInForm } from './SignInForm';

const push = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const INVITE = 'InviteTokenSampleValue1';

function respondWith(path: string, status: number, body: unknown) {
  server.use(
    http.post(path, (() =>
      HttpResponse.json(body as Record<string, unknown>, { status, headers: { 'Cache-Control': 'no-store' } })) as HttpResponseResolver),
  );
}

async function sendCode(number = '07700 900456') {
  await userEvent.type(screen.getByLabelText('Mobile number'), number);
  await userEvent.click(screen.getByRole('button', { name: 'Send code' }));
}

async function checkCode(code = '123456') {
  await userEvent.type(screen.getByLabelText('6-digit code'), code);
  await userEvent.click(screen.getByRole('button', { name: 'Check code' }));
}

beforeEach(() => {
  push.mockClear();
  bffRegistration.codeSend = { status: 202, body: { accepted: true, resendAfterSeconds: 60 } };
  bffRegistration.verify = { status: 200, body: { registrationId: 'REG-SAMPLE-1' } };
});

describe('SignInForm: asking for the code', () => {
  it('shows the sign-in wording, the mobile field with its hint, and the notes', () => {
    render(<SignInForm inviteToken={INVITE} />);
    expect(screen.getByText('Enter your mobile number. We text you a code to check it is you.')).toBeInTheDocument();
    const field = screen.getByLabelText('Mobile number');
    expect(field).toHaveAccessibleDescription('Use the number your invitation was sent to');
    expect(screen.getByRole('button', { name: 'Send code' })).toBeInTheDocument();
    expect(screen.getByText('You need an invitation from the SPOA shift lead to register. Check your texts or email for the link.')).toBeInTheDocument();
    expect(screen.getByText('Having trouble? Ask the SPOA shift lead to check your invitation.')).toBeInTheDocument();
  });

  it('sends the number as digits, the purpose and the invitation, and nothing else', async () => {
    render(<SignInForm inviteToken={INVITE} />);
    await sendCode('07700 900456');
    await waitFor(() => expect(seenBffRegistration).toHaveLength(1));
    expect(seenBffRegistration[0]).toMatchObject({
      path: '/api/bff/identity/code',
      body: { phone: '07700900456', purpose: 'registration', inviteToken: INVITE },
    });
  });

  it('moves to the code entry and does not keep the full number on the page once it is sent', async () => {
    const { container } = render(<SignInForm inviteToken={INVITE} />);
    await sendCode('07700 900456');
    expect(await screen.findByRole('heading', { level: 2, name: 'Enter your code' })).toBeInTheDocument();
    expect(screen.getByText('We sent a code to 07xxx xxx456.')).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/07700\s?900456/);
    expect(screen.queryByDisplayValue(/07700/)).not.toBeInTheDocument();
  });

  it('shows the inline error for an empty number and posts nothing', async () => {
    render(<SignInForm inviteToken={INVITE} />);
    await userEvent.click(screen.getByRole('button', { name: 'Send code' }));
    const field = screen.getByLabelText('Mobile number');
    expect(field).toHaveAttribute('aria-invalid', 'true');
    expect(field).toHaveAccessibleDescription(/Enter your mobile number/);
    expect(seenBffRegistration).toHaveLength(0);
  });

  it('shows the not-UK message for a number that is not a UK mobile and posts nothing', async () => {
    render(<SignInForm inviteToken={INVITE} />);
    await sendCode('01305 123456');
    expect(screen.getByLabelText('Mobile number')).toHaveAccessibleDescription(
      /Enter a UK mobile number, like 07700 900456/,
    );
    expect(seenBffRegistration).toHaveLength(0);
  });
});

describe('SignInForm: checking the code', () => {
  it('signs in and goes to the start of the registration the back end names', async () => {
    render(<SignInForm inviteToken={INVITE} />);
    await sendCode();
    await checkCode('123456');
    await waitFor(() => expect(push).toHaveBeenCalledWith('/register/REG-SAMPLE-1/start'));
    const verify = seenBffRegistration.find((r) => r.path === '/api/bff/identity/code/verify');
    expect(verify?.body).toEqual({ phone: '07700900456', code: '123456' });
  });

  it('shows the tries message for a wrong code, with the tries left', async () => {
    respondWith('/api/bff/identity/code/verify', 400, { code: 'wrong-code', triesLeft: 3 });
    render(<SignInForm inviteToken={INVITE} />);
    await sendCode();
    await checkCode();
    expect(await screen.findByText('That code is not right. You have 3 tries left.')).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it('shows the expired message for 410 and the locked message for 429', async () => {
    respondWith('/api/bff/identity/code/verify', 410, { code: 'expired' });
    const { unmount } = render(<SignInForm inviteToken={INVITE} />);
    await sendCode();
    await checkCode();
    expect(await screen.findByText('That code has expired. Ask for a new code.')).toBeInTheDocument();
    unmount();

    respondWith('/api/bff/identity/code/verify', 429, { code: 'locked' });
    render(<SignInForm inviteToken={INVITE} />);
    await sendCode();
    await checkCode();
    expect(await screen.findByText('Too many wrong tries. Ask for a new code.')).toBeInTheDocument();
  });

  it('shows the no-invitation message for 403 and does not sign in', async () => {
    respondWith('/api/bff/identity/code/verify', 403, { code: 'forbidden' });
    render(<SignInForm inviteToken={INVITE} />);
    await sendCode();
    await checkCode();
    expect(
      await screen.findByText('We could not find an invitation for this number. Ask the SPOA shift lead to check it.'),
    ).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it('has no axe violations on the sign-in step and on the code step with an error', async () => {
    const first = render(<SignInForm inviteToken={INVITE} />);
    expect((await runAxe(first.container)).violations).toEqual([]);
    first.unmount();

    respondWith('/api/bff/identity/code/verify', 400, { code: 'wrong-code', triesLeft: 3 });
    const { container } = render(<SignInForm inviteToken={INVITE} />);
    await sendCode();
    await checkCode();
    await screen.findByText('That code is not right. You have 3 tries left.');
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
