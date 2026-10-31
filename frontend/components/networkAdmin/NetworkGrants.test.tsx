import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { VIEW_GRANTS } from '@/test/fixtures/networkAdmin';
import { resetNetworkAdminReads, resetNetworkAdminWrites, seenNetworkAdminWrites } from '@/test/msw/handlers/networkAdmin';
import { SAMPLE_CSRF } from '@/test/msw/handlers/staff';
import { server } from '@/test/msw/server';
import { NetworkGrants } from './NetworkGrants';

// The grants of the network (TEN-080, design N1: NetworkGrants). The owner approves or declines a grant that
// waits for it; it never ends a member's grant (only the grantor does) and sees no field of a member's data.

beforeEach(() => {
  resetNetworkAdminWrites();
  resetNetworkAdminReads();
});

async function open() {
  const user = userEvent.setup();
  render(<NetworkGrants />);
  await screen.findByRole('table', { name: 'Grants' }, { timeout: 5000 });
  return user;
}
const rowOf = (id: string) => {
  const found = document.querySelector<HTMLElement>(`[data-row-ref="${id}"]`);
  if (found === null) throw new Error(`no row ${id}`);
  return found;
};

describe('the table', () => {
  it('has the design’s columns and an action column', async () => {
    await open();
    const table = byEl('NADM-GRANTS-TABLE');
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Organisation', 'Scope', 'Purpose', 'From', 'To', 'Approval', 'Version', 'Action']);
  });

  it('says for each grant the organisation, the scope in words, the purpose, the window and where the approvals stand', async () => {
    await open();
    expect(within(rowOf('grant-1')).getAllByRole('cell').map((c) => c.textContent)).toEqual([
      'Sample Area A',
      'Capacity',
      'Network capacity view',
      '4 Oct 2026',
      'No end date',
      'Waiting for the network owner',
      '1',
      expect.stringContaining('Approve'),
    ]);
    expect(within(rowOf('grant-4')).getByText('Ended')).toBeInTheDocument();
    expect(within(rowOf('grant-5')).getByText('Lapsed')).toBeInTheDocument();
    expect(within(rowOf('grant-6')).getByText('Declined')).toBeInTheDocument();
    expect(within(rowOf('grant-2')).getByText('Approved')).toBeInTheDocument();
    expect(within(rowOf('grant-3')).getByText('Waiting for the organisation and the network owner')).toBeInTheDocument();
    expect(within(rowOf('grant-7')).getByText('Waiting for the organisation')).toBeInTheDocument();
  });

  it('shows the end of a window when it has one', async () => {
    await open();
    expect(within(rowOf('grant-4')).getAllByRole('cell')[4]).toHaveTextContent('2027');
  });

  it('offers Approve and Decline on a grant that waits for the owner, and on no other', async () => {
    await open();
    for (const id of ['grant-1', 'grant-3']) {
      expect(within(rowOf(id)).getByRole('button', { name: /^Approve/ })).toBeInTheDocument();
      expect(within(rowOf(id)).getByRole('button', { name: /^Decline/ })).toBeInTheDocument();
    }
    for (const id of ['grant-2', 'grant-4', 'grant-5', 'grant-6', 'grant-7']) {
      expect(within(rowOf(id)).queryByRole('button')).not.toBeInTheDocument();
    }
  });

  it('names what each button acts on, so a screen reader hears more than "Approve"', async () => {
    await open();
    expect(within(rowOf('grant-1')).getByRole('button', { name: 'Approve Capacity grant of Sample Area A' })).toBeInTheDocument();
    expect(within(rowOf('grant-1')).getByRole('button', { name: 'Decline Capacity grant of Sample Area A' })).toBeInTheDocument();
  });

  it('offers no end button: the owner cannot end a member’s grant', async () => {
    await open();
    expect(screen.queryByRole('button', { name: /End/ })).not.toBeInTheDocument();
  });

  it('says Nothing here yet. when there is no grant, and could not load on a failure', async () => {
    server.use(http.get('/api/bff/network-admin/grants', () => HttpResponse.json({ ...VIEW_GRANTS, grants: [] })));
    render(<NetworkGrants />);
    await screen.findByRole('table', { name: 'Grants' }, { timeout: 5000 });
    expect(screen.getByText('Nothing here yet.')).toBeInTheDocument();
  });

  it('says it could not load, with no table, on a failure', async () => {
    server.use(http.get('/api/bff/network-admin/grants', () => HttpResponse.json({}, { status: 503 })));
    render(<NetworkGrants />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the grants.');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('holds no tenant id and none of the back end’s own names', async () => {
    await open();
    expect(document.body.innerHTML).not.toMatch(/trust-|tenant|account|network_id|organisation_name/i);
  });

  it('has no accessibility violation', async () => {
    await open();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});

describe('approving', () => {
  it('sends the approval by the grant’s handle with the CSRF token, and says the grant waits for the organisation when this was the first', async () => {
    const user = await open();
    await user.click(within(rowOf('grant-3')).getByRole('button', { name: /^Approve/ }));
    await waitFor(() => expect(seenNetworkAdminWrites).toHaveLength(1));
    expect(seenNetworkAdminWrites[0]).toMatchObject({ method: 'POST', path: '/api/bff/network-admin/grants/grant-3/approve', csrf: SAMPLE_CSRF });
    expect(await screen.findByRole('status')).toHaveTextContent('Your approval is recorded. The grant starts when the organisation has approved too.');
  });

  it('says the grant is in force when this was the second approval', async () => {
    server.use(http.post('/api/bff/network-admin/grants/:id/approve', () => HttpResponse.json({ effective: true })));
    const user = await open();
    await user.click(within(rowOf('grant-1')).getByRole('button', { name: /^Approve/ }));
    expect(await screen.findByRole('status')).toHaveTextContent('Approved. The grant is now in force.');
  });

  it('says the same person cannot give both approvals when the back end refuses with a conflict', async () => {
    server.use(http.post('/api/bff/network-admin/grants/:id/approve', () => HttpResponse.json({ code: 'conflict' }, { status: 409 })));
    const user = await open();
    await user.click(within(rowOf('grant-1')).getByRole('button', { name: /^Approve/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('That could not be done. If you gave the other approval yourself, another person must give this one.');
  });

  it('says it could not be done on a failure, and reloads the table after a success', async () => {
    server.use(http.post('/api/bff/network-admin/grants/:id/approve', () => HttpResponse.json({}, { status: 503 })));
    const user = await open();
    await user.click(within(rowOf('grant-1')).getByRole('button', { name: /^Approve/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The approval could not be recorded. Try again.');
  });
});

describe('declining', () => {
  it('asks first and says that a declined grant is closed, and sends nothing until it is confirmed', async () => {
    const user = await open();
    await user.click(within(rowOf('grant-1')).getByRole('button', { name: /^Decline/ }));
    const dialog = screen.getByRole('dialog', { name: 'Decline this grant?' });
    expect(within(dialog).getByText('A declined grant is closed. The organisation can propose a new one.')).toBeInTheDocument();
    expect(seenNetworkAdminWrites).toEqual([]);
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(seenNetworkAdminWrites).toEqual([]);
  });

  it('declines by the grant’s handle once confirmed', async () => {
    const user = await open();
    await user.click(within(rowOf('grant-1')).getByRole('button', { name: /^Decline/ }));
    await user.click(byEl('NADM-GRANT-DECLINE-CONFIRM-BTN'));
    await waitFor(() => expect(seenNetworkAdminWrites).toHaveLength(1));
    expect(seenNetworkAdminWrites[0]).toMatchObject({ path: '/api/bff/network-admin/grants/grant-1/decline', csrf: SAMPLE_CSRF });
    expect(await screen.findByRole('status')).toHaveTextContent('Grant declined.');
  });
});
