import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetReporterRequests, seenBffRequests } from '@/test/msw/handlers/reporter';
import { server } from '@/test/msw/server';
import { LostPhone } from './LostPhone';

vi.setConfig({ testTimeout: 20_000 });

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
  resetReporterRequests();
});

describe('LostPhone', () => {
  it('refuses a number that is not a UK mobile and posts nothing', async () => {
    const { container } = render(<LostPhone />);
    await userEvent.type(screen.getByLabelText('Mobile number'), '0123');
    await userEvent.click(screen.getByRole('button', { name: 'Send code' }));
    expect(await screen.findByText('Enter a UK mobile number, like 07700 900123')).toBeInTheDocument();
    expect(seenBffRequests.some((r) => r.path === '/api/bff/identity/new-phone')).toBe(false);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('posts a valid number, then shows the code entry; a verified code shows the call-back wait', async () => {
    render(<LostPhone />);
    await userEvent.type(screen.getByLabelText('Mobile number'), '07700 900123');
    await userEvent.click(screen.getByRole('button', { name: 'Send code' }));
    const boxes = await screen.findAllByRole('textbox');
    expect(seenBffRequests.find((r) => r.path === '/api/bff/identity/new-phone')?.body).toEqual({ phone: '07700 900123' });
    await userEvent.click(boxes[0]);
    await userEvent.paste('482913');
    await userEvent.click(screen.getByRole('button', { name: 'Check code' }));
    expect(await screen.findByRole('heading', { name: 'Waiting for a call-back' })).toBeInTheDocument();
    expect(screen.getByText('The shift lead will phone your service on the number on the register. Until then, prompts go to your cover number or the coordination team.')).toBeInTheDocument();
  });

  it('says what went wrong for a wrong code, an expired code and too many tries', async () => {
    const cases: [number, Record<string, string>, string][] = [
      [400, { code: 'wrong' }, 'That code is not right.'],
      [410, { code: 'expired' }, 'That code has expired. Ask for a new code.'],
      [429, { code: 'throttled' }, 'Too many wrong tries. Ask for a new code.'],
    ];
    for (const [status, body, text] of cases) {
      server.use(http.post('/api/bff/identity/new-phone/verify', () => HttpResponse.json(body, { status })));
      const { unmount } = render(<LostPhone />);
      await userEvent.type(screen.getByLabelText('Mobile number'), '07700 900123');
      await userEvent.click(screen.getByRole('button', { name: 'Send code' }));
      const boxes = await screen.findAllByRole('textbox');
      await userEvent.click(boxes[0]);
      await userEvent.paste('000000');
      await userEvent.click(screen.getByRole('button', { name: 'Check code' }));
      expect(await screen.findByText(text)).toBeInTheDocument();
      unmount();
    }
  });
});

describe('SignOutAll', () => {
  it('names the other phones, cancels with nothing sent, and signs out of all phones on Confirm', async () => {
    const { SignOutAll } = await import('./SignOutAll');
    render(<SignOutAll />);
    expect(await screen.findByText('This phone and 1 other will be signed out.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(push).toHaveBeenCalledWith('/app/settings');
    expect(seenBffRequests.some((r) => r.path === '/api/bff/identity/sign-out-everywhere')).toBe(false);
    push.mockClear();
    render(<SignOutAll />);
    await userEvent.click((await screen.findAllByRole('button', { name: 'Sign out of all phones' }))[0]);
    await waitFor(() => expect(push).toHaveBeenCalledWith('/app/pin'));
    expect(seenBffRequests.some((r) => r.path === '/api/bff/identity/sign-out-everywhere')).toBe(true);
  });
});
