import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { AdminOverview } from './AdminOverview';

// The administrator's first page (TEN-076): who the organisation is, which configuration is in force, and
// the way to each page of the administration. It shows no tenant id, no secret and nobody's reference.

describe('AdminOverview', () => {
  it('shows the organisation as the back end holds it', async () => {
    render(<AdminOverview />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Administration' })).toBeInTheDocument();
    const about = screen.getByRole('region', { name: 'Your organisation' });
    for (const text of ['Sample Area A', 'Sample Area A Organisation', 'RXX01', 'Europe/London', 'active', 'tenant-a.example.test']) {
      expect(within(about).getByText(text)).toBeInTheDocument();
    }
  });

  it('says which version of the settings is in force and since when, with the way to it', async () => {
    render(<AdminOverview />);
    const config = await screen.findByRole('region', { name: 'Settings in force' });
    expect(within(config).getByText('Version 2, in force since 21 Oct 2026, 10:00.')).toBeInTheDocument();
    expect(within(config).getByRole('link', { name: 'Settings and versions' })).toHaveAttribute('href', '/admin/config');
  });

  it('says so, and does not invent a version, when no settings are in force yet', async () => {
    server.use(http.get('/api/bff/tenant/overview', async () => HttpResponse.json({ ...(await import('@/test/fixtures/tenantAdmin')).VIEW_OVERVIEW, config: null })));
    render(<AdminOverview />);
    expect(await screen.findByText('No settings are in force yet.')).toBeInTheDocument();
  });

  it('links to every page of the administration', async () => {
    render(<AdminOverview />);
    const nav = await screen.findByRole('navigation', { name: 'Administration pages' });
    const links = within(nav).getAllByRole('link').map((a) => [a.textContent, a.getAttribute('href')]);
    expect(links).toEqual([
      ['Settings and versions', '/admin/config'],
      ['Users and roles', '/admin/users'],
      ['Contacts', '/admin/contacts'],
      ['Email sender', '/admin/email'],
      ['Data retention', '/admin/retention'],
      ['Who has accessed your organisation', '/admin/access'],
      ['Support requests', '/admin/support'],
      ['Sharing with the network', '/admin/sharing'],
    ]);
  });

  it('says who can sign in: the groups in use, in role words, and nobody by name', async () => {
    render(<AdminOverview />);
    const people = await screen.findByRole('region', { name: 'People and groups' });
    expect(within(people).getByText('1 group is in use:')).toBeInTheDocument();
    expect(within(people).getByText('Shift lead')).toBeInTheDocument();
  });

  it('lists what is left to do, with the page that does it, and says so plainly when nothing is mapped', async () => {
    const { VIEW_OVERVIEW } = await import('@/test/fixtures/tenantAdmin');
    server.use(http.get('/api/bff/tenant/overview', () => HttpResponse.json({ ...VIEW_OVERVIEW, bindings: [], mappings: [], contacts: [] })));
    render(<AdminOverview />);
    const setup = await screen.findByRole('region', { name: 'Finish setting up' });
    expect(within(setup).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'To doBind the directory your people sign in with. Users and roles',
      'To doMap a group to a role, so people can sign in. Users and roles',
      'To doAdd the coordination phone. Contacts',
    ]);
    expect(within(setup).getAllByRole('link', { name: 'Users and roles' })[0]).toHaveAttribute('href', '/admin/users');
    expect(screen.getByText('No group is mapped yet. Until one is, nobody can sign in except you.')).toBeInTheDocument();
  });

  it('shows a waiting directory as waiting for the platform operator, not as a task for the administrator', async () => {
    const { VIEW_OVERVIEW, DIRECTORY } = await import('@/test/fixtures/tenantAdmin');
    server.use(http.get('/api/bff/tenant/overview', () => HttpResponse.json({ ...VIEW_OVERVIEW, bindings: [{ directoryId: DIRECTORY, status: 'pending', verifiedAt: null }] })));
    render(<AdminOverview />);
    const setup = await screen.findByRole('region', { name: 'Finish setting up' });
    expect(within(setup).getByText('Waiting')).toBeInTheDocument();
    expect(within(setup).getByText('Your directory is waiting for the platform operator to verify it.')).toBeInTheDocument();
  });

  it('shows no setup list once everything is done', async () => {
    render(<AdminOverview />);
    await screen.findByRole('region', { name: 'Your organisation' });
    expect(screen.queryByRole('region', { name: 'Finish setting up' })).not.toBeInTheDocument();
  });

  it('shows no tenant id, no secret and no reference of a person', async () => {
    render(<AdminOverview />);
    await screen.findByText('Sample Area A');
    expect(document.body.textContent ?? '').not.toMatch(/trust-a|stf-|ops-|secret/i);
  });

  it('says it could not load, and shows no half page, when the read fails', async () => {
    server.use(http.get('/api/bff/tenant/overview', () => HttpResponse.json({ code: 'exception' }, { status: 503 })));
    render(<AdminOverview />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load your organisation.');
    expect(screen.queryByRole('region', { name: 'Your organisation' })).not.toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(<AdminOverview />);
    await screen.findByText('Sample Area A');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
