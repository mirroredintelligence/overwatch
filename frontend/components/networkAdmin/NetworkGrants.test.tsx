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

// The grants of the network (TEN-080, design NGrants). The owner approves or declines a grant that waits for it,
// filters the grants by where their approvals stand, and declines in place, under the table; it never ends a
// member's grant (only the grantor does) and sees no field of a member's data.

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
const shownRows = () => Array.from(document.querySelectorAll<HTMLElement>('[data-row-ref]')).map((row) => row.dataset.rowRef);
const chip = (name: string) => screen.getByRole('button', { name });

describe('the table', () => {
  it('has the design’s columns and an action column', async () => {
    await open();
    const table = byEl('NADM-GRANTS-TABLE');
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Organisation', 'Scope', 'From', 'Approval', 'Action']);
  });

  it('opens on the grants that wait for the owner, and each filter says how many it holds', async () => {
    await open();
    expect(chip('Waiting for me 2')).toHaveAttribute('aria-pressed', 'true');
    expect(chip('Waiting for the organisation 1')).toHaveAttribute('aria-pressed', 'false');
    expect(chip('Approved 1')).toHaveAttribute('aria-pressed', 'false');
    expect(chip('Declined 1')).toHaveAttribute('aria-pressed', 'false');
    expect(shownRows()).toEqual(['grant-1', 'grant-3']);
  });

  it('filters the rows by where their approvals stand, one state at a time', async () => {
    const user = await open();
    await user.click(chip('Approved 1'));
    expect(shownRows()).toEqual(['grant-2']);
    await user.click(chip('Declined 1'));
    expect(shownRows()).toEqual(['grant-6']);
    await user.click(chip('Waiting for the organisation 1'));
    expect(shownRows()).toEqual(['grant-7']);
    expect(chip('Waiting for the organisation 1')).toHaveAttribute('aria-pressed', 'true');
  });

  it('says for each grant the organisation, the scope in words, the start, where the approvals stand and the action', async () => {
    await open();
    expect(within(rowOf('grant-1')).getAllByRole('cell').map((c) => c.textContent)).toEqual([
      'Sample Area A',
      'Capacity',
      '4 Oct 2026',
      'Waiting for the network owner',
      expect.stringContaining('Approve'),
    ]);
    expect(within(rowOf('grant-3')).getByText('Waiting for the organisation and the network owner')).toBeInTheDocument();
  });

  it('shows the end of an approved grant’s window when it has one', async () => {
    server.use(
      http.get('/api/bff/network-admin/grants', () =>
        HttpResponse.json({ ...VIEW_GRANTS, grants: VIEW_GRANTS.grants.map((g) => (g.id === 'grant-2' ? { ...g, effectiveTo: '2027-10-09T10:00:00Z' } : g)) }),
      ),
    );
    const user = await open();
    await user.click(chip('Approved 1'));
    expect(within(rowOf('grant-2')).getAllByRole('cell')[4]).toHaveTextContent('to 9 Oct 2027');
    expect(within(rowOf('grant-2')).queryByRole('button')).not.toBeInTheDocument();
  });

  it('offers Approve and Decline on a grant that waits for the owner, and on no other', async () => {
    const user = await open();
    for (const id of ['grant-1', 'grant-3']) {
      expect(within(rowOf(id)).getByRole('button', { name: /^Approve/ })).toBeInTheDocument();
      expect(within(rowOf(id)).getByRole('button', { name: /^Decline/ })).toBeInTheDocument();
    }
    await user.click(chip('Approved 1'));
    expect(within(rowOf('grant-2')).queryByRole('button')).not.toBeInTheDocument();
    await user.click(chip('Declined 1'));
    expect(within(rowOf('grant-6')).queryByRole('button')).not.toBeInTheDocument();
    await user.click(chip('Waiting for the organisation 1'));
    expect(within(rowOf('grant-7')).queryByRole('button')).not.toBeInTheDocument();
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

  it('says Nothing here yet. when the chosen state holds no grant', async () => {
    server.use(http.get('/api/bff/network-admin/grants', () => HttpResponse.json({ ...VIEW_GRANTS, grants: [] })));
    render(<NetworkGrants />);
    await screen.findByRole('table', { name: 'Grants' }, { timeout: 5000 });
    expect(screen.getByText('Nothing here yet.')).toBeInTheDocument();
    expect(screen.getByText(/appears here for you to approve/)).toBeInTheDocument();
  });

  it('says it is loading the grants, with no table yet', async () => {
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.get('/api/bff/network-admin/grants', async () => {
        await held;
        return HttpResponse.json(VIEW_GRANTS);
      }),
    );
    render(<NetworkGrants />);
    expect(await screen.findByText('Loading the grants.')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    release();
    await screen.findByRole('table', { name: 'Grants' }, { timeout: 5000 });
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

describe('the side of the page', () => {
  it('says what each scope shares, what is never shared, and where a decision is recorded', async () => {
    await open();
    expect(screen.getByText('What each scope shares')).toBeInTheDocument();
    expect(screen.getByText('Status and figure of each listed service, with the time reported.')).toBeInTheDocument();
    expect(screen.getByText('Service name, category, district, opening hours and service line.')).toBeInTheDocument();
    expect(screen.getByText('The current version only: what is accepted, not accepted, ages, districts.')).toBeInTheDocument();
    expect(screen.getByText('Never shared')).toBeInTheDocument();
    expect(screen.getByText(/Anything about a patient or a person: cases, bookings/)).toBeInTheDocument();
    expect(screen.getByText(/"Network capacity view", and has dates\./)).toBeInTheDocument();
    expect(screen.getByText('Approving or declining is recorded with the date in History.')).toBeInTheDocument();
  });
});

describe('approving', () => {
  it('sends the approval by the grant’s handle with the CSRF token, and says the grant waits for the organisation when this was the first', async () => {
    const user = await open();
    await user.click(chip('Waiting for me 2'));
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

  it('says it could not be done on a failure', async () => {
    server.use(http.post('/api/bff/network-admin/grants/:id/approve', () => HttpResponse.json({}, { status: 503 })));
    const user = await open();
    await user.click(within(rowOf('grant-1')).getByRole('button', { name: /^Approve/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The approval could not be recorded. Try again.');
  });
});

describe('declining, in place under the table', () => {
  it('asks first in place, names the grant, and sends nothing until it is confirmed', async () => {
    const user = await open();
    await user.click(within(rowOf('grant-1')).getByRole('button', { name: /^Decline/ }));
    const box = screen.getByRole('region', { name: 'Decline this grant?' });
    expect(within(box).getByText('Capacity grant of Sample Area A')).toBeInTheDocument();
    expect(within(box).getByText('Sample Area A will not appear on the network board until a grant is approved.')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(seenNetworkAdminWrites).toEqual([]);
    await user.click(within(box).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('region', { name: 'Decline this grant?' })).not.toBeInTheDocument();
    expect(seenNetworkAdminWrites).toEqual([]);
  });

  it('moves focus to the question when it opens, so a keyboard user hears it', async () => {
    const user = await open();
    await user.click(within(rowOf('grant-1')).getByRole('button', { name: /^Decline/ }));
    expect(screen.getByRole('heading', { name: 'Decline this grant?' })).toHaveFocus();
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
