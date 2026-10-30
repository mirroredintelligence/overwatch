import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { SignInForm } from './SignInForm';

// The applicant's sign-in (W23, DEC-900 to DEC-902). The invitation says whose number the code goes to,
// so the page never asks for a number: it reads the link, shows the last three digits, sends the code
// and checks it. The number never reaches the browser; the page holds only its last three digits.

const push = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const INVITE = 'InviteTokenSampleValue1';
const OPEN = { state: 'open', serviceName: 'Community nursing', numberEnding: '456', expiresAt: '2026-11-01T18:00:00Z' };

type Call = { path: string; body: unknown; csrf: string | null };
const calls: Call[] = [];

/** Answers the BFF's registration routes for one test. Each answer is set by the test. */
const answers: {
  invitation: { status: number; body: unknown };
  code: { status: number; body: unknown; headers?: Record<string, string> };
  verify: { status: number; body: unknown };
} = {
  invitation: { status: 200, body: OPEN },
  code: { status: 202, body: { accepted: true, resendAfterSeconds: 60 } },
  verify: { status: 200, body: { registrationId: 'REG-SAMPLE-1' } },
};

function route(path: string, pick: () => { status: number; body: unknown; headers?: Record<string, string> }) {
  return http.post(path, (async ({ request }) => {
    calls.push({ path, body: await request.json().catch(() => null), csrf: request.headers.get('x-csrf-token') });
    const { status, body, headers } = pick();
    return HttpResponse.json(body as Record<string, unknown>, { status, headers: { 'Cache-Control': 'no-store', ...headers } });
  }) as HttpResponseResolver);
}

beforeEach(() => {
  push.mockClear();
  calls.length = 0;
  answers.invitation = { status: 200, body: OPEN };
  answers.code = { status: 202, body: { accepted: true, resendAfterSeconds: 60 } };
  answers.verify = { status: 200, body: { registrationId: 'REG-SAMPLE-1' } };
  server.use(
    route('/api/bff/identity/invitation', () => answers.invitation),
    route('/api/bff/identity/code', () => answers.code),
    route('/api/bff/identity/code/verify', () => answers.verify),
  );
});

async function sendCode() {
  await userEvent.click(await screen.findByRole('button', { name: 'Send code' }));
}

async function checkCode(code = '123456') {
  await userEvent.type(screen.getByLabelText('6-digit code'), code);
  await userEvent.click(screen.getByRole('button', { name: 'Check code' }));
}

describe('SignInForm: reading the invitation', () => {
  it('reads the link on the page’s own invitation and says whose number the code goes to, by its last three digits', async () => {
    render(<SignInForm inviteToken={INVITE} />);
    expect(await screen.findByText('We will text a code to the number your invitation was sent to: 07xxx xxx456.')).toBeInTheDocument();
    expect(calls).toEqual([{ path: '/api/bff/identity/invitation', body: { inviteToken: INVITE }, csrf: null }]);
  });

  it('asks for no number: there is no mobile field to fill in', async () => {
    render(<SignInForm inviteToken={INVITE} />);
    await screen.findByRole('button', { name: 'Send code' });
    expect(screen.queryByLabelText('Mobile number')).toBeNull();
  });

  it('shows the invitation’s expired and used words, with no send button', async () => {
    answers.invitation = { status: 200, body: { state: 'expired' } };
    const { unmount } = render(<SignInForm inviteToken={INVITE} />);
    expect(await screen.findByText('This invitation has expired. Ask the shift lead for a new one.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send code' })).toBeNull();
    unmount();

    answers.invitation = { status: 200, body: { state: 'used' } };
    render(<SignInForm inviteToken={INVITE} />);
    expect(await screen.findByText('This invitation has already been used. Ask the shift lead for a new one.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send code' })).toBeNull();
  });

  it('says the link cannot be found when the back end does not know it, and offers no code', async () => {
    answers.invitation = { status: 404, body: { code: 'not-found' } };
    render(<SignInForm inviteToken={INVITE} />);
    expect(await screen.findByText('We could not find an invitation for this link. Ask the shift lead to check your invitation.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send code' })).toBeNull();
  });

  it('says sign-in is not available when the back end cannot answer, and offers no code', async () => {
    answers.invitation = { status: 503, body: { code: 'unavailable' } };
    render(<SignInForm inviteToken={INVITE} />);
    expect(await screen.findByText('Sign-in is not available right now. Try again shortly.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send code' })).toBeNull();
  });
});

describe('SignInForm: sending and checking the code', () => {
  it('sends the code request with the invitation and nothing else, and moves to the code entry', async () => {
    render(<SignInForm inviteToken={INVITE} />);
    await sendCode();
    await screen.findByRole('heading', { name: 'Enter your code' });
    expect(calls.map((c) => [c.path, c.body])).toEqual([
      ['/api/bff/identity/invitation', { inviteToken: INVITE }],
      ['/api/bff/identity/code', { purpose: 'registration', inviteToken: INVITE }],
    ]);
    expect(screen.getByText('We sent a code to 07xxx xxx456.')).toBeInTheDocument();
  });

  it('signs in and goes to the start of the registration the back end names', async () => {
    render(<SignInForm inviteToken={INVITE} />);
    await sendCode();
    await checkCode();
    await waitFor(() => expect(push).toHaveBeenCalledWith('/register/REG-SAMPLE-1/start'));
    expect(calls.at(-1)).toMatchObject({ path: '/api/bff/identity/code/verify', body: { code: '123456' } });
  });

  it('sends the typed code only, with no number, invitation or tenant in the check', async () => {
    render(<SignInForm inviteToken={INVITE} />);
    await sendCode();
    await checkCode();
    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(calls.at(-1)?.body).toEqual({ code: '123456' });
  });

  it('shows a wrong code as not right, with no count of tries it does not have, and signs nobody in', async () => {
    render(<SignInForm inviteToken={INVITE} />);
    await sendCode();
    answers.verify = { status: 400, body: { code: 'wrong-code', message: 'That code is not right. Check it and try again.' } };
    await checkCode();
    expect(await screen.findByText('That code is not right. Check it and try again.')).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it('shows the expired words for 410, the throttle for 429, the no-invitation words for 403 and the device words for 409', async () => {
    render(<SignInForm inviteToken={INVITE} />);
    await sendCode();
    const cases: [number, string][] = [
      [410, 'That code has expired. Ask for a new code.'],
      [429, 'Too many attempts. Try again later.'],
      [403, 'We could not find an invitation for this number. Ask the shift lead to check it.'],
      [409, 'This phone cannot be set up with this code. Start again on this phone.'],
    ];
    for (const [status, text] of cases) {
      answers.verify = { status, body: { code: 'x' } };
      await checkCode();
      expect(await screen.findByText(text)).toBeInTheDocument();
    }
    expect(push).not.toHaveBeenCalled();
  });

  it('treats a sign-in answer with no registration as a check that failed, and does not navigate', async () => {
    render(<SignInForm inviteToken={INVITE} />);
    await sendCode();
    answers.verify = { status: 200, body: {} };
    await checkCode();
    expect(await screen.findByText('We could not check the code. Try again.')).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it('never shows a whole mobile number on the page at any point', async () => {
    const { container } = render(<SignInForm inviteToken={INVITE} />);
    await sendCode();
    await screen.findByRole('heading', { name: 'Enter your code' });
    expect(container.textContent ?? '').not.toMatch(/07\d{9}/);
  });
});

describe('SignInForm: accessibility', () => {
  it('has no axe violations on the invitation step and on the code step with an error', async () => {
    const { container, unmount } = render(<SignInForm inviteToken={INVITE} />);
    await screen.findByRole('button', { name: 'Send code' });
    expect(await runAxe(container)).toHaveNoViolations();
    unmount();

    const again = render(<SignInForm inviteToken={INVITE} />);
    await sendCode();
    answers.verify = { status: 400, body: { code: 'wrong-code', message: 'That code is not right. Check it and try again.' } };
    await checkCode();
    await screen.findByText('That code is not right. Check it and try again.');
    expect(await runAxe(again.container)).toHaveNoViolations();
  });
});
