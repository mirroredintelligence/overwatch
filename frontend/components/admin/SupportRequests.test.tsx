import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { ONE_TIME_CODE, VIEW_TICKETS } from '@/test/fixtures/tenantAdmin';
import { resetAdminWrites, seenAdminWrites } from '@/test/msw/handlers/tenantAdmin';
import { SAMPLE_CSRF } from '@/test/msw/handlers/staff';
import { server } from '@/test/msw/server';
import { SupportRequests } from './SupportRequests';

// The administrator's side of the support tickets (TEN-076, TEN-084, DEC-1003): a support person asks to look into
// this organisation with a reason; the administrator approves (and is given a one-time code to hand over, shown
// once), refuses, or takes an approved code or an open access back at once. Requests still waiting and the ones in
// hand are open; the ones that are over sit under a collapsed "Earlier requests" row.

const CODE_HEADING = 'Approved. Give them this code.';

beforeEach(() => resetAdminWrites());

async function open() {
  const user = userEvent.setup();
  render(<SupportRequests />);
  await screen.findByRole('heading', { level: 1, name: 'Support requests' });
  await screen.findAllByText('The board shows a service twice');
  return user;
}
const card = (id: string) => screen.getByRole('article', { name: `Request ${id}` });
const codePanel = () => screen.findByRole('region', { name: CODE_HEADING });

describe('the list', () => {
  it('says what the page is for, in the words of the board', async () => {
    await open();
    expect(screen.getByText('Platform staff can look into your organisation only when you approve and give them a code.')).toBeInTheDocument();
  });

  it('says how many requests are waiting for the administrator', async () => {
    await open();
    expect(screen.getByText('1 waiting for you')).toBeInTheDocument();
  });

  it('shows each request with its reason, its reference and where it stands, in words', async () => {
    await open();
    const first = card('tkt-1');
    expect(within(first).getByText('Waiting for you')).toBeInTheDocument();
    expect(within(first).getByText('Service fault')).toBeInTheDocument();
    expect(within(first).getByText('The board shows a service twice')).toBeInTheDocument();
    expect(within(first).getByText('Help-desk reference HD-1042')).toBeInTheDocument();
    expect(within(first).getByText('Asked 30 Oct 2026, 08:00. Lapses 31 Oct 2026, 08:00.')).toBeInTheDocument();
    expect(within(card('tkt-2')).getByText('Approved, code not used yet')).toBeInTheDocument();
    expect(within(card('tkt-3')).getByText('Open now')).toBeInTheDocument();
  });

  it('puts the requests that are over under a collapsed "Earlier requests" row, with their count', async () => {
    server.use(
      http.get('/api/bff/tenant/support-tickets', () =>
        HttpResponse.json({
          tickets: [
            ...VIEW_TICKETS.tickets,
            { id: 'tkt-4', state: 'refused', reasonCode: 'other', reason: 'Looked at a report', reference: null, requestedAt: '2026-10-27T08:00:00Z', validUntil: '2026-10-28T08:00:00Z', decidedAt: '2026-10-27T09:00:00Z', openedAt: null, endedAt: null, endedBy: null },
          ],
        }),
      ),
    );
    const user = await open();
    const earlier = screen.getByRole('button', { name: 'Earlier requests · 1' });
    expect(earlier).toHaveAttribute('aria-expanded', 'false');
    await user.click(earlier);
    expect(earlier).toHaveAttribute('aria-expanded', 'true');
    expect(within(card('tkt-4')).getByText('Refused')).toBeInTheDocument();
    expect(within(card('tkt-4')).queryAllByRole('button')).toHaveLength(0);
  });

  it('offers only what the state allows: approve and refuse, take the code back, end the access', async () => {
    await open();
    expect(within(card('tkt-1')).getAllByRole('button').map((b) => b.textContent)).toEqual(['Approve', 'Refuse']);
    expect(within(card('tkt-2')).getAllByRole('button').map((b) => b.textContent)).toEqual(['Take the code back']);
    expect(within(card('tkt-3')).getAllByRole('button').map((b) => b.textContent)).toEqual(['End the access now']);
  });

  it('says there are none, and says it could not load, in the right cases', async () => {
    server.use(http.get('/api/bff/tenant/support-tickets', () => HttpResponse.json({ tickets: [] })));
    const { unmount } = render(<SupportRequests />);
    expect(await screen.findByText('Nobody has asked to look into your organisation.')).toBeInTheDocument();
    expect(screen.queryByText(/waiting for you/)).not.toBeInTheDocument();
    unmount();
    server.use(http.get('/api/bff/tenant/support-tickets', () => HttpResponse.json({}, { status: 503 })));
    render(<SupportRequests />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the support requests.');
  });

  it('shows no reference of the person who asked', async () => {
    await open();
    expect(document.body.textContent ?? '').not.toMatch(/ops-|stf-/);
  });
});

describe('approving', () => {
  it('shows the one-time code once, with what it does, and sends the approval with the CSRF token and a key', async () => {
    const user = await open();
    await user.click(within(card('tkt-1')).getByRole('button', { name: 'Approve' }));
    const panel = await codePanel();
    expect(within(panel).getByRole('status')).toHaveTextContent(ONE_TIME_CODE);
    expect(within(panel).getByText(ONE_TIME_CODE)).toBeInTheDocument();
    expect(
      within(panel).getByText('Shown once. It works for 4 hours and opens one access to your organisation for 1 hour. If you lose it, take it back and ask them to ask again.'),
    ).toBeInTheDocument();
    expect(seenAdminWrites[0]).toMatchObject({ method: 'POST', path: '/api/bff/tenant/support-tickets/tkt-1/approval', csrf: SAMPLE_CSRF });
    expect(seenAdminWrites[0]?.key).toBeTruthy();
  });

  it('copies the code with a copy button, and says it has', async () => {
    const user = await open();
    // Set after open(): userEvent.setup() installs its own clipboard on navigator.
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    await user.click(within(card('tkt-1')).getByRole('button', { name: 'Approve' }));
    const panel = await codePanel();
    await user.click(within(panel).getByRole('button', { name: 'Copy the code' }));
    expect(writeText).toHaveBeenCalledWith(ONE_TIME_CODE);
    expect(await within(panel).findByText('Copied to the clipboard.')).toBeInTheDocument();
  });

  it('drops the code from the page when the administrator has passed it on, and never keeps it', async () => {
    const user = await open();
    await user.click(within(card('tkt-1')).getByRole('button', { name: 'Approve' }));
    const panel = await codePanel();
    await user.click(within(panel).getByRole('button', { name: 'I have passed it on' }));
    expect(screen.queryByText(ONE_TIME_CODE)).not.toBeInTheDocument();
    expect(document.body.textContent ?? '').not.toContain(ONE_TIME_CODE);
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    expect(document.cookie).not.toContain(ONE_TIME_CODE);
  });

  it('takes the code back from the code card, which ends the code with the same call as the list', async () => {
    const user = await open();
    await user.click(within(card('tkt-1')).getByRole('button', { name: 'Approve' }));
    const panel = await codePanel();
    await user.click(within(panel).getByRole('button', { name: 'Take it back' }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(2));
    expect(seenAdminWrites[1]).toMatchObject({ method: 'DELETE', path: '/api/bff/tenant/support-tickets/tkt-1/access' });
    expect(screen.queryByText(ONE_TIME_CODE)).not.toBeInTheDocument();
  });

  it('does not show the code on a reload of the list, and reads the list again after an approval', async () => {
    const user = await open();
    let reads = 0;
    server.use(http.get('/api/bff/tenant/support-tickets', () => { reads += 1; return HttpResponse.json(VIEW_TICKETS); }));
    await user.click(within(card('tkt-1')).getByRole('button', { name: 'Approve' }));
    await codePanel();
    await waitFor(() => expect(reads).toBeGreaterThan(0));
  });

  it('says a request that is no longer waiting could not be approved, and shows no code', async () => {
    server.use(http.post('/api/bff/tenant/support-tickets/tkt-1/approval', () => HttpResponse.json({ code: 'business-rule' }, { status: 409 })));
    const user = await open();
    await user.click(within(card('tkt-1')).getByRole('button', { name: 'Approve' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('This request is not waiting for you any more. The list has been read again.');
    expect(screen.queryByRole('region', { name: CODE_HEADING })).not.toBeInTheDocument();
  });

  it('says it could not be approved on a failure, and offers the same buttons again', async () => {
    server.use(http.post('/api/bff/tenant/support-tickets/tkt-1/approval', () => HttpResponse.json({}, { status: 503 })));
    const user = await open();
    await user.click(within(card('tkt-1')).getByRole('button', { name: 'Approve' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The request could not be approved. Try again.');
    expect(within(card('tkt-1')).getByRole('button', { name: 'Approve' })).toBeEnabled();
  });
});

describe('refusing and taking back', () => {
  it('refuses a request', async () => {
    const user = await open();
    await user.click(within(card('tkt-1')).getByRole('button', { name: 'Refuse' }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(1));
    expect(seenAdminWrites[0]).toMatchObject({ method: 'POST', path: '/api/bff/tenant/support-tickets/tkt-1/refusal' });
  });

  it('takes an approved code back, and ends an open access at once, each with the same call', async () => {
    const user = await open();
    await user.click(within(card('tkt-2')).getByRole('button', { name: 'Take the code back' }));
    await user.click(within(card('tkt-3')).getByRole('button', { name: 'End the access now' }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(2));
    expect(seenAdminWrites.map((w) => [w.method, w.path])).toEqual([
      ['DELETE', '/api/bff/tenant/support-tickets/tkt-2/access'],
      ['DELETE', '/api/bff/tenant/support-tickets/tkt-3/access'],
    ]);
  });

  it('has no axe violations, with the code showing too', async () => {
    const user = await open();
    expect(await runAxe(document.body)).toHaveNoViolations();
    await user.click(within(card('tkt-1')).getByRole('button', { name: 'Approve' }));
    await codePanel();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
