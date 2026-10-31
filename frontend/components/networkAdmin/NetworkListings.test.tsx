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

// The listings of the network (TEN-080, design N1: NetworkListings). The owner admits a member's service to
// the network, declines it, pauses it and reinstates it. A reason is one of the fixed codes, never free text.

beforeEach(() => {
  resetNetworkAdminWrites();
  resetNetworkAdminReads();
});

async function open() {
  const user = userEvent.setup();
  render(<NetworkListings />);
  await screen.findByRole('table', { name: 'Listings' });
  return user;
}
const rowOf = (id: string) => {
  const found = document.querySelector<HTMLElement>(`[data-row-ref="${id}"]`);
  if (found === null) throw new Error(`no row ${id}`);
  return found;
};

describe('the table', () => {
  it('has the design’s columns, with the reason of a decline or a pause and an action column', async () => {
    await open();
    expect(within(byEl('NADM-LISTINGS-TABLE')).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Organisation', 'Service', 'Status', 'Reason', 'Action']);
  });

  it('says for each listing the organisation, the service’s reference, the status in words and the reason', async () => {
    await open();
    expect(within(rowOf('lst-1')).getAllByRole('cell').slice(0, 4).map((c) => c.textContent)).toEqual(['Sample Area A', 'svc-ucr-west', 'Waiting', '-']);
    expect(within(rowOf('lst-2')).getByText('Admitted')).toBeInTheDocument();
    expect(within(rowOf('lst-3')).getAllByRole('cell').slice(2, 4).map((c) => c.textContent)).toEqual(['Paused', 'Data quality']);
    expect(within(rowOf('lst-4')).getAllByRole('cell').slice(2, 4).map((c) => c.textContent)).toEqual(['Declined', 'Outside the area']);
    expect(within(rowOf('lst-5')).getByText('Withdrawn')).toBeInTheDocument();
  });

  it('offers the buttons that fit the status and no others', async () => {
    await open();
    const names = (id: string) => within(rowOf(id)).queryAllByRole('button').map((b) => b.textContent?.replace(/\s+/g, ' ').trim().split(' ')[0]);
    expect(names('lst-1')).toEqual(['Admit', 'Decline']);
    expect(names('lst-2')).toEqual(['Pause']);
    expect(names('lst-3')).toEqual(['Reinstate']);
    expect(names('lst-4')).toEqual([]);
    expect(names('lst-5')).toEqual([]);
  });

  it('names the organisation and the service on each button', async () => {
    await open();
    expect(within(rowOf('lst-1')).getByRole('button', { name: 'Admit svc-ucr-west of Sample Area A' })).toBeInTheDocument();
  });

  it('says Nothing here yet. for an empty table, and could not load on a failure', async () => {
    server.use(http.get('/api/bff/network-admin/listings', () => HttpResponse.json({ ...VIEW_LISTINGS, listings: [] })));
    render(<NetworkListings />);
    await screen.findByRole('table', { name: 'Listings' });
    expect(screen.getByText('Nothing here yet.')).toBeInTheDocument();
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

describe('declining and pausing', () => {
  it('asks for a reason from the fixed list, in the design’s words, before sending anything', async () => {
    const user = await open();
    await user.click(byEl('NADM-LISTING-DECLINE-BTN', rowOf('lst-1')));
    const dialog = screen.getByRole('dialog', { name: 'Decline this listing?' });
    const select = within(dialog).getByRole('combobox', { name: 'Reason' });
    expect(select).toBe(byEl('NADM-LISTING-REASON-SELECT').querySelector('select') ?? byEl('NADM-LISTING-REASON-SELECT'));
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'Choose a reason',
      'Outside the area',
      'Outside the pilot',
      'Duplicate listing',
      'Data quality',
      'Safety concern',
      'Agreement',
      'Other',
    ]);
    expect(seenNetworkAdminWrites).toEqual([]);
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
    await user.selectOptions(screen.getByRole('combobox', { name: 'Reason' }), 'Outside the pilot');
    await user.click(byEl('NADM-LISTING-CONFIRM-BTN'));
    await waitFor(() => expect(seenNetworkAdminWrites).toHaveLength(1));
    expect(seenNetworkAdminWrites[0]).toMatchObject({ path: '/api/bff/network-admin/listings/lst-1/decline', csrf: SAMPLE_CSRF, body: { reason: 'outside-pilot' } });
    expect(await screen.findByRole('status')).toHaveTextContent('Listing declined.');
  });

  it('pauses with the reason code and says that a paused listing shows as not available', async () => {
    const user = await open();
    await user.click(byEl('NADM-LISTING-PAUSE-BTN', rowOf('lst-2')));
    const dialog = screen.getByRole('dialog', { name: 'Pause this listing?' });
    expect(within(dialog).getByText('A paused listing stops showing on the network. It shows as not available until it is reinstated.')).toBeInTheDocument();
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Reason' }), 'Data quality');
    await user.click(byEl('NADM-LISTING-CONFIRM-BTN'));
    await waitFor(() => expect(seenNetworkAdminWrites).toHaveLength(1));
    expect(seenNetworkAdminWrites[0]).toMatchObject({ path: '/api/bff/network-admin/listings/lst-2/suspend', body: { reason: 'data-quality' } });
    expect(await screen.findByRole('status')).toHaveTextContent('Listing paused.');
  });

  it('does nothing when it is cancelled, and gives focus back', async () => {
    const user = await open();
    const opener = byEl('NADM-LISTING-DECLINE-BTN', rowOf('lst-1'));
    await user.click(opener);
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }));
    expect(seenNetworkAdminWrites).toEqual([]);
    expect(opener).toHaveFocus();
  });

  it('keeps the dialog and says so when it could not be done', async () => {
    server.use(http.post('/api/bff/network-admin/listings/:id/decline', () => HttpResponse.json({}, { status: 503 })));
    const user = await open();
    await user.click(byEl('NADM-LISTING-DECLINE-BTN', rowOf('lst-1')));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Reason' }), 'Other');
    await user.click(byEl('NADM-LISTING-CONFIRM-BTN'));
    expect(await screen.findByRole('alert')).toHaveTextContent('That could not be done. Try again.');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });
});
