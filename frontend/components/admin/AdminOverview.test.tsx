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
