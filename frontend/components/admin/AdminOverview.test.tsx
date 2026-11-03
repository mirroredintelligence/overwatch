import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { DIRECTORY, VIEW_OVERVIEW, VIEW_TICKETS, VIEW_VERSIONS } from '@/test/fixtures/tenantAdmin';
import { server } from '@/test/msw/server';
import { AdminOverview } from './AdminOverview';

// The administrator's first page (TEN-076), on board A1: what needs the person, the organisation's facts, the
// people and the settings in force. It shows no tenant id, no secret and nobody's name.

// The version 3 of the fixture, written by someone else, so that it needs this person's approval.
const VERSIONS_BY_OTHERS = {
  versions: VIEW_VERSIONS.versions.map((v) => (v.version === 3 ? { ...v, authoredByYou: false } : v)),
};

describe('AdminOverview', () => {
  it('shows the organisation as the back end holds it, in the right column', async () => {
    render(<AdminOverview />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Administration' })).toBeInTheDocument();
    const about = screen.getByRole('complementary', { name: 'Your organisation' });
    for (const text of ['Sample Area A', 'RXX01', 'Europe/London', 'active', 'tenant-a.example.test']) {
      expect(within(about).getByText(text)).toBeInTheDocument();
    }
    expect(within(about).queryByText('Sample Area A Organisation')).not.toBeInTheDocument();
  });

  it('lists what needs this person, each row with its state in words and its one action', async () => {
    server.use(http.get('/api/bff/tenant/config/versions', () => HttpResponse.json(VERSIONS_BY_OTHERS)));
    render(<AdminOverview />);
    const needs = await screen.findByRole('region', { name: 'What needs you' });
    expect(within(needs).getByText('3 things')).toBeInTheDocument();

    expect(within(needs).getByText('Waiting for you')).toBeInTheDocument();
    expect(within(needs).getByText('A support person is asking to look into your organisation')).toBeInTheDocument();
    expect(within(needs).getByText('Approve or refuse. Nothing opens until you give them the code.')).toBeInTheDocument();
    expect(within(needs).getByRole('link', { name: 'Review request' })).toHaveAttribute('href', '/admin/support');

    expect(within(needs).getByText('Approve version 3 of your settings')).toBeInTheDocument();
    expect(within(needs).getByText('It changes a clinical setting, so it needs 2 approvals from other people. 0 given.')).toBeInTheDocument();
    expect(within(needs).getByRole('link', { name: 'Open version' })).toHaveAttribute('href', '/admin/config/3');

    expect(within(needs).getByText('Add the clinical safety officer')).toBeInTheDocument();
    expect(within(needs).getByRole('link', { name: 'Add officer' })).toHaveAttribute('href', '/admin/contacts');
  });

  it('does not ask this person to approve a version they wrote, or one they have already approved', async () => {
    render(<AdminOverview />);
    const needs = await screen.findByRole('region', { name: 'What needs you' });
    expect(within(needs).queryByText('Approve version 3 of your settings')).not.toBeInTheDocument();
    expect(within(needs).getByText('2 things')).toBeInTheDocument();
  });

  it('asks for the coordination phone and the safety officer when they are missing', async () => {
    server.use(http.get('/api/bff/tenant/overview', () => HttpResponse.json({ ...VIEW_OVERVIEW, contacts: [] })));
    render(<AdminOverview />);
    const needs = await screen.findByRole('region', { name: 'What needs you' });
    expect(within(needs).getByText('Add the coordination phone')).toBeInTheDocument();
    expect(within(needs).getByText('Staff see it on any page that says who to phone.')).toBeInTheDocument();
    expect(within(needs).getByRole('link', { name: 'Add phone' })).toHaveAttribute('href', '/admin/contacts');
    expect(within(needs).getByRole('link', { name: 'Add officer' })).toHaveAttribute('href', '/admin/contacts');
  });

  it('asks for a directory and a group when none is bound or mapped, and says so when a directory waits for the operator', async () => {
    server.use(http.get('/api/bff/tenant/overview', () => HttpResponse.json({ ...VIEW_OVERVIEW, bindings: [], mappings: [] })));
    const { unmount } = render(<AdminOverview />);
    const needs = await screen.findByRole('region', { name: 'What needs you' });
    expect(within(needs).getByText('Bind the directory your people sign in with')).toBeInTheDocument();
    expect(within(needs).getByRole('link', { name: 'Bind directory' })).toHaveAttribute('href', '/admin/users');
    expect(within(needs).getByText('Map a group to a role, so people can sign in')).toBeInTheDocument();
    expect(within(needs).getByRole('link', { name: 'Map group' })).toHaveAttribute('href', '/admin/users');
    unmount();

    server.use(http.get('/api/bff/tenant/overview', () => HttpResponse.json({ ...VIEW_OVERVIEW, bindings: [{ directoryId: DIRECTORY, status: 'pending', verifiedAt: null }] })));
    render(<AdminOverview />);
    const waiting = await screen.findByRole('region', { name: 'What needs you' });
    expect(within(waiting).getByText('Your directory is waiting for the platform operator to verify it')).toBeInTheDocument();
    expect(within(waiting).getByText('Waiting')).toBeInTheDocument();
    expect(within(waiting).queryByRole('link', { name: 'Bind directory' })).not.toBeInTheDocument();
  });

  it('keeps the steps already done in a list that opens on request', async () => {
    const user = userEvent.setup();
    render(<AdminOverview />);
    const toggle = await screen.findByRole('button', { name: /Done · 3 steps/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('A directory is bound and verified.')).toBeInTheDocument();
    expect(screen.getByText('A group is mapped to a role.')).toBeInTheDocument();
    expect(screen.getByText('The coordination phone is recorded.')).toBeInTheDocument();
  });

  it('says nothing needs the person when everything is done, and shows no task', async () => {
    server.use(
      http.get('/api/bff/tenant/overview', () =>
        HttpResponse.json({ ...VIEW_OVERVIEW, contacts: [...VIEW_OVERVIEW.contacts, { kind: 'clinical-safety-officer', label: 'CSO', value: 'Sample officer' }] }),
      ),
      http.get('/api/bff/tenant/support-tickets', () => HttpResponse.json({ tickets: VIEW_TICKETS.tickets.map((t) => ({ ...t, state: 'opened' })) })),
      http.get('/api/bff/tenant/config/versions', () => HttpResponse.json({ versions: [] })),
    );
    render(<AdminOverview />);
    const needs = await screen.findByRole('region', { name: 'What needs you' });
    expect(within(needs).getByText('Nothing needs you. The list comes back when something does.')).toBeInTheDocument();
    expect(within(needs).queryByRole('link', { name: /Review request|Open version|Add phone|Add officer/ })).not.toBeInTheDocument();
    expect(within(needs).queryByText(/things?$/)).not.toBeInTheDocument();
  });

  it('shows three skeleton rows while it loads, and no half page', async () => {
    server.use(http.get('/api/bff/tenant/overview', async () => new Promise(() => {})));
    render(<AdminOverview />);
    expect(screen.getByText('Loading your organisation.')).toBeInTheDocument();
    expect(screen.queryByRole('complementary', { name: 'Your organisation' })).not.toBeInTheDocument();
  });

  it('says it could not load, that nothing has changed, and offers to try again', async () => {
    const user = userEvent.setup();
    server.use(http.get('/api/bff/tenant/overview', () => HttpResponse.json({ code: 'exception' }, { status: 503 })));
    render(<AdminOverview />);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('We could not load your organisation.');
    expect(alert).toHaveTextContent('Nothing has changed.');
    expect(screen.queryByRole('complementary', { name: 'Your organisation' })).not.toBeInTheDocument();

    server.resetHandlers();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('complementary', { name: 'Your organisation' })).toBeInTheDocument();
  });

  it('says which version of the settings is in force and since when', async () => {
    render(<AdminOverview />);
    const config = await screen.findByRole('region', { name: 'Settings in force' });
    expect(within(config).getByText('Version 2, since 21 Oct 2026')).toBeInTheDocument();
  });

  it('says so, and does not invent a version, when no settings are in force yet', async () => {
    server.use(http.get('/api/bff/tenant/overview', () => HttpResponse.json({ ...VIEW_OVERVIEW, config: null })));
    render(<AdminOverview />);
    expect(await screen.findByText('No settings are in force yet.')).toBeInTheDocument();
  });

  it('says how many roles and people the groups give, with nobody named', async () => {
    render(<AdminOverview />);
    const people = await screen.findByRole('region', { name: 'People and roles' });
    expect(within(people).getByText('2 roles in use · 2 people')).toBeInTheDocument();
    expect(within(people).getByRole('link', { name: 'Open people and roles' })).toHaveAttribute('href', '/admin/users');
    expect(people.textContent ?? '').not.toMatch(/Jane|Sam Second|Sample/);
  });

  it('says there are no roles yet when no group is mapped', async () => {
    server.use(http.get('/api/bff/tenant/groups', () => HttpResponse.json({ setUp: true, groups: [] })));
    render(<AdminOverview />);
    const people = await screen.findByRole('region', { name: 'People and roles' });
    expect(within(people).getByText('0 roles in use · 0 people')).toBeInTheDocument();
  });

  it('says the sharing rule in the board words', async () => {
    render(<AdminOverview />);
    const sharing = await screen.findByRole('region', { name: 'Sharing with the network' });
    expect(within(sharing).getByText('You share only what you agree to.')).toBeInTheDocument();
  });

  it('says the organisation is being set up, and that the platform team goes live, while it is provisioning', async () => {
    server.use(http.get('/api/bff/tenant/overview', () => HttpResponse.json({ ...VIEW_OVERVIEW, tenant: { ...VIEW_OVERVIEW.tenant, status: 'provisioning' } })));
    render(<AdminOverview />);
    const about = await screen.findByRole('complementary', { name: 'Your organisation' });
    expect(within(about).getByText('Being set up')).toBeInTheDocument();
    expect(within(about).getByText('Going live is done by the platform team once everything here is finished.')).toBeInTheDocument();
  });

  it('shows no tenant id, no secret and no reference of a person', async () => {
    render(<AdminOverview />);
    await screen.findByText('Sample Area A');
    expect(document.body.textContent ?? '').not.toMatch(/trust-a|stf-|ops-|secret/i);
  });

  it('has no axe violations', async () => {
    const { container } = render(<AdminOverview />);
    await screen.findByText('Sample Area A');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
