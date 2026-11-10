import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { FailedReplies } from './FailedReplies';

// Replies we could not take in (DEC-1359): each waiting reply with what they wrote, who sent it when known, what
// went wrong in words, "Process it now" and "Mark as handled" (which asks first). Nothing here is a phone number.

const ITEMS = [
  { sid: 'SM1', receivedAt: new Date(Date.now() - 90 * 60_000).toISOString(), text: 'Y', senderName: 'Dee Manager', problem: 'We could not queue it.' },
  { sid: 'SM2', receivedAt: new Date(Date.now() - 10 * 60_000).toISOString(), text: '3', senderName: null, problem: 'We could not look up the sender.' },
];

type Seen = { path: string; body: unknown; key: string | null; csrf: string | null };
let seen: Seen[] = [];

function serve(items = ITEMS) {
  server.use(
    http.get('/api/bff/lead/replies', () => HttpResponse.json({ items }, { headers: { 'Cache-Control': 'no-store' } })),
    http.post('/api/bff/lead/replies/:sid', async ({ request, params }) => {
      seen.push({ path: `/api/bff/lead/replies/${String(params.sid)}`, body: await request.json(), key: request.headers.get('idempotency-key'), csrf: request.headers.get('x-csrf-token') });
      return HttpResponse.json({ sid: params.sid, action: 'process' });
    }),
  );
}

beforeEach(() => {
  seen = [];
  document.cookie = 'overwatch_csrf=test-csrf-token';
});

describe('FailedReplies', () => {
  it('lists each reply with who sent it, what they wrote and what went wrong, in words', async () => {
    serve();
    render(<FailedReplies />);
    const list = await screen.findByRole('list', { name: 'Replies waiting' });
    const rows = within(list).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByText('Dee Manager')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('We could not queue it.')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('Y')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('1 hr 30 min ago')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('Someone we could not identify')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('We could not look up the sender.')).toBeInTheDocument();
    expect(document.body.textContent ?? '').not.toMatch(/enqueue|find-sender|replay-marker/);
  });

  it('says so when nothing is waiting', async () => {
    serve([]);
    render(<FailedReplies />);
    expect(await screen.findByText('No replies are waiting.')).toBeInTheDocument();
  });

  it('processes a reply now, sending the action with the CSRF token and one key, and takes it off the list', async () => {
    serve();
    const user = userEvent.setup();
    render(<FailedReplies />);
    const row = (await screen.findAllByRole('listitem'))[0]!;
    await user.click(within(row).getByRole('button', { name: /Process it now/ }));
    await waitFor(() => expect(seen).toHaveLength(1));
    expect(seen[0]).toMatchObject({ path: '/api/bff/lead/replies/SM1', body: { action: 'process' }, csrf: 'test-csrf-token' });
    expect(seen[0]?.key).toBeTruthy();
    expect(await screen.findByText(/Processed\./)).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
  });

  it('asks before it marks a reply handled, and Keep leaves it on the list without a call', async () => {
    serve();
    const user = userEvent.setup();
    render(<FailedReplies />);
    const row = (await screen.findAllByRole('listitem'))[0]!;
    await user.click(within(row).getByRole('button', { name: /Mark as handled/ }));
    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByText(/It comes off this list and is not sent through/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Keep it on the list' }));
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(seen).toEqual([]);
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
  });

  it('marks a reply handled after the confirmation and takes it off the list', async () => {
    serve();
    const user = userEvent.setup();
    render(<FailedReplies />);
    const row = (await screen.findAllByRole('listitem'))[1]!;
    await user.click(within(row).getByRole('button', { name: /Mark as handled/ }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Mark as handled' }));
    await waitFor(() => expect(seen).toHaveLength(1));
    expect(seen[0]).toMatchObject({ path: '/api/bff/lead/replies/SM2', body: { action: 'handled' } });
    expect(await screen.findByText('Marked as handled.')).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
  });

  it('keeps the reply on the list and says so when it could not be processed', async () => {
    serve();
    server.use(http.post('/api/bff/lead/replies/:sid', () => HttpResponse.json({ code: 'transient' }, { status: 503 })));
    const user = userEvent.setup();
    render(<FailedReplies />);
    const row = (await screen.findAllByRole('listitem'))[0]!;
    await user.click(within(row).getByRole('button', { name: /Process it now/ }));
    expect(await screen.findByText(/We could not process it now/)).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
  });

  it('says it could not load, with a way to try again, and never an empty list', async () => {
    server.use(http.get('/api/bff/lead/replies', () => HttpResponse.json({ code: 'transient' }, { status: 503 })));
    render(<FailedReplies />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load these replies. Try again shortly.');
    expect(screen.queryByText('No replies are waiting.')).not.toBeInTheDocument();
    serve();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('list', { name: 'Replies waiting' })).toBeInTheDocument();
  });

  it('has no inline styles in its markup (the content security policy refuses them)', async () => {
    serve();
    const { container } = render(<FailedReplies />);
    await screen.findByRole('list', { name: 'Replies waiting' });
    expect(container.querySelectorAll('[style]')).toHaveLength(0);
  });

  it('has no axe violations', async () => {
    serve();
    const { container } = render(<FailedReplies />);
    await screen.findByRole('list', { name: 'Replies waiting' });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
