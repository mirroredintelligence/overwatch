import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { VIEW_OVERVIEW } from '@/test/fixtures/networkAdmin';
import { read, resetNetworkAdminReads, resetNetworkAdminWrites, seenNetworkAdminReads, seenNetworkAdminWrites } from '@/test/msw/handlers/networkAdmin';
import { SAMPLE_CSRF } from '@/test/msw/handlers/staff';
import { server } from '@/test/msw/server';
import { NetworkMembers } from './NetworkMembers';

// The network administrator's first page (TEN-080, design N1: NetworkMembers, NetworkMemberAdd, NetworkMemberEnd,
// NetworkAgreement, NetworkHealth). The owner sees who has joined, what each organisation agreed to share and
// whether it is arriving, and never another organisation's private data.

beforeEach(() => {
  resetNetworkAdminWrites();
  resetNetworkAdminReads();
});

async function open() {
  const user = userEvent.setup();
  render(<NetworkMembers />);
  await screen.findByRole('table', { name: 'Members' });
  return user;
}
const rowOf = (name: string) => within(screen.getByRole('table', { name: 'Members' })).getByRole('row', { name: new RegExp(name) });

describe('what the page says', () => {
  it('names the page and says what the owner does and does not see, in the design’s words', async () => {
    await open();
    expect(screen.getByRole('heading', { level: 1, name: 'Network members' })).toBeInTheDocument();
    expect(screen.getByText("You see who has joined, what each organisation agreed to share and whether it is arriving. You never see another organisation's private data.")).toBeInTheDocument();
  });

  it('lists every row, closed ones too, with the status in words and the dates', async () => {
    await open();
    const table = byEl('NADM-MEMBERS-TABLE');
    expect(table.tagName).toBe('TABLE');
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Organisation', 'Status', 'Joined', 'Left', 'Agreement version accepted', 'Action']);
    expect(within(rowOf('Sample Area A')).getByText('Active')).toBeInTheDocument();
    expect(within(rowOf('Sample Area A')).getByText('2 Oct 2026')).toBeInTheDocument();
    expect(within(rowOf('Sample Area C')).getByText('Invited')).toBeInTheDocument();
    expect(within(rowOf('Sample Area D')).getByText('Left')).toBeInTheDocument();
    expect(within(rowOf('Sample Area D')).getByText('28 Oct 2026')).toBeInTheDocument();
    expect(within(rowOf('Sample Area E')).getByText('Removed')).toBeInTheDocument();
  });

  it('says in words which row is the network owner’s own', async () => {
    await open();
    expect(within(rowOf('Sample Lead Organisation')).getByText('Network owner')).toBeInTheDocument();
  });

  it('flags a member that is behind the agreement, in words, with the version that is available', async () => {
    await open();
    expect(within(rowOf('Sample Area B')).getByText('Agreement version 2 is available')).toBeInTheDocument();
    expect(within(rowOf('Sample Area A')).queryByText(/is available/)).not.toBeInTheDocument();
  });

  it('shows what each organisation’s sharing is, as states and dates, never a row of data', async () => {
    await open();
    const health = byEl('NADM-HEALTH-TABLE');
    expect(within(health).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Organisation', 'Capacity', 'Directory', 'Criteria']);
    const a = within(health).getByRole('row', { name: /Sample Area A/ });
    expect(within(a).getAllByRole('cell').map((c) => c.textContent)).toEqual(['Sample Area A', 'Sharing', 'Sharing', 'Not sharing']);
    const d = within(health).getByRole('row', { name: /Sample Area D/ });
    expect(within(d).getAllByRole('cell').map((c) => c.textContent)).toEqual(['Sample Area D', 'Ended on 28 Oct 2026', 'Not sharing', 'Not sharing']);
  });

  it('holds no tenant id, no account reference and no field the back end names', async () => {
    await open();
    expect(document.body.innerHTML).not.toMatch(/trust-|tenant|account|organisation_name|membership_id/i);
  });

  it('says Nothing here yet. for an empty table', async () => {
    server.use(http.get('/api/bff/network-admin', () => HttpResponse.json({ network: { ...VIEW_OVERVIEW.network, members: [], health: [] } })));
    render(<NetworkMembers />);
    await screen.findByRole('table', { name: 'Members' });
    expect(screen.getAllByText('Nothing here yet.')).toHaveLength(2);
  });

  it('says it could not load, with no table and no form, when the read fails', async () => {
    server.use(http.get('/api/bff/network-admin', () => HttpResponse.json({}, { status: 503 })));
    render(<NetworkMembers />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the network members.');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add an organisation' })).not.toBeInTheDocument();
  });

  it('links to the history', async () => {
    await open();
    expect(byEl('NADM-HISTORY-LINK')).toHaveAttribute('href', '/network-admin/history');
    expect(byEl('NADM-HISTORY-LINK')).toHaveTextContent('History');
  });

  it('has no accessibility violation', async () => {
    await open();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});

describe('which network', () => {
  it('reads the networks first and, for one, asks for it without naming it', async () => {
    await open();
    expect(seenNetworkAdminReads).toEqual(['/api/bff/network-admin/networks', '/api/bff/network-admin']);
  });

  it('says the one refusal, and reads nothing else, when the organisation runs no network', async () => {
    server.use(http.get('/api/bff/network-admin/networks', read({ networks: [] })));
    render(<NetworkMembers />);
    const panel = await screen.findByText('Network view not available');
    expect(byEl('NET-STATE-PANEL')).toContainElement(panel);
    expect(screen.getByText('Ask your administrator.')).toBeInTheDocument();
    expect(seenNetworkAdminReads).toEqual(['/api/bff/network-admin/networks']);
  });

  it('offers a choice when it runs more than one, reads nothing of a network until one is chosen, and then names it as the one key', async () => {
    server.use(http.get('/api/bff/network-admin/networks', read({ networks: [{ id: 'net-sample', name: 'Sample Network' }, { id: 'net-second', name: 'Second Network' }] })));
    const user = userEvent.setup();
    render(<NetworkMembers />);
    await screen.findByText('Which network?');
    expect(seenNetworkAdminReads).toEqual(['/api/bff/network-admin/networks']);
    await user.click(screen.getByRole('button', { name: 'Second Network' }));
    await screen.findByRole('table', { name: 'Members' });
    expect(seenNetworkAdminReads.at(-1)).toBe('/api/bff/network-admin?networkId=net-second');
    expect(screen.getByRole('button', { name: 'Second Network' })).toHaveAttribute('aria-pressed', 'true');
  });
});

describe('adding an organisation', () => {
  it('opens a dialog with the code field, its help and the two buttons, and returns focus when it is cancelled', async () => {
    const user = await open();
    const opener = byEl('NADM-MEMBER-ADD-BTN');
    await user.click(opener);
    const dialog = screen.getByRole('dialog', { name: 'Add an organisation' });
    expect(within(dialog).getByLabelText('Organisation code')).toBeInTheDocument();
    expect(within(dialog).getByText("The code is on the organisation's administration page.")).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Send invitation' })).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
    expect(seenNetworkAdminWrites).toEqual([]);
  });

  it('sends the code with the CSRF token and says the invitation is sent', async () => {
    const user = await open();
    await user.click(byEl('NADM-MEMBER-ADD-BTN'));
    await user.type(screen.getByLabelText('Organisation code'), 'sample-area-c');
    await user.click(screen.getByRole('button', { name: 'Send invitation' }));
    await waitFor(() => expect(seenNetworkAdminWrites).toHaveLength(1));
    expect(seenNetworkAdminWrites[0]).toMatchObject({ method: 'POST', path: '/api/bff/network-admin/members', csrf: SAMPLE_CSRF, body: { organisationCode: 'sample-area-c' } });
    expect(await screen.findByRole('status')).toHaveTextContent('Invitation sent.');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('says the one message for a code that is not a code, without sending anything', async () => {
    const user = await open();
    await user.click(byEl('NADM-MEMBER-ADD-BTN'));
    await user.type(screen.getByLabelText('Organisation code'), 'Not A Code');
    await user.click(screen.getByRole('button', { name: 'Send invitation' }));
    expect(await screen.findByText('We could not add that organisation. Check the code with them.')).toBeInTheDocument();
    expect(seenNetworkAdminWrites).toEqual([]);
  });

  it('says the same message for an unknown, an ineligible and an already invited code, so no list of organisations can be built', async () => {
    server.use(http.post('/api/bff/network-admin/members', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    const user = await open();
    await user.click(byEl('NADM-MEMBER-ADD-BTN'));
    await user.type(screen.getByLabelText('Organisation code'), 'nobody-here');
    await user.click(screen.getByRole('button', { name: 'Send invitation' }));
    expect(await screen.findByText('We could not add that organisation. Check the code with them.')).toBeInTheDocument();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('says it could not be sent, and keeps the dialog, when the back end is down', async () => {
    server.use(http.post('/api/bff/network-admin/members', () => HttpResponse.json({}, { status: 503 })));
    const user = await open();
    await user.click(byEl('NADM-MEMBER-ADD-BTN'));
    await user.type(screen.getByLabelText('Organisation code'), 'sample-area-c');
    await user.click(screen.getByRole('button', { name: 'Send invitation' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The invitation could not be sent. Try again.');
  });
});

describe('ending a membership', () => {
  it('offers it for a member that is active or invited and for no other row', async () => {
    await open();
    for (const name of ['Sample Area A', 'Sample Area B', 'Sample Area C']) {
      expect(within(rowOf(name)).getByRole('button', { name: new RegExp(`^End membership.*${name}`) })).toBeInTheDocument();
    }
    for (const name of ['Sample Lead Organisation', 'Sample Area D', 'Sample Area E']) {
      expect(within(rowOf(name)).queryByRole('button')).not.toBeInTheDocument();
    }
  });

  it('asks first, in the design’s words, and says what stays', async () => {
    const user = await open();
    await user.click(within(rowOf('Sample Area A')).getByRole('button', { name: /End membership/ }));
    const dialog = screen.getByRole('dialog', { name: 'End membership for Sample Area A?' });
    expect(within(dialog).getByText("Its sharing stops now. What it already shared stays in the history, marked with today's date.")).toBeInTheDocument();
    expect(byEl('NADM-MEMBER-END-CONFIRM-BTN')).toHaveTextContent('End membership');
    expect(seenNetworkAdminWrites).toEqual([]);
  });

  it('ends it by the membership’s handle with the CSRF token, and says it ended', async () => {
    const user = await open();
    await user.click(within(rowOf('Sample Area A')).getByRole('button', { name: /End membership/ }));
    await user.click(byEl('NADM-MEMBER-END-CONFIRM-BTN'));
    await waitFor(() => expect(seenNetworkAdminWrites).toHaveLength(1));
    expect(seenNetworkAdminWrites[0]).toMatchObject({ method: 'POST', path: '/api/bff/network-admin/members/mem-a/remove', csrf: SAMPLE_CSRF });
    expect(await screen.findByRole('status')).toHaveTextContent('Membership ended.');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('does nothing when it is cancelled, and gives focus back to the button that opened it', async () => {
    const user = await open();
    const opener = within(rowOf('Sample Area A')).getByRole('button', { name: /End membership/ });
    await user.click(opener);
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }));
    expect(seenNetworkAdminWrites).toEqual([]);
    expect(opener).toHaveFocus();
  });

  it('says it could not be ended, and keeps the dialog, on a failure', async () => {
    server.use(http.post('/api/bff/network-admin/members/:id/remove', () => HttpResponse.json({}, { status: 503 })));
    const user = await open();
    await user.click(within(rowOf('Sample Area A')).getByRole('button', { name: /End membership/ }));
    await user.click(byEl('NADM-MEMBER-END-CONFIRM-BTN'));
    expect(await screen.findByRole('alert')).toHaveTextContent('The membership could not be ended. Try again.');
  });
});

describe('the agreement', () => {
  it('shows the version in force by its reference, and says that only the reference and version are stored', async () => {
    await open();
    expect(screen.getByText('Agreement DSA-2026-1, version 2.')).toBeInTheDocument();
    expect(screen.getByText('Only the reference and version are stored, never the agreement itself.')).toBeInTheDocument();
    expect(byEl('NADM-AGREEMENT-REFERENCE-INPUT')).toBeInTheDocument();
    expect(byEl('NADM-AGREEMENT-VERSION-INPUT')).toBeInTheDocument();
  });

  it('records a new version: the reference and the version as a number, with the CSRF token', async () => {
    const user = await open();
    await user.type(screen.getByLabelText('Agreement reference'), 'DSA-2026-3');
    await user.type(screen.getByLabelText('Version'), '3');
    await user.click(byEl('NADM-AGREEMENT-RECORD-BTN'));
    await waitFor(() => expect(seenNetworkAdminWrites).toHaveLength(1));
    expect(seenNetworkAdminWrites[0]).toMatchObject({ path: '/api/bff/network-admin/agreement', csrf: SAMPLE_CSRF, body: { reference: 'DSA-2026-3', version: 3 } });
    expect(await screen.findByRole('status')).toHaveTextContent('Agreement version 3 recorded. Members show as behind until they accept it.');
  });

  it.each([
    ['a reference with a space', 'DSA 2026', '3', 'Enter the reference as it is in your document system, with letters, digits, dots, slashes and hyphens only.'],
    ['no reference', '', '3', 'Enter the reference as it is in your document system, with letters, digits, dots, slashes and hyphens only.'],
    ['a version that is not a whole number', 'DSA-2026-3', '2.5', 'Enter the version as a whole number, one or more.'],
    ['no version', 'DSA-2026-3', '', 'Enter the version as a whole number, one or more.'],
  ])('says in words what is wrong with %s, and sends nothing', async (_name, reference, version, message) => {
    const user = await open();
    if (reference !== '') await user.type(screen.getByLabelText('Agreement reference'), reference);
    if (version !== '') await user.type(screen.getByLabelText('Version'), version);
    await user.click(byEl('NADM-AGREEMENT-RECORD-BTN'));
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(seenNetworkAdminWrites).toEqual([]);
  });
});
