import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { VIEW_SUPPORT_TICKETS, VIEW_TENANTS_SUPPORT, rawTicket, viewTicket } from '@/test/fixtures/operator';
import { OPERATOR_SAMPLE_CSRF, resetOperatorWrites, seenOperatorWrites } from '@/test/msw/handlers/operator';
import { server } from '@/test/msw/server';
import { SupportTicketDetail } from './SupportTicketDetail';

// One request of a support person (TEN-083, DEC-1003): where it stands, the cancellation while it waits, the
// opening with the one-time code the administrator gave (one tenant, one hour, once) and ending the access.
// The code is typed here and sent in one call: it is never kept, shown again or put in an address.

beforeEach(() => {
  resetOperatorWrites();
  server.use(http.get('/api/bff/platform/tenants', () => HttpResponse.json(VIEW_TENANTS_SUPPORT)));
});

function serve(over: Record<string, unknown>) {
  server.use(http.get('/api/bff/platform/support-tickets/:id', () => HttpResponse.json(viewTicket(rawTicket(over)))));
}
async function open(over: Record<string, unknown> = {}) {
  serve(over);
  const user = userEvent.setup();
  render(<SupportTicketDetail id="tkt-1" />);
  await screen.findByRole('heading', { level: 1, name: 'Request tkt-1' });
  return user;
}

describe('a request that is waiting', () => {
  it('shows the tenant by name, where it stands, the reason, the reference and the times', async () => {
    await open();
    expect(screen.getByText('Sample Area A')).toBeInTheDocument();
    expect(screen.getByText('Waiting for the tenant’s administrator')).toBeInTheDocument();
    expect(screen.getByText('The board shows a service twice')).toBeInTheDocument();
    expect(screen.getByText('Help-desk reference HD-1042')).toBeInTheDocument();
    expect(screen.getByText('Asked 30 Oct 2026, 08:00. Lapses 31 Oct 2026, 08:00.')).toBeInTheDocument();
  });

  it('can be taken back, with the console’s CSRF token and a key', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Cancel the request' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(seenOperatorWrites[0]).toMatchObject({ method: 'POST', path: '/api/bff/platform/support-tickets/tkt-1/cancellation', csrf: OPERATOR_SAMPLE_CSRF });
    expect(seenOperatorWrites[0]?.key).toBeTruthy();
    expect(await screen.findByRole('status')).toHaveTextContent('The request is cancelled.');
  });

  it('offers no code to type yet', async () => {
    await open();
    expect(screen.queryByLabelText('Code from the administrator')).not.toBeInTheDocument();
  });
});

describe('an approved request', () => {
  it('asks for the code, and opens the access with it, once, then forgets it', async () => {
    const user = await open({ state: 'approved', decidedAt: '2026-10-30T08:30:00Z' });
    expect(screen.getByText('Approved. Ask the administrator for the code.')).toBeInTheDocument();
    await user.type(screen.getByLabelText('Code from the administrator'), 'k7r4-92qx');
    await user.click(screen.getByRole('button', { name: 'Open access' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(seenOperatorWrites[0]).toMatchObject({ method: 'POST', path: '/api/bff/platform/support-tickets/tkt-1/access', body: { code: 'K7R4-92QX' } });
    expect(await screen.findByRole('status')).toHaveTextContent('Access is open until 30 Oct 2026, 10:00. It is for this tenant only.');
    expect(document.body.textContent ?? '').not.toContain('K7R4-92QX');
    expect(screen.queryByLabelText('Code from the administrator')).not.toBeInTheDocument();
  });

  it('refuses a code that is not the shape of one before any call', async () => {
    const user = await open({ state: 'approved' });
    await user.type(screen.getByLabelText('Code from the administrator'), 'abc');
    await user.click(screen.getByRole('button', { name: 'Open access' }));
    expect(await screen.findByText('Enter the code as it was given, for example K7R4-92QX.', { selector: 'p' })).toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
  });

  it('says the one thing for every refusal, and clears the code field', async () => {
    server.use(http.post('/api/bff/platform/support-tickets/:id/access', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    const user = await open({ state: 'approved' });
    await user.type(screen.getByLabelText('Code from the administrator'), 'K7R4-92QX');
    await user.click(screen.getByRole('button', { name: 'Open access' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('That code did not work. Check it with the administrator, or ask them to take it back and approve again.');
    expect(screen.getByLabelText('Code from the administrator')).toHaveValue('');
  });
});

describe('an open access', () => {
  it('says when it was opened and what this console does and does not do, and ends it at once on request', async () => {
    const user = await open({ state: 'opened', openedAt: '2026-10-30T09:00:00Z' });
    expect(screen.getByText('Open now')).toBeInTheDocument();
    expect(screen.getByText('Opened 30 Oct 2026, 09:00. It lasts one hour.')).toBeInTheDocument();
    expect(screen.getByText('This console opens and ends the access. It does not read the tenant’s data yet.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'End the access now' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(seenOperatorWrites[0]).toMatchObject({ method: 'DELETE', path: '/api/bff/platform/support-tickets/tkt-1/access' });
    expect(await screen.findByRole('status')).toHaveTextContent('The access has ended.');
  });
});

describe('a request that is finished', () => {
  it.each([
    ['refused', 'Refused'],
    ['cancelled', 'Cancelled'],
    ['ended', 'Ended'],
    ['revoked', 'Taken back by the administrator'],
    ['expired', 'Lapsed'],
  ])('shows %s and offers nothing to do', async (state, word) => {
    await open({ state });
    expect(screen.getByText(word)).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});

describe('failures', () => {
  it('says it could not find the request on a 404 and could not load it otherwise', async () => {
    server.use(http.get('/api/bff/platform/support-tickets/:id', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    const { unmount } = render(<SupportTicketDetail id="nope" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not find that request.');
    unmount();
    server.use(http.get('/api/bff/platform/support-tickets/:id', () => HttpResponse.json({}, { status: 503 })));
    render(<SupportTicketDetail id="tkt-1" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the request.');
  });

  it('says the request could not be taken back, on a failure', async () => {
    server.use(http.post('/api/bff/platform/support-tickets/:id/cancellation', () => HttpResponse.json({}, { status: 409 })));
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Cancel the request' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The request could not be taken back. It may have been decided. The page has been read again.');
  });

  it('has no axe violations', async () => {
    await open({ state: 'approved' });
    expect(await runAxe(document.body)).toHaveNoViolations();
    expect(VIEW_SUPPORT_TICKETS.tickets).toHaveLength(3);
  });
});
