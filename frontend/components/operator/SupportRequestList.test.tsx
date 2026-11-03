import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { VIEW_TENANTS_SUPPORT } from '@/test/fixtures/operator';
import { server } from '@/test/msw/server';
import { SupportRequestList } from './SupportRequestList';

// A support person's own requests (TEN-083, DEC-1003, board O5): the requests on the left, each by its number and
// the organisation's name, where it stands as shape plus word, and the way to ask for another. The open request
// (or the sheet that asks) is passed in and sits on the right. Only their own: the back end lists no one else's.

function serveTenants() {
  server.use(http.get('/api/bff/platform/tenants', () => HttpResponse.json(VIEW_TENANTS_SUPPORT)));
}

describe('SupportRequestList', () => {
  it('names the page, says one organisation at a time, and says nothing opens until the administrator approves', async () => {
    serveTenants();
    render(<SupportRequestList />);
    expect(screen.getByRole('heading', { level: 1, name: 'Support requests' })).toBeInTheDocument();
    expect(screen.getByText('You can ask to look into one organisation at a time.')).toBeInTheDocument();
    expect(screen.getByText('Nothing opens until the organisation’s administrator approves and gives you a code.')).toBeInTheDocument();
    await screen.findByRole('article', { name: 'Request tkt-1' });
  });

  it('lists each request by number and the organisation’s name, with a short state word and the reason', async () => {
    serveTenants();
    render(<SupportRequestList />);
    const first = await screen.findByRole('article', { name: 'Request tkt-1' });
    expect(within(first).getByText('tkt-1')).toBeInTheDocument();
    expect(within(first).getByText('Sample Area A')).toBeInTheDocument();
    expect(within(first).getByText('Waiting')).toBeInTheDocument();
    expect(within(first).getByText(/The board shows a service twice/)).toBeInTheDocument();
    expect(within(first).getByRole('link', { name: 'Open request tkt-1' })).toHaveAttribute('href', '/operator/support/tickets/tkt-1');
    expect(within(screen.getByRole('article', { name: 'Request tkt-2' })).getByText('Approved')).toBeInTheDocument();
    expect(within(screen.getByRole('article', { name: 'Request tkt-3' })).getByText('Open now')).toBeInTheDocument();
  });

  it('marks the open request as the current one', async () => {
    serveTenants();
    render(<SupportRequestList selectedId="tkt-2" />);
    const second = await screen.findByRole('article', { name: 'Request tkt-2' });
    expect(within(second).getByRole('link', { name: 'Open request tkt-2' })).toHaveAttribute('aria-current', 'page');
    expect(within(screen.getByRole('article', { name: 'Request tkt-1' })).getByRole('link')).not.toHaveAttribute('aria-current');
  });

  it('names an organisation it has no name for by its id, and links to asking for another', async () => {
    server.use(http.get('/api/bff/platform/tenants', () => HttpResponse.json({ tenants: [] })));
    render(<SupportRequestList />);
    const first = await screen.findByRole('article', { name: 'Request tkt-1' });
    expect(within(first).getByText('trust-a')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Ask for access' })).toHaveAttribute('href', '/operator/support/new');
  });

  it('shows what it is given on the right: the open request, or a line that says to choose one', async () => {
    serveTenants();
    const { unmount } = render(<SupportRequestList />);
    expect(screen.getByText('Choose a request to see where it stands.')).toBeInTheDocument();
    await screen.findByRole('article', { name: 'Request tkt-1' });
    unmount();
    render(
      <SupportRequestList selectedId="tkt-1">
        <p>The open request</p>
      </SupportRequestList>,
    );
    expect(screen.getByText('The open request')).toBeInTheDocument();
    expect(screen.queryByText('Choose a request to see where it stands.')).not.toBeInTheDocument();
    await screen.findByRole('article', { name: 'Request tkt-1' });
  });

  it('keeps the list out of reach while the sheet is open', async () => {
    serveTenants();
    render(<SupportRequestList sheet={<section aria-label="Ask for access">the sheet</section>} />);
    expect(screen.getByRole('region', { name: 'Ask for access' })).toBeInTheDocument();
    expect(document.querySelector('[inert]')).not.toBeNull();
    expect(document.querySelector('[inert]')).not.toContainElement(screen.getByRole('region', { name: 'Ask for access' }));
    await waitFor(() => expect(document.querySelector('[inert] article')).not.toBeNull());
  });

  it('says there are none while loading ends, and offers another try when it could not load', async () => {
    serveTenants();
    server.use(http.get('/api/bff/platform/support-tickets', () => HttpResponse.json({ tickets: [] })));
    const { unmount } = render(<SupportRequestList />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading your requests.');
    expect(await screen.findByText('You have not asked for access to any organisation.')).toBeInTheDocument();
    unmount();
    server.use(http.get('/api/bff/platform/support-tickets', () => HttpResponse.json({}, { status: 503 })));
    render(<SupportRequestList />);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('We could not load your requests.');
    server.use(http.get('/api/bff/platform/support-tickets', () => HttpResponse.json({ tickets: [] })));
    await userEvent.setup().click(within(alert).getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('You have not asked for access to any organisation.')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    serveTenants();
    render(<SupportRequestList />);
    await screen.findByRole('article', { name: 'Request tkt-1' });
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
