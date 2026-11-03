import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { VIEW_LISTINGS } from '@/test/fixtures/networkAdmin';
import { resetNetworkAdminReads, resetNetworkAdminWrites, seenNetworkAdminWrites } from '@/test/msw/handlers/networkAdmin';
import { SAMPLE_CSRF } from '@/test/msw/handlers/staff';
import { server } from '@/test/msw/server';
import { NetworkListings } from './NetworkListings';

// The listings of the network (TEN-080, board NListings). The owner admits a member's service to the network,
// declines it, pauses it and reinstates it. Filter by status; a decline or a pause asks for a reason in place,
// from the fixed codes, never free text.

beforeEach(() => {
  resetNetworkAdminWrites();
  resetNetworkAdminReads();
});

async function open() {
  const user = userEvent.setup();
  render(<NetworkListings />);
  await screen.findByRole('table', { name: 'Listings' }, { timeout: 5000 });
  return user;
}
const rowOf = (id: string) => {
  const found = document.querySelector<HTMLElement>(`[data-row-ref="${id}"]`);
  if (found === null) throw new Error(`no row ${id}`);
  return found;
};
const rowIfShown = (id: string) => document.querySelector<HTMLElement>(`[data-row-ref="${id}"]`);

describe('the filter', () => {
  it('has one chip per status, with its count, and Waiting chosen first', async () => {
    await open();
    const chips = screen.getByRole('group', { name: 'Filter by status' });
    expect(within(chips).getAllByRole('button').map((b) => b.textContent)).toEqual(['Waiting 1', 'Admitted 1', 'Paused 1', 'Declined 1', 'Withdrawn 1']);
    expect(within(chips).getByRole('button', { name: 'Waiting 1' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(chips).getByRole('button', { name: 'Admitted 1' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('shows only the listings with the chosen status', async () => {
    const user = await open();
    expect(rowIfShown('lst-1')).not.toBeNull();
    expect(rowIfShown('lst-2')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Admitted 1' }));
    expect(rowIfShown('lst-1')).toBeNull();
    expect(rowIfShown('lst-2')).not.toBeNull();
    expect(screen.getByRole('button', { name: 'Admitted 1' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('says so when no listing has the chosen status', async () => {
    server.use(http.get('/api/bff/network-admin/listings', () => HttpResponse.json({ ...VIEW_LISTINGS, listings: VIEW_LISTINGS.listings.filter((l) => l.id === 'lst-1') })));
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Declined 0' }));
    expect(screen.getByText('No listings with this status.')).toBeInTheDocument();
  });
});

describe('the table', () => {
  it('has the board’s columns: organisation, service, status and an action column', async () => {
    await open();
    expect(within(byEl('NADM-LISTINGS-TABLE')).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Organisation', 'Service', 'Status', 'Action']);
  });

  it('says for each listing the organisation, the service’s reference and the status in words', async () => {
    const user = await open();
    expect(within(rowOf('lst-1')).getAllByRole('cell').slice(0, 3).map((c) => c.textContent)).toEqual(['Sample Area A', 'svc-ucr-west', 'Waiting']);
    await user.click(screen.getByRole('button', { name: 'Admitted 1' }));
    expect(within(rowOf('lst-2')).getByText('Admitted')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Paused 1' }));
    expect(within(rowOf('lst-3')).getAllByRole('cell').slice(0, 3).map((c) => c.textContent)).toEqual(['Sample Area B', 'svc-beds', 'Paused']);
    await user.click(screen.getByRole('button', { name: 'Declined 1' }));
    expect(within(rowOf('lst-4')).getByText('Declined')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Withdrawn 1' }));
    expect(within(rowOf('lst-5')).getByText('Withdrawn')).toBeInTheDocument();
  });

  it('offers the buttons that fit the status and no others', async () => {
    const user = await open();
    const names = (id: string) => within(rowOf(id)).queryAllByRole('button').map((b) => b.textContent?.replace(/\s+/g, ' ').trim().split(' ')[0]);
    expect(names('lst-1')).toEqual(['Admit', 'Decline']);
    await user.click(screen.getByRole('button', { name: 'Admitted 1' }));
    expect(names('lst-2')).toEqual(['Pause']);
    await user.click(screen.getByRole('button', { name: 'Paused 1' }));
    expect(names('lst-3')).toEqual(['Reinstate']);
    await user.click(screen.getByRole('button', { name: 'Declined 1' }));
    expect(names('lst-4')).toEqual([]);
    await user.click(screen.getByRole('button', { name: 'Withdrawn 1' }));
    expect(names('lst-5')).toEqual([]);
  });

  it('names the organisation and the service on each button', async () => {
    await open();
    expect(within(rowOf('lst-1')).getByRole('button', { name: 'Admit svc-ucr-west of Sample Area A' })).toBeInTheDocument();
    expect(within(rowOf('lst-1')).getByRole('button', { name: 'Decline svc-ucr-west of Sample Area A' })).toBeInTheDocument();
  });

  it('says Nothing here yet. for an empty table, and could not load on a failure', async () => {
    server.use(http.get('/api/bff/network-admin/listings', () => HttpResponse.json({ ...VIEW_LISTINGS, listings: [] })));
    render(<NetworkListings />);
    await screen.findByRole('table', { name: 'Listings' }, { timeout: 5000 });
    expect(screen.getByText('Nothing here yet.')).toBeInTheDocument();
    expect(screen.getByText(/Organisations list their own services/)).toBeInTheDocument();
  });

  it('says it could not load, with no table', async () => {
    server.use(http.get('/api/bff/network-admin/listings', () => HttpResponse.json({}, { status: 503 })));
    render(<NetworkListings />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the listings.');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('holds no tenant id and nothing about a person', async () => {
    await open();
    expect(document.body.innerHTML).not.toMatch(/trust-|tenant|account|organisation_name|service_id/i);
  });

  it('has no accessibility violation', async () => {
    await open();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});

describe('admitting and reinstating', () => {
  it('admits by the listing’s handle with the CSRF token and no reason', async () => {
    const user = await open();
    await user.click(byEl('NADM-LISTING-ADMIT-BTN', rowOf('lst-1')));
    await waitFor(() => expect(seenNetworkAdminWrites).toHaveLength(1));
    expect(seenNetworkAdminWrites[0]).toMatchObject({ method: 'POST', path: '/api/bff/network-admin/listings/lst-1/admit', csrf: SAMPLE_CSRF });
    expect(seenNetworkAdminWrites[0]?.body ?? {}).toEqual({});
    expect(await screen.findByRole('status')).toHaveTextContent('Listing admitted.');
  });

  it('reinstates a paused listing', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Paused 1' }));
    await user.click(byEl('NADM-LISTING-REINSTATE-BTN', rowOf('lst-3')));
    await waitFor(() => expect(seenNetworkAdminWrites).toHaveLength(1));
    expect(seenNetworkAdminWrites[0]).toMatchObject({ path: '/api/bff/network-admin/listings/lst-3/reinstate' });
    expect(await screen.findByRole('status')).toHaveTextContent('Listing reinstated.');
  });

  it('says it could not be done on a failure', async () => {
    server.use(http.post('/api/bff/network-admin/listings/:id/admit', () => HttpResponse.json({}, { status: 503 })));
    const user = await open();
    await user.click(byEl('NADM-LISTING-ADMIT-BTN', rowOf('lst-1')));
    expect(await screen.findByRole('alert')).toHaveTextContent('That could not be done. Try again.');
  });
});

describe('declining and pausing, with the reason in place', () => {
  it('opens the decline panel beside the table, with no dialog, and offers the reasons as a group of choices', async () => {
    const user = await open();
    await user.click(byEl('NADM-LISTING-DECLINE-BTN', rowOf('lst-1')));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    const panel = screen.getByRole('region', { name: 'Decline svc-ucr-west' });
    const group = within(panel).getByRole('group', { name: 'Reason' });
    expect(within(group).getAllByRole('radio').map((r) => r.closest('label')?.textContent)).toEqual([
      'Outside the area',
      'Outside the pilot',
      'Duplicate listing',
      'Data quality',
      'Safety concern',
      'Agreement',
      'Other',
    ]);
    expect(within(group).getAllByRole('radio').every((r) => (r as HTMLInputElement).checked === false)).toBe(true);
    expect(seenNetworkAdminWrites).toEqual([]);
  });

  it('moves between the reasons with the arrow keys', async () => {
    const user = await open();
    await user.click(byEl('NADM-LISTING-DECLINE-BTN', rowOf('lst-1')));
    const group = within(screen.getByRole('region', { name: 'Decline svc-ucr-west' })).getByRole('group', { name: 'Reason' });
    within(group).getByRole('radio', { name: 'Outside the area' }).focus();
    await user.keyboard('{ArrowDown}');
    expect(within(group).getByRole('radio', { name: 'Outside the pilot' })).toBeChecked();
  });

  it('needs a reason: with none chosen it says so and sends nothing', async () => {
    const user = await open();
    await user.click(byEl('NADM-LISTING-DECLINE-BTN', rowOf('lst-1')));
    await user.click(byEl('NADM-LISTING-CONFIRM-BTN'));
    expect(await screen.findByText('Choose a reason.')).toBeInTheDocument();
    expect(seenNetworkAdminWrites).toEqual([]);
  });

  it('declines with the reason code, never words', async () => {
    const user = await open();
    await user.click(byEl('NADM-LISTING-DECLINE-BTN', rowOf('lst-1')));
    await user.click(screen.getByRole('radio', { name: 'Outside the pilot' }));
    await user.click(byEl('NADM-LISTING-CONFIRM-BTN'));
    await waitFor(() => expect(seenNetworkAdminWrites).toHaveLength(1));
    expect(seenNetworkAdminWrites[0]).toMatchObject({ path: '/api/bff/network-admin/listings/lst-1/decline', csrf: SAMPLE_CSRF, body: { reason: 'outside-pilot' } });
    expect(await screen.findByRole('status')).toHaveTextContent('Listing declined.');
  });

  it('pauses with the reason code, in the board’s words', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Admitted 1' }));
    await user.click(byEl('NADM-LISTING-PAUSE-BTN', rowOf('lst-2')));
    const panel = screen.getByRole('region', { name: 'Pause svc-sdec' });
    expect(within(panel).getByText('It leaves the live board now and shows as paused. Say why: the reason is kept in the history.')).toBeInTheDocument();
    await user.click(within(panel).getByRole('radio', { name: 'Data quality' }));
    await user.click(byEl('NADM-LISTING-CONFIRM-BTN'));
    await waitFor(() => expect(seenNetworkAdminWrites).toHaveLength(1));
    expect(seenNetworkAdminWrites[0]).toMatchObject({ path: '/api/bff/network-admin/listings/lst-2/suspend', body: { reason: 'data-quality' } });
    expect(await screen.findByRole('status')).toHaveTextContent('Listing paused.');
  });

  it('shows what viewers see of a paused service beside the pause panel', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Admitted 1' }));
    await user.click(byEl('NADM-LISTING-PAUSE-BTN', rowOf('lst-2')));
    expect(screen.getByText('What viewers see')).toBeInTheDocument();
    expect(screen.getByText(/Not available on the network. Phone to confirm./)).toBeInTheDocument();
  });

  it('does nothing when it is cancelled, and gives focus back to the button that opened it', async () => {
    const user = await open();
    const opener = byEl('NADM-LISTING-DECLINE-BTN', rowOf('lst-1'));
    await user.click(opener);
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('region', { name: 'Decline svc-ucr-west' })).not.toBeInTheDocument();
    expect(seenNetworkAdminWrites).toEqual([]);
    expect(opener).toHaveFocus();
  });

  it('keeps the panel and says so when it could not be done', async () => {
    server.use(http.post('/api/bff/network-admin/listings/:id/decline', () => HttpResponse.json({}, { status: 503 })));
    const user = await open();
    await user.click(byEl('NADM-LISTING-DECLINE-BTN', rowOf('lst-1')));
    await user.click(screen.getByRole('radio', { name: 'Other' }));
    await user.click(byEl('NADM-LISTING-CONFIRM-BTN'));
    expect(await screen.findByRole('alert')).toHaveTextContent('That could not be done. Try again.');
    expect(screen.getByRole('region', { name: 'Decline svc-ucr-west' })).toBeInTheDocument();
  });

  it('has no accessibility violation with a panel open', async () => {
    const user = await open();
    await user.click(byEl('NADM-LISTING-DECLINE-BTN', rowOf('lst-1')));
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
