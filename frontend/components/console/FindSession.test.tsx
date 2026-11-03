import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { FindSession } from './FindSession';

const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

const RESULT = {
  sessionId: 's-7f3a9c2e1b',
  role: 'advisor',
  device: 'desktop',
  release: '1.4.2',
  started: '2026-10-30T13:50:00Z',
  eventCount: 42,
  frictionCount: 3,
  errorCount: 0,
};

describe('FindSession: open with a support code', () => {
  it('shows the fixed refusal for a wrong or expired code', async () => {
    server.use(
      http.post('/api/bff/console/sessions/open', () => HttpResponse.json({ code: 'forbidden' }, { status: 403 })),
    );
    render(<FindSession />);

    await userEvent.type(screen.getByLabelText('Support code'), 'ABC123');
    await userEvent.click(screen.getByRole('button', { name: 'Open session' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('That code is not valid or has expired.');
    expect(push).not.toHaveBeenCalled();
  });

  it('opens the session it was given', async () => {
    server.use(
      http.post('/api/bff/console/sessions/open', () =>
        HttpResponse.json({ sessionId: 's-7f3a9c2e1b', expiresAt: '2026-10-30T14:30:00Z' }),
      ),
    );
    render(<FindSession />);

    await userEvent.type(screen.getByLabelText('Support code'), 'ABC123');
    await userEvent.click(screen.getByRole('button', { name: 'Open session' }));

    await waitFor(() => expect(push).toHaveBeenCalledWith('/console/session/s-7f3a9c2e1b'));
  });

  it('puts the support code card first, with the one primary action', () => {
    render(<FindSession />);

    const open = screen.getByRole('heading', { name: 'Open one session' });
    const search = screen.getByRole('heading', { name: 'Or search' });
    expect(open.compareDocumentPosition(search) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Open session' })).toHaveAttribute('data-variant', 'primary');
    expect(screen.getByRole('button', { name: 'Search' })).toHaveAttribute('data-variant', 'secondary');
  });

  it('shows the support code field at 56px, from the module stylesheet', () => {
    const css = readFileSync(resolve(__dirname, 'FindSession.module.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(css).toMatch(/var\(--c-/);
    expect(css).toMatch(/\.code\s*\{[^}]*min-height:\s*56px/);
  });
});

describe('FindSession: search', () => {
  it('shows the results with an Open control for each session', async () => {
    server.use(http.get('/api/bff/console/sessions', () => HttpResponse.json({ items: [RESULT] })));
    render(<FindSession />);

    await userEvent.click(screen.getByRole('button', { name: 'Search' }));

    const row = await screen.findByRole('row', { name: /s-7f3a9c2e1b/ });
    expect(row).toHaveTextContent('advisor');
    expect(row).toHaveTextContent('1.4.2');
    expect(screen.getByRole('button', { name: /open s-7f3a9c2e1b/i })).toBeInTheDocument();
  });

  it('shows the results as a labelled region, and right-aligns the counts', async () => {
    server.use(http.get('/api/bff/console/sessions', () => HttpResponse.json({ items: [RESULT] })));
    render(<FindSession />);

    await userEvent.click(screen.getByRole('button', { name: 'Search' }));

    const region = await screen.findByRole('region', { name: 'Search results' });
    expect(within(region).getByRole('cell', { name: '42' })).toHaveAttribute('data-align', 'end');
    expect(within(region).getByRole('cell', { name: '3' })).toHaveAttribute('data-align', 'end');
  });

  it('keeps the session id, trace id, reference and release behind More filters', async () => {
    render(<FindSession />);

    const toggle = screen.getByRole('button', { name: 'More filters' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByLabelText('Trace id')).not.toBeInTheDocument();

    await userEvent.click(toggle);

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByLabelText('Session id')).toBeInTheDocument();
    expect(screen.getByLabelText('Trace id')).toBeInTheDocument();
    expect(screen.getByLabelText('Booking or case reference')).toBeInTheDocument();
    expect(screen.getByLabelText('Release')).toBeInTheDocument();
  });

  it('keeps the role chips in view without opening More filters', () => {
    render(<FindSession />);

    const roles = screen.getByRole('group', { name: 'Role' });
    for (const name of ['Advisor', 'Lead', 'Clinical', 'Reporter']) {
      expect(within(roles).getByRole('button', { name })).toHaveAttribute('aria-pressed', 'false');
    }
  });

  it('says the person has no access when the back end refuses the search', async () => {
    server.use(http.get('/api/bff/console/sessions', () => HttpResponse.json({ code: 'forbidden' }, { status: 403 })));
    render(<FindSession />);

    await userEvent.click(screen.getByRole('button', { name: 'Search' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have access to the console.');
  });

  it('says that a search by trace id or reference is not available when the back end refuses it as not supported', async () => {
    server.use(http.get('/api/bff/console/sessions', () => HttpResponse.json({ code: 'not-supported' }, { status: 400 })));
    render(<FindSession />);

    await userEvent.click(screen.getByRole('button', { name: 'More filters' }));
    await userEvent.type(screen.getByLabelText('Trace id'), 'a'.repeat(32));
    await userEvent.click(screen.getByRole('button', { name: 'Search' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Search by trace id or reference is not available yet. Search by session id, role or release.');
  });

  it('says a search found no session when the back end answers an empty list', async () => {
    server.use(http.get('/api/bff/console/sessions', () => HttpResponse.json({ items: [] })));
    render(<FindSession />);

    await userEvent.click(screen.getByRole('button', { name: 'Search' }));

    expect(await screen.findByText('No sessions found.')).toBeInTheDocument();
  });

  it('carries the footnote that search shows aggregates and ids, and that opening a timeline is refused without a way in', () => {
    render(<FindSession />);

    expect(
      screen.getByText(
        'Search shows aggregates and session ids only. Opening a timeline asks for a support code or a ticket approval, and that is refused with a way back to this page.',
      ),
    ).toBeInTheDocument();
  });

  it('passes vitest-axe', async () => {
    const { container } = render(<FindSession />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
