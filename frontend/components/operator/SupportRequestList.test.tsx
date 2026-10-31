import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { VIEW_TENANTS_SUPPORT } from '@/test/fixtures/operator';
import { server } from '@/test/msw/server';
import { SupportRequestList } from './SupportRequestList';

// A support person's own requests (TEN-083, DEC-1003): the tenant by its name, where each stands in words
// from the support person's side, and the way to ask for another. Only their own: the back end lists no one
// else's.

function serveTenants() {
  server.use(http.get('/api/bff/platform/tenants', () => HttpResponse.json(VIEW_TENANTS_SUPPORT)));
}

describe('SupportRequestList', () => {
  it('lists the requests with the tenant’s name, the state in words and the reason', async () => {
    serveTenants();
    render(<SupportRequestList />);
    const first = await screen.findByRole('article', { name: 'Request tkt-1' });
    expect(within(first).getByText('Sample Area A')).toBeInTheDocument();
    expect(within(first).getByText('Waiting for the tenant’s administrator')).toBeInTheDocument();
    expect(within(first).getByText('The board shows a service twice')).toBeInTheDocument();
    expect(within(first).getByRole('link', { name: 'Open request tkt-1' })).toHaveAttribute('href', '/operator/support/tickets/tkt-1');
    expect(within(screen.getByRole('article', { name: 'Request tkt-2' })).getByText('Approved. Ask the administrator for the code.')).toBeInTheDocument();
    expect(within(screen.getByRole('article', { name: 'Request tkt-3' })).getByText('Open now')).toBeInTheDocument();
  });

  it('names a tenant it has no name for by its id, and links to asking for another', async () => {
    server.use(http.get('/api/bff/platform/tenants', () => HttpResponse.json({ tenants: [] })));
    render(<SupportRequestList />);
    const first = await screen.findByRole('article', { name: 'Request tkt-1' });
    expect(within(first).getByText('trust-a')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Ask for access' })).toHaveAttribute('href', '/operator/support/new');
  });

  it('says there are none, and says it could not load, in the right cases', async () => {
    serveTenants();
    server.use(http.get('/api/bff/platform/support-tickets', () => HttpResponse.json({ tickets: [] })));
    const { unmount } = render(<SupportRequestList />);
    expect(await screen.findByText('You have not asked for access to any tenant.')).toBeInTheDocument();
    unmount();
    server.use(http.get('/api/bff/platform/support-tickets', () => HttpResponse.json({}, { status: 503 })));
    render(<SupportRequestList />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load your requests.');
  });

  it('has no axe violations', async () => {
    serveTenants();
    render(<SupportRequestList />);
    await screen.findByRole('article', { name: 'Request tkt-1' });
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
