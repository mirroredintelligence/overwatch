import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { ONE_TIME_CODE, VIEW_TICKETS } from '@/test/fixtures/tenantAdmin';
import { resetAdminWrites, seenAdminWrites } from '@/test/msw/handlers/tenantAdmin';
import { SAMPLE_CSRF } from '@/test/msw/handlers/staff';
import { server } from '@/test/msw/server';
import { SupportRequests } from './SupportRequests';

// The administrator's side of the support tickets (TEN-076, TEN-084): a support person asks to look into
// this organisation with a reason; the administrator approves (and is given a one-time code to hand over,
// shown once), refuses, or takes an approved code or an open access back at once.

beforeEach(() => resetAdminWrites());

async function open() {
  const user = userEvent.setup();
  render(<SupportRequests />);
  await screen.findByRole('heading', { level: 1, name: 'Support requests' });
  await screen.findAllByText('The board shows a service twice');
  return user;
}
const card = (id: string) => screen.getByRole('article', { name: `Request ${id}` });

describe('the list', () => {
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
    const panel = await screen.findByRole('region', { name: 'Give this code to the support person' });
    expect(within(panel).getByText(ONE_TIME_CODE)).toBeInTheDocument();
    expect(within(panel).getByText('It is not shown again. It works for four hours and opens one access to your organisation for one hour.')).toBeInTheDocument();
    expect(within(panel).getByText('If you lose it, take the code back and ask the support person to ask again.')).toBeInTheDocument();
    expect(seenAdminWrites[0]).toMatchObject({ method: 'POST', path: '/api/bff/tenant/support-tickets/tkt-1/approval', csrf: SAMPLE_CSRF });
    expect(seenAdminWrites[0]?.key).toBeTruthy();
  });

  it('drops the code from the page when the administrator has passed it on, and never keeps it', async () => {
    const user = await open();
    await user.click(within(card('tkt-1')).getByRole('button', { name: 'Approve' }));
    const panel = await screen.findByRole('region', { name: 'Give this code to the support person' });
    await user.click(within(panel).getByRole('button', { name: 'I have given the code' }));
    expect(screen.queryByText(ONE_TIME_CODE)).not.toBeInTheDocument();
    expect(document.body.textContent ?? '').not.toContain(ONE_TIME_CODE);
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    expect(document.cookie).not.toContain(ONE_TIME_CODE);
  });

  it('does not show the code on a reload of the list, and reads the list again after an approval', async () => {
    const user = await open();
    let reads = 0;
    server.use(http.get('/api/bff/tenant/support-tickets', () => { reads += 1; return HttpResponse.json(VIEW_TICKETS); }));
    await user.click(within(card('tkt-1')).getByRole('button', { name: 'Approve' }));
    await screen.findByRole('region', { name: 'Give this code to the support person' });
    await waitFor(() => expect(reads).toBeGreaterThan(0));
  });

  it('says a request that is no longer waiting could not be approved, and shows no code', async () => {
    server.use(http.post('/api/bff/tenant/support-tickets/tkt-1/approval', () => HttpResponse.json({ code: 'business-rule' }, { status: 409 })));
    const user = await open();
    await user.click(within(card('tkt-1')).getByRole('button', { name: 'Approve' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('This request is not waiting for you any more. The list has been read again.');
    expect(screen.queryByRole('region', { name: 'Give this code to the support person' })).not.toBeInTheDocument();
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
    await screen.findByRole('region', { name: 'Give this code to the support person' });
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
