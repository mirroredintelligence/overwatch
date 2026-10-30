import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetReporterRequests, seenBffRequests } from '@/test/msw/handlers/reporter';
import { server } from '@/test/msw/server';
import { VerifyScreen } from './VerifyScreen';

vi.setConfig({ testTimeout: 20_000 });

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

// The 30-day check (W37, W8E): a text code to the number the back end holds for this phone's device. The
// phone has no number to send, and no session is needed (the PIN screen sent the reporter here because a
// code is due).

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
  resetReporterRequests();
});

describe('VerifyScreen', () => {
  it('asks for a reverify code with no number, reads nothing behind a session (there is none yet), and passes axe', async () => {
    const { container } = render(<VerifyScreen />);
    expect(screen.getByText('It has been 30 days. We will text a code to the number we have for you.')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
    expect(seenBffRequests.some((r) => r.path === '/api/bff/reporter/settings')).toBe(false);
    await userEvent.click(screen.getByRole('button', { name: 'Send code' }));
    expect(await screen.findAllByRole('textbox')).not.toHaveLength(0);
    expect(seenBffRequests.find((r) => r.path === '/api/bff/identity/device-code')?.body).toEqual({ purpose: 'reverify' });
  });

  it('checks the code for the reverify purpose and goes back to the app', async () => {
    render(<VerifyScreen />);
    await userEvent.click(screen.getByRole('button', { name: 'Send code' }));
    const boxes = await screen.findAllByRole('textbox');
    await userEvent.click(boxes[0]);
    await userEvent.paste('482913');
    await userEvent.click(screen.getByRole('button', { name: 'Check code' }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/app'));
    expect(seenBffRequests.find((r) => r.path === '/api/bff/identity/device-code/verify')?.body).toEqual({ purpose: 'reverify', code: '482913' });
  });

  it('says how many tries are left after a wrong code, and does not go on', async () => {
    render(<VerifyScreen />);
    await userEvent.click(screen.getByRole('button', { name: 'Send code' }));
    const boxes = await screen.findAllByRole('textbox');
    await userEvent.click(boxes[0]);
    await userEvent.paste('000001');
    await userEvent.click(screen.getByRole('button', { name: 'Check code' }));
    expect(await screen.findByText('That code is not right. You have 4 tries left.')).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it('does not show the code entry when the code could not be sent', async () => {
    server.use(http.post('/api/bff/identity/device-code', () => HttpResponse.json({ code: 'unavailable' }, { status: 503 })));
    render(<VerifyScreen />);
    await userEvent.click(screen.getByRole('button', { name: 'Send code' }));
    expect(await screen.findByText('We could not send a code. Try again shortly.')).toBeInTheDocument();
    expect(screen.queryAllByRole('textbox')).toHaveLength(0);
  });
});
