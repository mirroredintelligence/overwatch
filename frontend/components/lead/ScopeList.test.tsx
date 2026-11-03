import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { resetRegistrationRequests, seenRegistrationRequests } from '@/test/msw/handlers/registrations';
import type { ScopeEntry } from '@/lib/registration/types';
import { ScopeList } from './ScopeList';

beforeEach(() => resetRegistrationRequests());

const posts = () => seenRegistrationRequests.filter((request) => request.method === 'POST');

// The user-event tests here run slowly when the whole suite shares the machine; the budget is per file.
vi.setConfig({ testTimeout: 15_000 });

// One service per lifecycle state the board shows (live, paused, in review, not invited, re-verify due, ...).
const EVERY_STATE: ScopeEntry[] = [
  { serviceId: 'e1', name: 'UCR West', category: 'urgent-community-response', flag: 'in-pilot', registrationState: 'live' },
  { serviceId: 'e2', name: 'SDEC · Site 2', category: 'same-day-emergency-care', flag: 'in-pilot', registrationState: 'paused' },
  { serviceId: 'e3', name: 'Community hospital · Ward A', category: 'inpatient-beds', flag: 'in-pilot', registrationState: 'reverify' },
  { serviceId: 'e4', name: 'Community hospital · Ward B', category: 'inpatient-beds', flag: 'in-pilot', registrationState: 'in-review' },
  { serviceId: 'e5', name: 'Virtual ward', category: 'hospital-at-home-or-virtual-ward', flag: 'in-pilot', registrationState: 'invited' },
  { serviceId: 'e6', name: 'Hospital at home · East', category: 'hospital-at-home-or-virtual-ward', flag: 'in-pilot', registrationState: 'not-invited' },
  { serviceId: 'e7', name: 'Old unit', category: 'other', flag: 'out-of-scope', registrationState: 'not-approved', reason: 'Closed' },
];

// Four services across the flags, for the filter tests.
const MIXED: ScopeEntry[] = [
  { serviceId: 'm1', name: 'UCR West', category: 'urgent-community-response', flag: 'in-pilot', registrationState: 'live' },
  { serviceId: 'm2', name: 'SDEC · Site 1', category: 'same-day-emergency-care', flag: 'in-pilot', registrationState: 'not-invited' },
  { serviceId: 'm3', name: 'Reablement north', category: 'reablement', flag: 'later', registrationState: 'not-invited', reason: 'Waiting' },
  { serviceId: 'm4', name: 'Night sitting service', category: 'other', flag: 'out-of-scope', registrationState: 'not-invited', reason: 'Not ours' },
];

const useEntries = (entries: ScopeEntry[]) =>
  server.use(http.get('/api/bff/scope', () => HttpResponse.json({ entries })));

describe('ScopeList', () => {
  it('shows the three sample services, and an Invite link only on the in-pilot service not yet invited', async () => {
    const { container } = render(<ScopeList />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Services in scope' })).toBeInTheDocument();
    expect(screen.getByText('You can only invite services on this list.')).toBeInTheDocument();

    const rows = await screen.findAllByRole('listitem');
    expect(rows).toHaveLength(3);
    expect(within(rows[0]!).getByText('UCR West')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('Live')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('In review')).toBeInTheDocument();
    expect(within(rows[2]!).getByText('Not invited')).toBeInTheDocument();
    // The board shows no flag word on an in-pilot row; the filter chips carry that.
    expect(within(rows[2]!).queryByText('In pilot')).not.toBeInTheDocument();

    const invites = screen.getAllByRole('link', { name: 'Invite' });
    expect(invites).toHaveLength(1);
    expect(invites[0]).toHaveAttribute('href', '/lead/reporters/invite?service=s3');
    expect(invites[0]).toHaveAttribute('data-el', 'LEAD-SCOPE-INVITE-LINK');

    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows a state word for every lifecycle state, and the category under each name', async () => {
    useEntries(EVERY_STATE);
    render(<ScopeList />);
    const rows = await screen.findAllByRole('listitem');
    expect(rows).toHaveLength(7);
    const words = ['Live', 'Paused', 'Re-verify due', 'In review', 'Invited', 'Not invited', 'Not approved'];
    words.forEach((word, index) => expect(within(rows[index]!).getByText(word)).toBeInTheDocument());
    expect(within(rows[0]!).getByText('Urgent community response')).toBeInTheDocument();
    // A service that is not in the pilot says which flag it has.
    expect(within(rows[6]!).getByText('Out of scope')).toBeInTheDocument();
  });

  it('filters with aria-pressed buttons whose names carry the count, and keeps the Invite rule on the filtered list', async () => {
    const user = userEvent.setup();
    useEntries(MIXED);
    render(<ScopeList />);
    await screen.findAllByRole('listitem');

    const all = screen.getByRole('button', { name: 'All 4' });
    expect(all).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'In pilot 2' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: 'Later 1' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Out of scope 1' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Later 1' }));
    expect(screen.getByRole('button', { name: 'Later 1' })).toHaveAttribute('aria-pressed', 'true');
    expect(all).toHaveAttribute('aria-pressed', 'false');
    const rows = await screen.findAllByRole('listitem');
    expect(rows).toHaveLength(1);
    expect(within(rows[0]!).getByText('Reablement north')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Invite' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'In pilot 2' }));
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
    expect(screen.getAllByRole('link', { name: 'Invite' })).toHaveLength(1);
  });

  it('moves between filters with the keyboard', async () => {
    const user = userEvent.setup();
    useEntries(MIXED);
    render(<ScopeList />);
    await screen.findAllByRole('listitem');
    screen.getByRole('button', { name: 'Out of scope 1' }).focus();
    await user.keyboard('{Enter}');
    expect(screen.getByRole('button', { name: 'Out of scope 1' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
  });

  it('says why a list is empty, and still offers the add action', async () => {
    useEntries([]);
    render(<ScopeList />);
    expect(await screen.findByText('No services are in the scope list yet.')).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Services in scope' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add a service to the scope list' })).toBeInTheDocument();
  });

  it('says why a filter is empty, in words, and keeps the chip count at zero', async () => {
    const user = userEvent.setup();
    useEntries([MIXED[0]!]);
    render(<ScopeList />);
    await screen.findAllByRole('listitem');
    await user.click(screen.getByRole('button', { name: 'Later 0' }));
    expect(screen.getByText('No services are marked Later yet.')).toBeInTheDocument();
    expect(screen.queryByRole('listitem')).not.toBeInTheDocument();
  });

  it('shows loading placeholders with a spoken label until the list arrives', async () => {
    render(<ScopeList />);
    expect(screen.getByText('Loading the scope list.')).toBeInTheDocument();
    expect(await screen.findAllByRole('listitem')).toHaveLength(3);
    expect(screen.queryByText('Loading the scope list.')).not.toBeInTheDocument();
  });

  it('keeps the list absent and offers Try again when the read fails, and loads when tried again', async () => {
    const user = userEvent.setup();
    server.use(http.get('/api/bff/scope', () => HttpResponse.json({ code: 'exception' }, { status: 500 })));
    render(<ScopeList />);
    expect(await screen.findByText('The scope list could not be loaded. Try again shortly.')).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Services in scope' })).not.toBeInTheDocument();
    expect(screen.queryByText('No services are in the scope list yet.')).not.toBeInTheDocument();

    server.resetHandlers();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findAllByRole('listitem')).toHaveLength(3);
    expect(screen.queryByText('The scope list could not be loaded. Try again shortly.')).not.toBeInTheDocument();
  });

  it('opens the add panel as a labelled region, focuses the name, and closes it with Cancel', async () => {
    const user = userEvent.setup();
    render(<ScopeList />);
    await screen.findAllByRole('listitem');
    expect(screen.queryByRole('region', { name: 'Add a service to the scope list' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Add a service to the scope list' }));
    const panel = screen.getByRole('region', { name: 'Add a service to the scope list' });
    expect(panel).toBeInTheDocument();
    expect(screen.getByLabelText('Service name')).toHaveFocus();
    expect(screen.getAllByRole('listitem')).toHaveLength(3);

    await user.click(within(panel).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('region', { name: 'Add a service to the scope list' })).not.toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(3);
  });

  it('refuses a reason-less "Out of scope" entry with "Enter a reason" and sends nothing, then adds the row', async () => {
    const user = userEvent.setup();
    render(<ScopeList />);
    await screen.findAllByRole('listitem');

    await user.click(screen.getByRole('button', { name: 'Add a service to the scope list' }));
    await user.type(screen.getByLabelText('Service name'), 'Reablement team');
    const category = screen.getByRole('group', { name: 'Category' });
    await user.click(within(category).getByRole('radio', { name: 'Reablement' }));
    await user.click(screen.getByRole('radio', { name: 'Out of scope' }));
    await user.click(screen.getByRole('button', { name: 'Add to the list' }));

    expect(await screen.findByText('Enter a reason')).toBeInTheDocument();
    expect(posts()).toHaveLength(0);

    await user.type(screen.getByLabelText('Reason'), 'Not on the Dorset pathway');
    await user.click(screen.getByRole('button', { name: 'Add to the list' }));

    expect(await screen.findByText('Reablement team')).toBeInTheDocument();
    expect(posts()).toHaveLength(1);
    expect(posts()[0]?.body).toEqual({
      name: 'Reablement team',
      category: 'reablement',
      flag: 'out-of-scope',
      reason: 'Not on the Dorset pathway',
    });
    expect(posts()[0]?.idempotencyKey).toBeTruthy();
    expect(posts()[0]?.csrf).toBe('csrf-sample-token');
  });

  it('confirms an added in-pilot service in a status banner with an Invite link to it', async () => {
    const user = userEvent.setup();
    render(<ScopeList />);
    await screen.findAllByRole('listitem');

    await user.click(screen.getByRole('button', { name: 'Add a service to the scope list' }));
    await user.type(screen.getByLabelText('Service name'), 'Night sitting pilot');
    await user.click(within(screen.getByRole('group', { name: 'Category' })).getByRole('radio', { name: 'Other' }));
    await user.click(screen.getByRole('radio', { name: 'In pilot' }));
    await user.click(screen.getByRole('button', { name: 'Add to the list' }));

    const banner = await screen.findByRole('status');
    expect(within(banner).getByText('Added Night sitting pilot to the scope list.')).toBeInTheDocument();
    expect(within(banner).getByText(/It can be invited now\./)).toBeInTheDocument();
    expect(within(banner).getByRole('link', { name: 'Invite' })).toHaveAttribute(
      'href',
      '/lead/reporters/invite?service=s4',
    );
  });

  it('passes axe with the add panel open', async () => {
    const user = userEvent.setup();
    const { container } = render(<ScopeList />);
    await screen.findAllByRole('listitem');
    await user.click(screen.getByRole('button', { name: 'Add a service to the scope list' }));
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
