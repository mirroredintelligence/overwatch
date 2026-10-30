import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { SupportCode } from './SupportCode';

const sent: { method: string; path: string; csrf: string | null; body?: unknown }[] = [];
const CODE = 'K7R4-92QX';
let state: { active: boolean; expiresAt?: string } = { active: false };

function bffHandlers(accesses: unknown[] = [{ openedAt: '2026-10-23T13:02:00Z', role: 'support' }]) {
  return [
    http.get('/api/bff/support/code', () => HttpResponse.json(state)),
    http.post('/api/bff/support/code', async ({ request }) => {
      sent.push({ method: 'POST', path: '/api/bff/support/code', csrf: request.headers.get('X-CSRF-Token'), body: await request.json() });
      state = { active: true, expiresAt: '2026-10-23T17:02:00Z' };
      return HttpResponse.json({ code: CODE, expiresAt: '2026-10-23T17:02:00Z' }, { status: 201 });
    }),
    http.get('/api/bff/support/accesses', () => HttpResponse.json(accesses)),
    http.delete('/api/bff/support/code', ({ request }) => {
      sent.push({ method: 'DELETE', path: '/api/bff/support/code', csrf: request.headers.get('X-CSRF-Token') });
      state = { active: false };
      return new HttpResponse(null, { status: 204 });
    }),
  ];
}

beforeEach(() => {
  sent.length = 0;
  state = { active: false };
  localStorage.clear();
  server.use(...bffHandlers());
});

async function makeCode() {
  await userEvent.click(await screen.findByRole('button', { name: 'Make a support code' }));
  return screen.findByText(CODE);
}

describe('SupportCode before a code is made', () => {
  it('reads whether sharing is on when the page opens, makes no code by itself, and offers to make one', async () => {
    render(<SupportCode />);
    expect(await screen.findByRole('button', { name: 'Make a support code' })).toBeInTheDocument();
    expect(screen.getByText('Support cannot see your session.')).toBeInTheDocument();
    expect(sent.filter((s) => s.method === 'POST')).toHaveLength(0);
  });

  it('makes the code on request for this session, and shows it in large type with when it is valid until', async () => {
    render(<SupportCode />);
    expect(await makeCode()).toBeInTheDocument();
    expect(screen.getByText('Valid until 18:02')).toBeInTheDocument();
    expect(screen.getByText('Support can see the pages you used, the buttons you pressed and any errors. They cannot see what you typed or any patient information.')).toBeInTheDocument();
    const body = sent.find((s) => s.method === 'POST')?.body as { sessionId: string; deviceType: string; appMode: string; release: string };
    expect(body.sessionId).toMatch(/^[a-f0-9]{16,32}$/);
    expect(Object.keys(body).sort()).toEqual(['appMode', 'deviceType', 'release', 'sessionId']);
  });

  it('says so, and reads the state again, when the back end refuses a second code', async () => {
    server.use(http.post('/api/bff/support/code', () => {
      state = { active: true, expiresAt: '2026-10-23T17:02:00Z' };
      return HttpResponse.json({ code: 'conflict' }, { status: 409 });
    }));
    render(<SupportCode />);
    await userEvent.click(await screen.findByRole('button', { name: 'Make a support code' }));
    expect(await screen.findByText('A code is live until 18:02.')).toBeInTheDocument();
  });

  it('says it could not make a code when the back end fails', async () => {
    server.use(http.post('/api/bff/support/code', () => HttpResponse.json({ code: 'exception' }, { status: 503 })));
    render(<SupportCode />);
    await userEvent.click(await screen.findByRole('button', { name: 'Make a support code' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not make a code. Try again.');
  });
});

describe('SupportCode when a code is already live (a reload, or another tab)', () => {
  beforeEach(() => {
    state = { active: true, expiresAt: '2026-10-23T17:02:00Z' };
  });

  it('says a code is live until when, and does not show a code it does not have', async () => {
    render(<SupportCode />);
    expect(await screen.findByText('A code is live until 18:02.')).toBeInTheDocument();
    expect(screen.getByText('The code is shown only once, when it is made. If you no longer have it, stop sharing and make a new one.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Copy code' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Make a support code' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Stop sharing now' })).toBeInTheDocument();
    expect(screen.queryByText(CODE)).not.toBeInTheDocument();
  });

  it('says it could not tell whether a code is live, and offers nothing that would guess, when the read fails', async () => {
    server.use(http.get('/api/bff/support/code', () => HttpResponse.json({ code: 'exception' }, { status: 503 })));
    render(<SupportCode />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not tell whether a code is live. Try again.');
    expect(screen.queryByRole('button', { name: 'Make a support code' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Check again' })).toBeInTheDocument();
  });
});

describe('SupportCode with a code made in this visit', () => {
  it('lists who has opened the session, or says nobody has', async () => {
    const first = render(<SupportCode />);
    await makeCode();
    expect(await screen.findByText('14:02 by Support')).toBeInTheDocument();
    first.unmount();
    state = { active: true, expiresAt: '2026-10-23T17:02:00Z' };
    server.use(...bffHandlers([]));
    render(<SupportCode />);
    expect(await screen.findByText('Nobody has opened it yet.')).toBeInTheDocument();
  });

  it('copies the code to the clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(<SupportCode />);
    await makeCode();
    await userEvent.click(screen.getByRole('button', { name: 'Copy code' }));
    expect(writeText).toHaveBeenCalledWith(CODE);
  });

  it('says how to copy by hand when the clipboard refuses', async () => {
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) }, configurable: true });
    render(<SupportCode />);
    await makeCode();
    await userEvent.click(screen.getByRole('button', { name: 'Copy code' }));
    expect(await screen.findByText('Press Ctrl+C to copy')).toBeInTheDocument();
  });

  it('asks before it stops sharing, sends the delete with the CSRF header only when confirmed, and then offers a new code', async () => {
    document.cookie = 'diucs_csrf=csrf-test-token';
    render(<SupportCode />);
    await makeCode();
    await userEvent.click(screen.getByRole('button', { name: 'Stop sharing now' }));
    expect(screen.getByText('Stop sharing? Support will lose access at once.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(sent.filter((s) => s.method === 'DELETE')).toHaveLength(0);
    await userEvent.click(screen.getByRole('button', { name: 'Stop sharing now' }));
    await userEvent.click(within(screen.getByRole('group', { name: 'Stop sharing?' })).getByRole('button', { name: 'Stop sharing' }));
    expect(await screen.findByText('Sharing stopped.')).toBeInTheDocument();
    expect(sent.find((s) => s.method === 'DELETE')?.csrf).toBe('csrf-test-token');
    expect(screen.queryByText(CODE)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Make a support code' })).toBeInTheDocument();
    document.cookie = 'diucs_csrf=; max-age=0';
  });

  it('keeps the code out of local storage and session storage', async () => {
    render(<SupportCode />);
    await makeCode();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<SupportCode />);
    await makeCode();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
