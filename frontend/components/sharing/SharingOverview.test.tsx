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

// Sharing with the network, for the member organisation's administrator (board A6, right half: admin-operator-public.md
// section 3, /admin/sharing). Sharing is read only: other organisations see only the fields listed here, and no patient
// information is ever shared. Each kind is a row that says its state in a tag and opens, on request, to its detail; one
// row is open at a time. The history is a disclosure, closed until asked for.

type Kind = 'Capacity' | 'Service directory' | 'Criteria';
const KIND_NAMES = /^(Capacity|Service directory|Criteria)$/;

beforeEach(() => {
  resetNetworkAdminWrites();
  resetNetworkAdminReads();
});

async function open() {
  const user = userEvent.setup();
  render(<SharingOverview />);
  await screen.findAllByRole('region', { name: KIND_NAMES }, { timeout: 5000 });
  return user;
}
const card = (kind: Kind) => screen.getByRole('region', { name: kind });
const page = (over: Partial<typeof VIEW_SHARING_PAGE>) => server.use(http.get('/api/bff/sharing', read({ ...VIEW_SHARING_PAGE, ...over })));
const openRow = async (user: ReturnType<typeof userEvent.setup>, kind: Kind) => {
  await user.click(within(card(kind)).getByRole('button', { expanded: false }));
};
const actionNames = (kind: Kind) =>
  within(card(kind))
    .queryAllByRole('button')
    .filter((button) => !button.hasAttribute('aria-expanded'))
    .map((button) => button.textContent?.trim());

describe('what the page says', () => {
  it('names the page, gives the design’s lead sentence, and says what is never shared', async () => {
    await open();
    expect(screen.getByRole('heading', { level: 1, name: 'Sharing with the network' })).toBeInTheDocument();
    expect(
      screen.getByText('You share only what you agree to, and you can end it at any time. Each kind of sharing needs two approvals: one from you and one from the network owner.'),
    ).toBeInTheDocument();
    expect(screen.getByText("Never shared: reporters' names, phone numbers, devices and PINs; links and codes; messages sent or received; bookings and cases; audit entries; anything about a patient.")).toBeInTheDocument();
  });

  it('gives the organisation’s own code in its own section, with a Copy button', async () => {
    await open();
    const section = screen.getByRole('region', { name: 'Your organisation code' });
    expect(within(section).getByText(ORGANISATION_CODE)).toBeInTheDocument();
    expect(within(section).getByRole('button', { name: 'Copy' })).toBeInTheDocument();
  });

  it('copies the code and says so', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Copy' }));
    expect(await screen.findByText('Copied.')).toBeInTheDocument();
  });

  it('has one row for each kind, with what it shares in a line and its state in a tag', async () => {
    await open();
    expect(screen.getAllByRole('region', { name: KIND_NAMES })).toHaveLength(3);
    expect(within(card('Capacity')).getByText('How many places each service has now')).toBeInTheDocument();
    expect(within(card('Service directory')).getByText('Which services you run and where')).toBeInTheDocument();
    expect(within(card('Criteria')).getByText('Which patients each service takes')).toBeInTheDocument();
    for (const kind of ['Capacity', 'Service directory', 'Criteria'] as const) expect(card(kind)).toHaveAttribute('data-el', 'SHARE-SCOPE-CARD');
    expect(within(card('Capacity')).getByText('Waiting for your approval')).toBeInTheDocument();
    expect(within(card('Service directory')).getByText('Shared since 4 Oct 2026')).toBeInTheDocument();
    expect(within(card('Criteria')).getByText('Not shared')).toBeInTheDocument();
  });

  it('keeps a closed row’s detail inert, and opens it on request', async () => {
    const user = await open();
    const window = within(card('Service directory')).getByText('From 4 Oct 2026, no end date');
    expect(window.closest('[inert]')).not.toBeNull();
    await openRow(user, 'Service directory');
    expect(within(card('Service directory')).getByRole('button', { expanded: true })).toBeInTheDocument();
    expect(window.closest('[inert]')).toBeNull();
  });

  it('opens one row at a time', async () => {
    const user = await open();
    await openRow(user, 'Capacity');
    expect(within(card('Capacity')).getByRole('button', { expanded: true })).toBeInTheDocument();
    await openRow(user, 'Service directory');
    expect(within(card('Capacity')).getByRole('button', { expanded: false })).toBeInTheDocument();
    expect(within(card('Service directory')).getByRole('button', { expanded: true })).toBeInTheDocument();
  });

  it('says the window of the grant in force and of the one that waits, so what is approved is what is read', async () => {
    const user = await open();
    await openRow(user, 'Service directory');
    expect(within(card('Service directory')).getByText('From 4 Oct 2026, no end date')).toBeInTheDocument();
    await openRow(user, 'Capacity');
    expect(within(card('Capacity')).getByText('From 4 Oct 2026, no end date')).toBeInTheDocument();
    await openRow(user, 'Criteria');
    expect(within(card('Criteria')).queryByText(/^From /)).not.toBeInTheDocument();
  });

  it('says whether the network is getting what is in force', async () => {
    const user = await open();
    await openRow(user, 'Service directory');
    expect(within(card('Service directory')).getByText('The network is receiving this.')).toBeInTheDocument();
  });

  it('says that a grant needs two approvals from two different people, beside the one that waits', async () => {
    const user = await open();
    await openRow(user, 'Capacity');
    expect(within(card('Capacity')).getByText(/needs the approval of your organisation and of the network owner, from two different people/)).toBeInTheDocument();
  });

  it('lists exactly which fields leave, rendered from the allowlist the back end sent', async () => {
    const user = await open();
    await openRow(user, 'Criteria');
    expect(within(within(card('Criteria')).getByRole('list')).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Age range',
      'Postcode districts',
      'Needs accepted and needs excluded',
      'Review-by date',
      'Current version number',
    ]);
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

  it('says it is loading, with the words for a screen reader, before the page arrives', () => {
    render(<SharingOverview />);
    const words = screen.getByText('Loading what your organisation shares.');
    expect(words.closest('[aria-busy="true"]')).not.toBeNull();
  });

  it('says it could not load, with no row, on a failure', async () => {
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
    expect(within(card('Service directory')).getByRole('button', { name: 'End sharing service directory' })).toBeInTheDocument();
  });

  it('has no accessibility violation', async () => {
    await open();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});

describe('an organisation that is in no network', () => {
  it('says under the code that it is not in a network, shows each kind as not shared, and offers nothing to do', async () => {
    page({ networks: [] });
    await open();
    expect(screen.getByText('Give this code to the network owner so they can invite you. You are not in a network yet.')).toBeInTheDocument();
    expect(screen.getAllByText('Not shared')).toHaveLength(3);
    expect(screen.getAllByRole('list', { name: /^Fields shared:/ })).toHaveLength(3);
    expect(screen.queryByRole('button', { name: /^(Approve|Decline|End sharing|Propose sharing|Leave network|Accept version)/ })).not.toBeInTheDocument();
  });

  it('does not say so when the organisation is in a network', async () => {
    await open();
    expect(screen.queryByText(/You are not in a network yet/)).not.toBeInTheDocument();
  });
});

describe('the buttons that fit the state', () => {
  it('are Approve and Decline while the organisation’s approval is to come, End sharing while in force, and Propose sharing when there is nothing', async () => {
    await open();
    expect(actionNames('Capacity')).toEqual(['Approve', 'Decline']);
    expect(actionNames('Service directory')).toEqual(['End sharing']);
    expect(actionNames('Criteria')).toEqual(['Propose sharing']);
    expect(byEl('SHARE-APPROVE-BTN', card('Capacity'))).toBeInTheDocument();
    expect(byEl('SHARE-DECLINE-BTN', card('Capacity'))).toBeInTheDocument();
    expect(byEl('SHARE-END-BTN', card('Service directory'))).toBeInTheDocument();
    expect(byEl('SHARE-PROPOSE-BTN', card('Criteria'))).toBeInTheDocument();
  });

  it('are none while the network owner’s approval is to come', async () => {
    page({ networks: [sharingNetwork({ grants: [ownGrant('g1', 'capacity', 'grantor-approved', { grantorApprovedAt: '2026-10-04T09:00:00Z' })] })] });
    await open();
    expect(within(card('Capacity')).getByText('Waiting for the network owner')).toBeInTheDocument();
    expect(actionNames('Capacity')).toEqual([]);
  });

  it('offer a new proposal after an ending, and say when it ended in the tag', async () => {
    page({ networks: [sharingNetwork({ shared: [], grants: [ownGrant('g1', 'capacity', 'ended', { endedAt: '2026-10-20T09:00:00Z', endReason: 'ended' })] })] });
    await open();
    expect(within(card('Capacity')).getByText('Ended on 20 Oct 2026')).toBeInTheDocument();
    expect(actionNames('Capacity')).toEqual(['Propose sharing']);
  });

  it('say that an approved grant has not started when its window is still to come, and offer to end it', async () => {
    page({ networks: [sharingNetwork({ shared: [], grants: [ownGrant('g1', 'capacity', 'approved', { effective: false, effectiveFrom: '2026-12-01T09:00:00Z' })] })] });
    await open();
    expect(within(card('Capacity')).getByText('Approved. Sharing starts on 1 Dec 2026')).toBeInTheDocument();
    expect(actionNames('Capacity')).toEqual(['End sharing']);
  });

  it('name the kind on each button so a screen reader hears more than "Approve"', async () => {
    await open();
    expect(screen.getByRole('button', { name: 'Approve sharing capacity' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'End sharing service directory' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Propose sharing criteria' })).toBeInTheDocument();
  });
});

describe('approving and declining', () => {
  it('approves by the grant’s handle with the CSRF token, and says the grant starts when the owner has approved too', async () => {
    const user = await open();
    await openRow(user, 'Capacity');
    await user.click(byEl('SHARE-APPROVE-BTN', card('Capacity')));
    await waitFor(() => expect(seenNetworkAdminWrites).toHaveLength(1));
    expect(seenNetworkAdminWrites[0]).toMatchObject({ method: 'POST', path: '/api/bff/sharing/grants/grant-cap/approve', query: 'networkId=net-sample', csrf: SAMPLE_CSRF });
    expect(await screen.findByRole('status')).toHaveTextContent('Your approval is recorded. Sharing starts when the network owner has approved too.');
  });

  it('says sharing starts now when this was the second approval', async () => {
    server.use(http.post('/api/bff/sharing/grants/:id/approve', () => HttpResponse.json({ effective: true })));
    const user = await open();
    await openRow(user, 'Capacity');
    await user.click(byEl('SHARE-APPROVE-BTN', card('Capacity')));
    expect(await screen.findByRole('status')).toHaveTextContent('Approved. Sharing capacity starts now.');
  });

  it('says the same person cannot give both approvals on a conflict', async () => {
    server.use(http.post('/api/bff/sharing/grants/:id/approve', () => HttpResponse.json({ code: 'conflict' }, { status: 409 })));
    const user = await open();
    await openRow(user, 'Capacity');
    await user.click(byEl('SHARE-APPROVE-BTN', card('Capacity')));
    expect(await screen.findByRole('alert')).toHaveTextContent('That could not be done. If you gave the other approval yourself, another person must give this one.');
  });

  it('says it could not be done on a failure', async () => {
    server.use(http.post('/api/bff/sharing/grants/:id/approve', () => HttpResponse.json({}, { status: 503 })));
    const user = await open();
    await openRow(user, 'Capacity');
    await user.click(byEl('SHARE-APPROVE-BTN', card('Capacity')));
    expect(await screen.findByRole('alert')).toHaveTextContent('That could not be done. Try again.');
  });

  it('asks before declining, and sends nothing until it is confirmed', async () => {
    const user = await open();
    await openRow(user, 'Capacity');
    await user.click(byEl('SHARE-DECLINE-BTN', card('Capacity')));
    const dialog = screen.getByRole('dialog', { name: 'Decline sharing capacity?' });
    expect(within(dialog).getByText('Nothing is shared. You can propose sharing again at any time.')).toBeInTheDocument();
    expect(seenNetworkAdminWrites).toEqual([]);
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(seenNetworkAdminWrites).toEqual([]);
  });

  it('declines by the grant’s handle once confirmed', async () => {
    const user = await open();
    await openRow(user, 'Capacity');
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
    await openRow(user, 'Criteria');
    await user.click(byEl('SHARE-PROPOSE-BTN', card('Criteria')));
    await waitFor(() => expect(seenNetworkAdminWrites).toHaveLength(1));
    expect(seenNetworkAdminWrites[0]).toMatchObject({ method: 'POST', path: '/api/bff/sharing/grants', query: 'networkId=net-sample', csrf: SAMPLE_CSRF, body: { kind: 'criteria' } });
    expect(await screen.findByRole('status')).toHaveTextContent('Proposed. It now waits for your approval.');
  });

  it('says there is already an open proposal when the back end refuses with a conflict', async () => {
    server.use(http.post('/api/bff/sharing/grants', () => HttpResponse.json({ code: 'conflict' }, { status: 409 })));
    const user = await open();
    await openRow(user, 'Criteria');
    await user.click(byEl('SHARE-PROPOSE-BTN', card('Criteria')));
    expect(await screen.findByRole('alert')).toHaveTextContent('There is already an open proposal for this. Reload the page.');
  });

  it('asks before ending, in the design’s words, and sends nothing until it is confirmed', async () => {
    const user = await open();
    await openRow(user, 'Service directory');
    await user.click(byEl('SHARE-END-BTN', card('Service directory')));
    const dialog = screen.getByRole('dialog', { name: 'End sharing service directory?' });
    expect(within(dialog).getByText("New data stops being shared straight away. What was already shared stays in the network history, marked with today's date.")).toBeInTheDocument();
    expect(seenNetworkAdminWrites).toEqual([]);
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(seenNetworkAdminWrites).toEqual([]);
  });

  it('ends by the grant’s handle once confirmed, and says it ended', async () => {
    const user = await open();
    await openRow(user, 'Service directory');
    await user.click(byEl('SHARE-END-BTN', card('Service directory')));
    await user.click(byEl('SHARE-END-CONFIRM-BTN'));
    await waitFor(() => expect(seenNetworkAdminWrites).toHaveLength(1));
    expect(seenNetworkAdminWrites[0]).toMatchObject({ path: '/api/bff/sharing/grants/grant-dir/end', csrf: SAMPLE_CSRF });
    expect(await screen.findByRole('status')).toHaveTextContent('Sharing ended.');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('keeps the dialog and says so when ending fails, and gives focus back when it is cancelled', async () => {
    server.use(http.post('/api/bff/sharing/grants/:id/end', () => HttpResponse.json({}, { status: 503 })));
    const user = await open();
    await openRow(user, 'Service directory');
    const opener = byEl('SHARE-END-BTN', card('Service directory'));
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

  it('shows a network that was left with its date and offers no action', async () => {
    page({ networks: [sharingNetwork({ membershipStatus: 'left', leftAt: '2026-10-28T10:00:00Z', shared: [], grants: [ownGrant('g1', 'capacity', 'lapsed', { endedAt: '2026-10-28T10:00:00Z', endReason: 'lapsed' })] })] });
    render(<SharingOverview />);
    await screen.findByText('You left this network on 28 Oct 2026.');
    expect(screen.queryByRole('button', { name: /^(Approve|Decline|End sharing|Propose sharing|Leave network|Accept version)/ })).not.toBeInTheDocument();
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

  it('is offered for an invitation not yet accepted, and shows no kind to act on until it is', async () => {
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
  it('is a disclosure, closed, that says how many changes it holds, and opens to who the data has been shared with, since when, and what ended', async () => {
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
    const user = await open();
    const history = screen.getByRole('region', { name: 'History' });
    const toggle = within(history).getByRole('button', { expanded: false });
    expect(toggle).toHaveTextContent('2 changes');
    expect(history.querySelector('[inert]')).not.toBeNull();
    await user.click(toggle);
    expect(within(history).getByRole('button', { expanded: true })).toBeInTheDocument();
    expect(within(history).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Directory: Shared with Sample Network since 4 Oct 2026',
      'Capacity: Shared with Sample Network since 5 Oct 2026. Ended on 20 Oct 2026',
    ]);
  });

  it('says No changes yet, and Nothing here yet. when opened, when nothing was ever shared', async () => {
    page({ networks: [sharingNetwork({ grants: [], shared: [] })] });
    const user = await open();
    const history = screen.getByRole('region', { name: 'History' });
    expect(within(history).getByRole('button', { expanded: false })).toHaveTextContent('No changes yet');
    await user.click(within(history).getByRole('button', { expanded: false }));
    expect(within(history).getByText('Nothing here yet.')).toBeInTheDocument();
  });
});
