import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { SupportCode } from './SupportCode';

const sent: { method: string; path: string; csrf: string | null; body?: unknown }[] = [];
const CODE = 'K7R4-92QX';

function bffHandlers(accesses: unknown[] = [{ openedAt: '2026-10-23T13:02:00Z', role: 'support' }]) {
  return [
    http.post('/api/bff/support/code', async ({ request }) => {
      sent.push({ method: 'POST', path: '/api/bff/support/code', csrf: request.headers.get('X-CSRF-Token'), body: await request.json() });
      return HttpResponse.json({ code: CODE, expiresAt: '2026-10-23T17:02:00Z' }, { status: 201 });
    }),
    http.get('/api/bff/support/accesses', () => HttpResponse.json(accesses)),
    http.delete('/api/bff/support/code', ({ request }) => {
      sent.push({ method: 'DELETE', path: '/api/bff/support/code', csrf: request.headers.get('X-CSRF-Token') });
      return new HttpResponse(null, { status: 204 });
    }),
  ];
}

beforeEach(() => {
  sent.length = 0;
  localStorage.clear();
  server.use(...bffHandlers());
});

describe('SupportCode', () => {
  it('shows the code from the BFF in large type, and when it is valid until', async () => {
    render(<SupportCode />);
    expect(await screen.findByText(CODE)).toBeInTheDocument();
    expect(screen.getByText('Valid until 18:02')).toBeInTheDocument();
    expect(screen.getByText('Support can see the pages you used, the buttons you pressed and any errors. They cannot see what you typed or any patient information.')).toBeInTheDocument();
  });

  it('lists who has opened the session, or says nobody has', async () => {
    render(<SupportCode />);
    expect(await screen.findByText('14:02 by Support')).toBeInTheDocument();
    server.use(...bffHandlers([]));
    render(<SupportCode />);
    expect(await screen.findByText('Nobody has opened it yet.')).toBeInTheDocument();
  });

  it('copies the code to the clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(<SupportCode />);
    await screen.findByText(CODE);
    await userEvent.click(screen.getByRole('button', { name: 'Copy code' }));
    expect(writeText).toHaveBeenCalledWith(CODE);
  });

  it('says how to copy by hand when the clipboard refuses', async () => {
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) }, configurable: true });
    render(<SupportCode />);
    await screen.findByText(CODE);
    await userEvent.click(screen.getByRole('button', { name: 'Copy code' }));
    expect(await screen.findByText('Press Ctrl+C to copy')).toBeInTheDocument();
  });

  it('asks before it stops sharing, and sends the delete with the CSRF header only when confirmed', async () => {
    document.cookie = 'diucs_csrf=csrf-test-token';
    render(<SupportCode />);
    await screen.findByText(CODE);
    await userEvent.click(screen.getByRole('button', { name: 'Stop sharing now' }));
    expect(screen.getByText('Stop sharing? Support will lose access at once.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(sent.filter((s) => s.method === 'DELETE')).toHaveLength(0);
    await userEvent.click(screen.getByRole('button', { name: 'Stop sharing now' }));
    await userEvent.click(within(screen.getByRole('group', { name: 'Stop sharing?' })).getByRole('button', { name: 'Stop sharing' }));
    expect(await screen.findByText('Sharing stopped.')).toBeInTheDocument();
    expect(sent.find((s) => s.method === 'DELETE')?.csrf).toBe('csrf-test-token');
    document.cookie = 'diucs_csrf=; max-age=0';
  });

  it('keeps the code out of local storage', async () => {
    render(<SupportCode />);
    await screen.findByText(CODE);
    expect(localStorage.length).toBe(0);
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<SupportCode />);
    await screen.findByText(CODE);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

