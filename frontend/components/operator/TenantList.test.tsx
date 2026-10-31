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

  it('turns an empty list into a next step: the operator is offered the first tenant, with what comes after it', async () => {
    server.use(http.get('/api/bff/platform/tenants', () => HttpResponse.json({ tenants: [] })));
    const { container } = render(<TenantList role="platform-operator" />);
    const empty = await screen.findByRole('region', { name: 'There are no tenants yet.' });
    expect(within(empty).getByText(/give it an address, bind its directory/)).toBeInTheDocument();
    expect(within(empty).getByRole('link', { name: 'Create the first tenant' })).toHaveAttribute('href', '/operator/tenants/new');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows the way to create a tenant beside the heading once there are tenants, and no empty state', async () => {
    render(<TenantList role="platform-operator" />);
    await screen.findByRole('table');
    expect(screen.getAllByRole('link', { name: 'Create a tenant' })).toHaveLength(1);
    expect(screen.queryByRole('region', { name: 'There are no tenants yet.' })).not.toBeInTheDocument();
  });

  it('labels every cell by its column, so the table can read as cards on a phone', async () => {
    render(<TenantList role="platform-operator" />);
    const table = await screen.findByRole('table', { name: 'Tenants' });
    const row = within(table).getByRole('row', { name: /Sample Area A/ });
    expect(within(row).getAllByRole('cell').map((c) => c.getAttribute('data-label'))).toEqual(['Status', 'Type', 'Address', 'Activated']);
  });

  it('has no axe violations', async () => {
    render(<TenantList role="platform-operator" />);
    await screen.findByRole('table');
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});

describe('TenantList for a support person', () => {
  it('has an empty state with no button to create one: a support person asks a platform operator', async () => {
    server.use(http.get('/api/bff/platform/tenants', () => HttpResponse.json({ tenants: [] })));
    render(<TenantList role="support" />);
    const empty = await screen.findByRole('region', { name: 'There are no tenants yet.' });
    expect(within(empty).queryByRole('link')).not.toBeInTheDocument();
    expect(within(empty).getByText(/When a platform operator creates one/)).toBeInTheDocument();
  });

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
