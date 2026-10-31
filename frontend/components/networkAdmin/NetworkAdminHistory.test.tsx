import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { VIEW_GRANTS, VIEW_OVERVIEW } from '@/test/fixtures/networkAdmin';
import { server } from '@/test/msw/server';
import { NetworkAdminHistory } from './NetworkAdminHistory';

// The read-only history of the network's membership and grant decisions, with their dates (TEN-080, design
// N1: NetworkAdminHistory). Nothing here can be changed.

async function open() {
  render(<NetworkAdminHistory />);
  await screen.findByRole('table', { name: 'Membership history' }, { timeout: 5000 });
}

describe('the history', () => {
  it('says what it is and that it is read only, in the design’s words', async () => {
    await open();
    expect(screen.getByRole('heading', { level: 1, name: 'History' })).toBeInTheDocument();
    expect(screen.getByText('Read-only history of membership and grant decisions, with their dates.')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('lists the members that left or were removed, with the date, and no one who is still in', async () => {
    await open();
    const table = screen.getByRole('table', { name: 'Membership history' });
    const rows = within(table).getAllByRole('row').slice(1).map((r) => within(r).getAllByRole('cell').map((c) => c.textContent));
    expect(rows).toEqual([
      ['Sample Area D', 'Left the network on 28 Oct 2026'],
      ['Sample Area E', 'Removed from the network on 28 Oct 2026'],
    ]);
  });

  it('lists the grants that ended, lapsed or were declined, with what happened and when it is known', async () => {
    await open();
    const table = screen.getByRole('table', { name: 'Grant history' });
    const rows = within(table).getAllByRole('row').slice(1).map((r) => within(r).getAllByRole('cell').map((c) => c.textContent));
    expect(rows).toEqual([
      ['Sample Area B', 'Criteria', 'Ended on 29 Oct 2026'],
      ['Sample Area D', 'Capacity', 'Lapsed on 29 Oct 2026'],
      ['Sample Area A', 'Criteria', 'Declined'],
    ]);
  });

  it('says Nothing here yet. for an empty history', async () => {
    server.use(
      http.get('/api/bff/network-admin', () => HttpResponse.json({ network: { ...VIEW_OVERVIEW.network, members: VIEW_OVERVIEW.network.members.slice(0, 2) } })),
      http.get('/api/bff/network-admin/grants', () => HttpResponse.json({ ...VIEW_GRANTS, grants: VIEW_GRANTS.grants.slice(0, 2) })),
    );
    render(<NetworkAdminHistory />);
    await screen.findByRole('table', { name: 'Membership history' }, { timeout: 5000 });
    expect(screen.getAllByText('Nothing here yet.')).toHaveLength(2);
  });

  it('says it could not load, with no table, when either read fails', async () => {
    server.use(http.get('/api/bff/network-admin/grants', () => HttpResponse.json({}, { status: 503 })));
    render(<NetworkAdminHistory />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the history.');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('has no accessibility violation', async () => {
    await open();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
