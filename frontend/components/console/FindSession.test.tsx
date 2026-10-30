import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { FindSession } from './FindSession';

const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

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
});

describe('FindSession: search', () => {
  it('shows the results with an Open control for each session', async () => {
    server.use(
      http.get('/api/bff/console/sessions', () =>
        HttpResponse.json({
          items: [
            {
              sessionId: 's-7f3a9c2e1b',
              role: 'advisor',
              device: 'desktop',
              release: '1.4.2',
              started: '2026-10-30T13:50:00Z',
              eventCount: 42,
              frictionCount: 3,
              errorCount: 0,
            },
          ],
        }),
      ),
    );
    render(<FindSession />);

    await userEvent.click(screen.getByRole('button', { name: 'Search' }));

    const row = await screen.findByRole('row', { name: /s-7f3a9c2e1b/ });
    expect(row).toHaveTextContent('advisor');
    expect(row).toHaveTextContent('1.4.2');
    expect(screen.getByRole('button', { name: /open s-7f3a9c2e1b/i })).toBeInTheDocument();
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

  it('passes vitest-axe', async () => {
    const { container } = render(<FindSession />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
