import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { ORGANISATION_CODE, ownGrant, sharingNetwork, VIEW_SHARING_PAGE } from '@/test/fixtures/networkAdmin';
import { read, resetNetworkAdminReads, resetNetworkAdminWrites, seenNetworkAdminWrites } from '@/test/msw/handlers/networkAdmin';
import { SAMPLE_CSRF } from '@/test/msw/handlers/staff';
import { server } from '@/test/msw/server';
import { SharingOverview } from './SharingOverview';

// Sharing with the network, for the member organisation's administrator (TEN-081, design N2: SharingOverview,
// SharingFields, SharingEnd, SharingLeave, SharingAgreement, SharingHistory). Sharing is read only: other
// organisations see only the fields listed here, and no patient information is ever shared.

beforeEach(() => {
  resetNetworkAdminWrites();
  resetNetworkAdminReads();
});

async function open() {
  const user = userEvent.setup();
  render(<SharingOverview />);
  await screen.findAllByRole('region', { name: /^(Capacity|Directory|Criteria)$/ });
  return user;
}
const card = (scope: 'Capacity' | 'Directory' | 'Criteria') => screen.getByRole('region', { name: scope });
const page = (over: Partial<typeof VIEW_SHARING_PAGE>) => server.use(http.get('/api/bff/sharing', read({ ...VIEW_SHARING_PAGE, ...over })));

describe('what the page says', () => {
  it('names the page, says that sharing is read only and what is never shared, in the design’s words', async () => {
    await open();
    expect(screen.getByRole('heading', { level: 1, name: 'Sharing with the network' })).toBeInTheDocument();
    expect(screen.getByText('Sharing is read only. Other organisations see only the fields listed here. No patient information is ever shared.')).toBeInTheDocument();
    expect(screen.getByText("Never shared: reporters' names, phone numbers, devices and PINs; links and codes; messages sent or received; bookings and cases; audit entries; anything about a patient.")).toBeInTheDocument();
  });

  it('gives the organisation’s own code, so the network owner can invite it', async () => {
    await open();
    const section = screen.getByRole('region', { name: 'Your organisation code' });
    expect(within(section).getByText(ORGANISATION_CODE)).toBeInTheDocument();
    expect(within(section).getByText('Give this code to the network owner so that they can invite your organisation.')).toBeInTheDocument();
  });

  it('has one card for each kind, each with its state in the design’s words and the fields it shares', async () => {
    await open();
    const cards = screen.getAllByRole('region', { name: /^(Capacity|Directory|Criteria)$/ });
    expect(cards).toHaveLength(3);
    for (const el of cards) {
      expect(el).toHaveAttribute('data-el', 'SHARE-SCOPE-CARD');
      expect(within(el).getByRole('list', { name: /^Fields shared:/ })).toBeInTheDocument();
    }
    expect(within(card('Capacity')).getByText('Waiting for your approval')).toBeInTheDocument();
    expect(within(card('Directory')).getByText('Sharing since 4 Oct 2026')).toBeInTheDocument();
    expect(within(card('Criteria')).getByText('Not sharing')).toBeInTheDocument();
  });

  it('lists exactly which fields leave, rendered from the allowlist the back end sent', async () => {
    await open();
    expect(within(within(card('Criteria')).getByRole('list')).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Age range',
      'Postcode districts',
      'Needs accepted and needs excluded',
      'Review-by date',
      'Current version number',
    ]);
  });

  it('says whether the network is getting what is in force', async () => {
    await open();
    expect(within(card('Directory')).getByText('The network is receiving this.')).toBeInTheDocument();
  });

  it('says that a grant needs two approvals from two different people, beside the one that waits', async () => {
    await open();
    expect(within(card('Capacity')).getByText(/needs the approval of your organisation and of the network owner, from two different people/)).toBeInTheDocument();
  });

  it('shows the network, the membership and the agreement’s reference, never its content', async () => {
    await open();
    expect(screen.getByRole('heading', { level: 2, name: 'Sample Network' })).toBeInTheDocument();
    expect(screen.getByText('Agreement DSA-2026-1, version 1.')).toBeInTheDocument();
  });

  it('holds no tenant id but its own code, no handle and none of the back end’s own names', async () => {
    await open();
    expect(document.body.innerHTML).not.toMatch(/trust-|mem-|network_id|organisation_name|tenant_id|membership/i);
  });

  it('says it could not load, with no card, on a failure', async () => {
    server.use(http.get('/api/bff/sharing', () => HttpResponse.json({}, { status: 503 })));
    render(<SharingOverview />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load what your organisation shares.');
    expect(screen.queryByRole('region', { name: 'Capacity' })).not.toBeInTheDocument();
  });

  it('says nothing can be listed, and offers no approval, when a field has no sentence', async () => {
    page({ allowlist: { ...VIEW_SHARING_PAGE.allowlist, scopes: { ...VIEW_SHARING_PAGE.allowlist.scopes, capacity: [...VIEW_SHARING_PAGE.allowlist.scopes.capacity, 'reporter_name'] } } });
    await open();
    expect(within(card('Capacity')).getByRole('alert')).toHaveTextContent('We could not list the fields that are shared. Do not approve this until it is fixed.');
    expect(within(card('Capacity')).queryByRole('button', { name: /Approve/ })).not.toBeInTheDocument();
    expect(within(card('Directory')).getByRole('button', { name: 'End sharing' })).toBeInTheDocument();
  });

  it('has no accessibility violation', async () => {
    await open();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});

describe('an organisation that is in no network', () => {
  it('says so, lists what could be shared, and offers nothing to do', async () => {
    page({ networks: [] });
    render(<SharingOverview />);
    await screen.findByText('Your organisation is not in a network.');
    expect(screen.getAllByRole('list', { name: /^Fields shared:/ })).toHaveLength(3);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Your organisation code' })).toBeInTheDocument();
  });
});

describe('the buttons that fit the state', () => {
  const names = (el: HTMLElement) => within(el).queryAllByRole('button').map((b) => b.textContent?.trim());

  it('are Approve and Decline while the organisation’s approval is to come, End sharing while in force, and Propose sharing when there is nothing', async () => {
    await open();
    expect(names(card('Capacity'))).toEqual(['Approve', 'Decline']);
    expect(names(card('Directory'))).toEqual(['End sharing']);
    expect(names(card('Criteria'))).toEqual(['Propose sharing']);
    expect(byEl('SHARE-APPROVE-BTN', card('Capacity'))).toBeInTheDocument();
    expect(byEl('SHARE-DECLINE-BTN', card('Capacity'))).toBeInTheDocument();
    expect(byEl('SHARE-END-BTN', card('Directory'))).toBeInTheDocument();
    expect(byEl('SHARE-PROPOSE-BTN', card('Criteria'))).toBeInTheDocument();
  });

  it('are none while the network owner’s approval is to come', async () => {
    page({ networks: [sharingNetwork({ grants: [ownGrant('g1', 'capacity', 'grantor-approved', { grantorApprovedAt: '2026-10-04T09:00:00Z' })] })] });
    await open();
    expect(within(card('Capacity')).getByText('Waiting for the network owner')).toBeInTheDocument();
    expect(names(card('Capacity'))).toEqual([]);
  });

  it('offer a new proposal after an ending, and say when it ended', async () => {
    page({ networks: [sharingNetwork({ shared: [], grants: [ownGrant('g1', 'capacity', 'ended', { endedAt: '2026-10-20T09:00:00Z', endReason: 'ended' })] })] });
    await open();
    expect(within(card('Capacity')).getByText('Ended on 20 Oct 2026')).toBeInTheDocument();
    expect(names(card('Capacity'))).toEqual(['Propose sharing']);
  });

  it('say that an approved grant has not started when its window is still to come, and offer to end it', async () => {
    page({ networks: [sharingNetwork({ shared: [], grants: [ownGrant('g1', 'capacity', 'approved', { effective: false, effectiveFrom: '2026-12-01T09:00:00Z' })] })] });
    await open();
    expect(within(card('Capacity')).getByText('Approved. Sharing starts on 1 Dec 2026')).toBeInTheDocument();
    expect(names(card('Capacity'))).toEqual(['End sharing']);
  });

  it('name the kind on each button so a screen reader hears more than "Approve"', async () => {
    await open();
    expect(screen.getByRole('button', { name: 'Approve sharing capacity' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'End sharing directory' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Propose sharing criteria' })).toBeInTheDocument();
  });
});

describe('approving and declining', () => {
  it('approves by the grant’s handle with the CSRF token, and says the grant starts when the owner has approved too', async () => {
    const user = await open();
    await user.click(byEl('SHARE-APPROVE-BTN', card('Capacity')));
    await waitFor(() => expect(seenNetworkAdminWrites).toHaveLength(1));
    expect(seenNetworkAdminWrites[0]).toMatchObject({ method: 'POST', path: '/api/bff/sharing/grants/grant-cap/approve', query: 'networkId=net-sample', csrf: SAMPLE_CSRF });
    expect(await screen.findByRole('status')).toHaveTextContent('Your approval is recorded. Sharing starts when the network owner has approved too.');
  });

  it('says sharing starts now when this was the second approval', async () => {
    server.use(http.post('/api/bff/sharing/grants/:id/approve', () => HttpResponse.json({ effective: true })));
    const user = await open();
    await user.click(byEl('SHARE-APPROVE-BTN', card('Capacity')));
    expect(await screen.findByRole('status')).toHaveTextContent('Approved. Sharing capacity starts now.');
  });

  it('says the same person cannot give both approvals on a conflict', async () => {
    server.use(http.post('/api/bff/sharing/grants/:id/approve', () => HttpResponse.json({ code: 'conflict' }, { status: 409 })));
    const user = await open();
    await user.click(byEl('SHARE-APPROVE-BTN', card('Capacity')));
    expect(await screen.findByRole('alert')).toHaveTextContent('That could not be done. If you gave the other approval yourself, another person must give this one.');
  });

  it('says it could not be done on a failure', async () => {
    server.use(http.post('/api/bff/sharing/grants/:id/approve', () => HttpResponse.json({}, { status: 503 })));
    const user = await open();
    await user.click(byEl('SHARE-APPROVE-BTN', card('Capacity')));
    expect(await screen.findByRole('alert')).toHaveTextContent('That could not be done. Try again.');
  });

  it('asks before declining, and sends nothing until it is confirmed', async () => {
    const user = await open();
    await user.click(byEl('SHARE-DECLINE-BTN', card('Capacity')));
    const dialog = screen.getByRole('dialog', { name: 'Decline sharing capacity?' });
    expect(within(dialog).getByText('Nothing is shared. You can propose sharing again at any time.')).toBeInTheDocument();
    expect(seenNetworkAdminWrites).toEqual([]);
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(seenNetworkAdminWrites).toEqual([]);
  });

  it('declines by the grant’s handle once confirmed', async () => {
    const user = await open();
    await user.click(byEl('SHARE-DECLINE-BTN', card('Capacity')));
    await user.click(byEl('SHARE-DECLINE-CONFIRM-BTN'));
    await waitFor(() => expect(seenNetworkAdminWrites).toHaveLength(1));
    expect(seenNetworkAdminWrites[0]).toMatchObject({ path: '/api/bff/sharing/grants/grant-cap/decline', csrf: SAMPLE_CSRF });
    expect(await screen.findByRole('status')).toHaveTextContent('Declined. Nothing is shared.');
  });
});

describe('proposing and ending', () => {
  it('proposes the kind and nothing else, naming the network the page was offered, and says what happens next', async () => {
    const user = await open();
    await user.click(byEl('SHARE-PROPOSE-BTN', card('Criteria')));
    await waitFor(() => expect(seenNetworkAdminWrites).toHaveLength(1));
    expect(seenNetworkAdminWrites[0]).toMatchObject({ method: 'POST', path: '/api/bff/sharing/grants', query: 'networkId=net-sample', csrf: SAMPLE_CSRF, body: { kind: 'criteria' } });
    expect(await screen.findByRole('status')).toHaveTextContent('Proposed. It now waits for your approval.');
  });

  it('says there is already an open proposal when the back end refuses with a conflict', async () => {
    server.use(http.post('/api/bff/sharing/grants', () => HttpResponse.json({ code: 'conflict' }, { status: 409 })));
    const user = await open();
    await user.click(byEl('SHARE-PROPOSE-BTN', card('Criteria')));
    expect(await screen.findByRole('alert')).toHaveTextContent('There is already an open proposal for this. Reload the page.');
  });

  it('asks before ending, in the design’s words, and sends nothing until it is confirmed', async () => {
    const user = await open();
    await user.click(byEl('SHARE-END-BTN', card('Directory')));
    const dialog = screen.getByRole('dialog', { name: 'End sharing directory?' });
    expect(within(dialog).getByText('New data stops being shared straight away. What was already shared stays in the network history, marked with today’s date.')).toBeInTheDocument();
    expect(seenNetworkAdminWrites).toEqual([]);
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(seenNetworkAdminWrites).toEqual([]);
  });

  it('ends by the grant’s handle once confirmed, and says it ended', async () => {
    const user = await open();
    await user.click(byEl('SHARE-END-BTN', card('Directory')));
    await user.click(byEl('SHARE-END-CONFIRM-BTN'));
    await waitFor(() => expect(seenNetworkAdminWrites).toHaveLength(1));
    expect(seenNetworkAdminWrites[0]).toMatchObject({ path: '/api/bff/sharing/grants/grant-dir/end', csrf: SAMPLE_CSRF });
    expect(await screen.findByRole('status')).toHaveTextContent('Sharing ended.');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('keeps the dialog and says so when ending fails, and gives focus back when it is cancelled', async () => {
    server.use(http.post('/api/bff/sharing/grants/:id/end', () => HttpResponse.json({}, { status: 503 })));
    const user = await open();
    const opener = byEl('SHARE-END-BTN', card('Directory'));
    await user.click(opener);
    await user.click(byEl('SHARE-END-CONFIRM-BTN'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Sharing could not be ended. Try again.');
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }));
    expect(opener).toHaveFocus();
  });
});

describe('leaving the network', () => {
  it('is offered for a network the organisation is in and does not own, and asks first', async () => {
    const user = await open();
    await user.click(byEl('SHARE-LEAVE-BTN'));
    const dialog = screen.getByRole('dialog', { name: 'Leave Sample Network?' });
    expect(within(dialog).getByText('All your sharing ends now. What was already shared stays in the history, marked with the date you left.')).toBeInTheDocument();
    expect(seenNetworkAdminWrites).toEqual([]);
  });

  it('leaves the network the page was offered once confirmed, and says so', async () => {
    const user = await open();
    await user.click(byEl('SHARE-LEAVE-BTN'));
    await user.click(byEl('SHARE-LEAVE-CONFIRM-BTN'));
    await waitFor(() => expect(seenNetworkAdminWrites).toHaveLength(1));
    expect(seenNetworkAdminWrites[0]).toMatchObject({ path: '/api/bff/sharing/leave', query: 'networkId=net-sample', csrf: SAMPLE_CSRF });
    expect(await screen.findByRole('status')).toHaveTextContent('You have left Sample Network. What was shared stays in its history.');
  });

  it('is not offered to the owner of the network, nor after leaving', async () => {
    page({ networks: [sharingNetwork({ isOwner: true })] });
    await open();
    expect(screen.queryByRole('button', { name: /Leave network/ })).not.toBeInTheDocument();
  });

  it('shows a network that was left with its date and no buttons', async () => {
    page({ networks: [sharingNetwork({ membershipStatus: 'left', leftAt: '2026-10-28T10:00:00Z', shared: [], grants: [ownGrant('g1', 'capacity', 'lapsed', { endedAt: '2026-10-28T10:00:00Z', endReason: 'lapsed' })] })] });
    render(<SharingOverview />);
    await screen.findByText('You left this network on 28 Oct 2026.');
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});

describe('the agreement', () => {
  it('says a newer version is available and accepts the version the administrator read', async () => {
    page({ networks: [sharingNetwork({ agreementVersion: 2, agreementBehind: true })] });
    const user = await open();
    expect(screen.getByText('Agreement version 2 is available.')).toBeInTheDocument();
    await user.click(byEl('SHARE-AGREEMENT-ACCEPT-BTN'));
    await waitFor(() => expect(seenNetworkAdminWrites).toHaveLength(1));
    expect(seenNetworkAdminWrites[0]).toMatchObject({ path: '/api/bff/sharing/agreement', query: 'networkId=net-sample', csrf: SAMPLE_CSRF, body: { agreementVersion: 2 } });
    expect(await screen.findByRole('status')).toHaveTextContent('Agreement version 2 accepted.');
  });

  it('names the version on the button and never shows the agreement’s content', async () => {
    page({ networks: [sharingNetwork({ agreementVersion: 2, agreementBehind: true })] });
    await open();
    expect(screen.getByRole('button', { name: 'Accept version 2' })).toBeInTheDocument();
  });

  it('is offered for an invitation not yet accepted, and shows no sharing card to act on until it is', async () => {
    page({ networks: [sharingNetwork({ membershipStatus: 'invited', joinedAt: null, acceptedAgreementVersion: null, shared: [], grants: [] })] });
    render(<SharingOverview />);
    await screen.findByText('You have been invited to Sample Network.');
    expect(screen.getByRole('button', { name: 'Accept version 1' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Propose sharing/ })).not.toBeInTheDocument();
  });

  it('is not offered when the organisation is up to date', async () => {
    await open();
    expect(screen.queryByRole('button', { name: /Accept version/ })).not.toBeInTheDocument();
  });

  it('says it could not be accepted on a failure', async () => {
    server.use(http.post('/api/bff/sharing/agreement', () => HttpResponse.json({}, { status: 503 })));
    page({ networks: [sharingNetwork({ agreementVersion: 2, agreementBehind: true })] });
    const user = await open();
    await user.click(byEl('SHARE-AGREEMENT-ACCEPT-BTN'));
    expect(await screen.findByRole('alert')).toHaveTextContent('The agreement could not be accepted. Try again.');
  });
});

describe('the history', () => {
  it('has a link to it and says who the data has been shared with, since when, and what ended', async () => {
    page({
      networks: [
        sharingNetwork({
          grants: [
            ownGrant('g1', 'directory', 'approved', { effective: true }),
            ownGrant('g2', 'capacity', 'ended', { effectiveFrom: '2026-10-05T09:00:00Z', endedAt: '2026-10-20T09:00:00Z', endReason: 'ended' }),
            ownGrant('g3', 'criteria', 'declined'),
          ],
        }),
      ],
    });
    await open();
    expect(byEl('SHARE-HISTORY-LINK')).toHaveAttribute('href', '#history');
    const history = screen.getByRole('region', { name: 'History' });
    expect(within(history).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Directory: Shared with Sample Network since 4 Oct 2026',
      'Capacity: Shared with Sample Network since 5 Oct 2026. Ended on 20 Oct 2026',
    ]);
  });

  it('says Nothing here yet. when nothing was ever shared', async () => {
    page({ networks: [sharingNetwork({ grants: [], shared: [] })] });
    await open();
    expect(within(screen.getByRole('region', { name: 'History' })).getByText('Nothing here yet.')).toBeInTheDocument();
  });
});
