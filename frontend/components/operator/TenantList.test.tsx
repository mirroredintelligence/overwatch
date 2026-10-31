import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { VIEW_TENANTS_SUPPORT } from '@/test/fixtures/operator';
import { server } from '@/test/msw/server';
import { TenantList } from './TenantList';

// The console's first page (TEN-083): the tenants. The operator sees the type, the address and the date a
// tenant was activated and can open or create one; a support person sees the name and the status and can ask
// to look into an active one. Neither sees a person.

describe('TenantList for the platform operator', () => {
  it('lists every tenant with its status in words, its type, its address and when it was activated', async () => {
    render(<TenantList role="platform-operator" />);
    const table = await screen.findByRole('table', { name: 'Tenants' });
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Name', 'Status', 'Type', 'Address', 'Activated']);
    const a = within(table).getByRole('row', { name: /Sample Area A/ });
    expect(within(a).getByText('Active')).toBeInTheDocument();
    expect(within(a).getByText('NHS trust')).toBeInTheDocument();
    expect(within(a).getByText('tenant-a.example.test')).toBeInTheDocument();
    expect(within(a).getByText('1 Oct 2026, 10:00')).toBeInTheDocument();
    const b = within(table).getByRole('row', { name: /Sample Area B/ });
    expect(within(b).getByText('Being set up')).toBeInTheDocument();
    expect(within(table).getByText('Suspended')).toBeInTheDocument();
  });

  it('links each name to the tenant’s page and offers to create one', async () => {
    render(<TenantList role="platform-operator" />);
    expect(await screen.findByRole('link', { name: 'Sample Area B' })).toHaveAttribute('href', '/operator/tenants/trust-b');
    expect(screen.getByRole('link', { name: 'Create a tenant' })).toHaveAttribute('href', '/operator/tenants/new');
  });

  it('says there are none, and says it could not load, in the right cases', async () => {
    server.use(http.get('/api/bff/platform/tenants', () => HttpResponse.json({ tenants: [] })));
    const { unmount } = render(<TenantList role="platform-operator" />);
    expect(await screen.findByText('There are no tenants yet.')).toBeInTheDocument();
    unmount();
    server.use(http.get('/api/bff/platform/tenants', () => HttpResponse.json({}, { status: 503 })));
    render(<TenantList role="platform-operator" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the tenants.');
    expect(screen.queryByText('There are no tenants yet.')).not.toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    render(<TenantList role="platform-operator" />);
    await screen.findByRole('table');
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});

describe('TenantList for a support person', () => {
  it('shows the name and the status only, with no link to a tenant’s page and no way to create one', async () => {
    server.use(http.get('/api/bff/platform/tenants', () => HttpResponse.json(VIEW_TENANTS_SUPPORT)));
    render(<TenantList role="support" />);
    const table = await screen.findByRole('table', { name: 'Tenants' });
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Name', 'Status', 'Ask to look in']);
    expect(screen.queryByRole('link', { name: 'Sample Area A' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Create a tenant' })).not.toBeInTheDocument();
    expect(document.body.textContent ?? '').not.toMatch(/example\.test|NHS trust/);
  });

  it('offers to ask for access to an active tenant only', async () => {
    server.use(http.get('/api/bff/platform/tenants', () => HttpResponse.json(VIEW_TENANTS_SUPPORT)));
    render(<TenantList role="support" />);
    await screen.findByRole('table');
    const links = screen.getAllByRole('link');
    expect(links.map((a) => [a.textContent, a.getAttribute('href')])).toEqual([['Ask for access to Sample Area A', '/operator/support/new?for=trust-a']]);
  });
});
