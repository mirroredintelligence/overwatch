import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { VIEW_GRANTS, VIEW_LISTINGS, VIEW_OVERVIEW } from '@/test/fixtures/networkAdmin';
import { server } from '@/test/msw/server';
import { NetworkAdminHistory } from './NetworkAdminHistory';

// The read-only history of the network's membership, grant and listing decisions, with their dates (TEN-080,
// design NAdminHistory). Nothing here can be changed, and nothing of what an organisation shared is shown.

async function open() {
  const user = userEvent.setup();
  render(<NetworkAdminHistory />);
  await screen.findByRole('list', { name: 'Decisions' }, { timeout: 5000 });
  return user;
}

/** Each shown decision as its date, its title and its detail, in the order the list shows them. */
function decisions(): string[][] {
  return within(screen.getByRole('list', { name: 'Decisions' }))
    .getAllByRole('listitem')
    .map((item) => [item.querySelector('time')?.textContent ?? '', item.querySelector('b')?.textContent ?? '', item.querySelector('small')?.textContent ?? '']);
}

describe('the history', () => {
  it('says what it is and that it is read only, in the design’s words', async () => {
    await open();
    expect(screen.getByRole('heading', { level: 1, name: 'History' })).toBeInTheDocument();
    expect(screen.getByText('Read-only history of membership and grant decisions, with their dates. It names roles, never people.')).toBeInTheDocument();
    expect(screen.getByText('Decisions are never edited or removed.')).toBeInTheDocument();
  });

  it('offers four filters, All first, and no other control', async () => {
    await open();
    expect(screen.getByRole('button', { name: 'All' })).toHaveAttribute('aria-pressed', 'true');
    for (const name of ['Membership', 'Grants', 'Listings']) {
      expect(screen.getByRole('button', { name })).toHaveAttribute('aria-pressed', 'false');
    }
    expect(screen.getAllByRole('button')).toHaveLength(4);
  });

  it('lists every decision with its date, newest first, and says no date for a decision made without one', async () => {
    await open();
    expect(decisions()).toHaveLength(17);
    expect(decisions()[0]).toEqual(['29 Oct 2026', 'Grant ended', 'Sample Area B · Criteria']);
    expect(decisions()[2]).toEqual(['28 Oct 2026', 'Membership ended', 'Sample Area D left the network']);
    expect(decisions().at(-1)).toEqual(['No date recorded', 'Grant declined', 'Sample Area A · Criteria']);
  });

  it('shows the membership decisions alone under Membership, with the agreement a member accepted', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Membership' }));
    expect(decisions()).toEqual([
      ['28 Oct 2026', 'Membership ended', 'Sample Area D left the network'],
      ['28 Oct 2026', 'Membership ended', 'Sample Area E was removed from the network'],
      ['2 Oct 2026', 'Membership started', 'Sample Lead Organisation accepted agreement version 1'],
      ['2 Oct 2026', 'Membership started', 'Sample Area A accepted agreement version 1'],
      ['2 Oct 2026', 'Membership started', 'Sample Area B accepted agreement version 1'],
      ['2 Oct 2026', 'Membership started', 'Sample Area D accepted agreement version 1'],
      ['2 Oct 2026', 'Membership started', 'Sample Area E accepted agreement version 1'],
    ]);
    expect(screen.getByRole('button', { name: 'Membership' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'All' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('shows the grant decisions alone under Grants: approvals, endings, and a declined grant with no date', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Grants' }));
    expect(decisions()).toEqual([
      ['29 Oct 2026', 'Grant ended', 'Sample Area B · Criteria'],
      ['29 Oct 2026', 'Grant lapsed', 'Sample Area D · Capacity'],
      ['5 Oct 2026', 'Grant approved', 'Sample Area A · Directory'],
      ['5 Oct 2026', 'Grant approved', 'Sample Area B · Criteria'],
      ['5 Oct 2026', 'Grant approved', 'Sample Area D · Capacity'],
      ['No date recorded', 'Grant declined', 'Sample Area A · Criteria'],
    ]);
  });

  it('shows the listing decisions alone under Listings, with the reason as a code word', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Listings' }));
    expect(decisions()).toEqual([
      ['7 Oct 2026', 'Listing admitted', 'Sample Area A'],
      ['7 Oct 2026', 'Listing paused', 'Sample Area B · reason: Data quality'],
      ['7 Oct 2026', 'Listing declined', 'Sample Area B · reason: Outside the area'],
      ['7 Oct 2026', 'Listing withdrawn', 'Sample Area D'],
    ]);
  });

  it('keeps a decision out of the list while it is open: pending listings and proposed grants are not history', async () => {
    await open();
    expect(decisions().some((d) => d[1] === 'Listing waiting')).toBe(false);
    expect(decisions().some((d) => d[2].includes('Sample Area C'))).toBe(false);
  });

  it('says Nothing here yet. for an empty history', async () => {
    server.use(
      http.get('/api/bff/network-admin', () => HttpResponse.json({ network: { ...VIEW_OVERVIEW.network, members: [] } })),
      http.get('/api/bff/network-admin/grants', () => HttpResponse.json({ ...VIEW_GRANTS, grants: [] })),
      http.get('/api/bff/network-admin/listings', () => HttpResponse.json({ ...VIEW_LISTINGS, listings: [] })),
    );
    render(<NetworkAdminHistory />);
    expect(await screen.findByText('Nothing here yet.')).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Decisions' })).not.toBeInTheDocument();
  });

  it('says it is loading the history, with no list yet', async () => {
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.get('/api/bff/network-admin/listings', async () => {
        await held;
        return HttpResponse.json(VIEW_LISTINGS);
      }),
    );
    render(<NetworkAdminHistory />);
    expect(await screen.findByText('Loading the history.')).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Decisions' })).not.toBeInTheDocument();
    release();
    await screen.findByRole('list', { name: 'Decisions' }, { timeout: 5000 });
  });

  it('says it could not load, with no list, when any of the three reads fails', async () => {
    server.use(http.get('/api/bff/network-admin/listings', () => HttpResponse.json({}, { status: 503 })));
    render(<NetworkAdminHistory />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the history.');
    expect(screen.queryByRole('list', { name: 'Decisions' })).not.toBeInTheDocument();
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
