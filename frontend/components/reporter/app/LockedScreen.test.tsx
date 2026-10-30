import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetReporterRequests } from '@/test/msw/handlers/reporter';
import { LockedScreen } from './LockedScreen';

// Full-suite runs share the machine: a PIN or form test clicks many keys, so it gets more time.
vi.setConfig({ testTimeout: 20_000 });

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
  resetReporterRequests();
});

async function typeDigits(digits: string) {
  for (const digit of digits) await userEvent.click(screen.getByRole('button', { name: digit }));
}

describe('LockedScreen', () => {
  it('takes a text code, then a new PIN entered twice, and lands on the app', async () => {
    const { container } = render(<LockedScreen reason={null} />);
    expect(screen.getByRole('heading', { name: 'Your PIN is locked' })).toBeInTheDocument();
    expect(screen.getByText('Nothing was sent or changed.')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
    await userEvent.click(screen.getByRole('button', { name: 'Text me a code' }));
    const boxes = await screen.findAllByRole('textbox');
    await userEvent.click(boxes[0]);
    await userEvent.paste('482913');
    await userEvent.click(screen.getByRole('button', { name: 'Check code' }));
    expect(await screen.findByRole('heading', { name: 'Create a 6-digit PIN' })).toBeInTheDocument();
    await typeDigits('246810');
    await typeDigits('246810');
    await waitFor(() => expect(push).toHaveBeenCalledWith('/app'));
  });

  it('says Forgot your PIN? and leaves out the five-tries line when reached from the link', () => {
    render(<LockedScreen reason="forgot" />);
    expect(screen.getByRole('heading', { name: 'Forgot your PIN?' })).toBeInTheDocument();
    expect(screen.queryByText(/That was 5 wrong tries/)).toBeNull();
  });

  it('asks for a PIN-reset code for the phone’s device, and checks it for that purpose, with no number', async () => {
    const { seenBffRequests } = await import('@/test/msw/handlers/reporter');
    render(<LockedScreen reason={null} />);
    await userEvent.click(screen.getByRole('button', { name: 'Text me a code' }));
    const boxes = await screen.findAllByRole('textbox');
    await userEvent.click(boxes[0]);
    await userEvent.paste('482913');
    await userEvent.click(screen.getByRole('button', { name: 'Check code' }));
    await screen.findByRole('heading', { name: 'Create a 6-digit PIN' });
    expect(seenBffRequests.find((r) => r.path === '/api/bff/identity/device-code')?.body).toEqual({ purpose: 'pin-reset' });
    expect(seenBffRequests.find((r) => r.path === '/api/bff/identity/device-code/verify')?.body).toEqual({ purpose: 'pin-reset', code: '482913' });
  });

  it('records text for the phone’s device before sign-in on “Use text or email instead”', async () => {
    const { seenBffRequests } = await import('@/test/msw/handlers/reporter');
    render(<LockedScreen reason={null} />);
    await userEvent.click(screen.getByRole('button', { name: 'Use text or email instead' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/app/settings'));
    expect(seenBffRequests.find((r) => r.path === '/api/bff/identity/channel')?.body).toEqual({ channel: 'text' });
    expect(seenBffRequests.some((r) => r.path === '/api/bff/reporter/channel')).toBe(false);
  });

  it('says to get a code first when the phone’s code has timed out', async () => {
    const { http, HttpResponse } = await import('msw');
    const { server } = await import('@/test/msw/server');
    server.use(http.post('/api/bff/identity/channel', () => HttpResponse.json({ code: 'needs-code' }, { status: 403 })));
    render(<LockedScreen reason={null} />);
    await userEvent.click(screen.getByRole('button', { name: 'Use text or email instead' }));
    expect(await screen.findByText('Get a code by text first, then choose text or email.')).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });
});
