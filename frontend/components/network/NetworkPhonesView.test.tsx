import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { networkBffHandlers } from '@/test/msw/handlers/networkBff';
import { server } from '@/test/msw/server';
import { NetworkPhonesView } from './NetworkPhonesView';

// W43, network variant (`GET /network/{id}/phones`): the services of the network and the service line each
// organisation shared. Phoning is the only action. No reporter's number, no cover, no role and no move:
// those are an organisation's own and are never shared (DEC-136 items 1 and 5).

const view = () => render(<NetworkPhonesView ownHref="/lead/phones" />);

describe('NetworkPhonesView', () => {
  it('shows the scope header, the count and a row for each service with its organisation, category and status', async () => {
    server.use(...networkBffHandlers);
    view();
    expect(await screen.findByText('3 services from 3 organisations')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Sample Network phones' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Which board you are viewing' })).toHaveTextContent('Showing: Network, Sample Network');
    const rows = screen.getAllByRole('row').slice(1);
    expect(rows).toHaveLength(3);
    expect(within(rows[0]!).getByText('UCR West')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('Sample Area A')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('Urgent community response')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('Accepting')).toBeInTheDocument();
  });

  it('marks the viewer’s own organisation in words', async () => {
    server.use(...networkBffHandlers);
    view();
    await screen.findByText('3 services from 3 organisations');
    expect(screen.getAllByText('Your organisation')).toHaveLength(1);
  });

  it('has the service line as a link to phone, and "Phone to confirm" when none was shared', async () => {
    server.use(...networkBffHandlers);
    view();
    await screen.findByText('3 services from 3 organisations');
    const rows = screen.getAllByRole('row').slice(1);
    const link = within(rows[0]!).getByRole('link', { name: 'Phone UCR West on 01632 960010' });
    expect(link).toHaveAttribute('href', 'tel:01632960010');
    expect(within(rows[1]!).getByText('Phone to confirm')).toBeInTheDocument();
    expect(within(rows[1]!).queryByRole('link')).toBeNull();
  });

  it('shows a late service as Not updated and a paused listing as not available, never a status of its own', async () => {
    server.use(...networkBffHandlers);
    view();
    await screen.findByText('3 services from 3 organisations');
    const rows = screen.getAllByRole('row').slice(1);
    expect(within(rows[1]!).getByText('Not updated')).toBeInTheDocument();
    expect(within(rows[2]!).getByText('Not available on the network')).toBeInTheDocument();
    expect(within(rows[2]!).queryByText(/Accepting|Limited/)).toBeNull();
  });

  it('says why there is no reporter phone, move or cover here, and offers none', async () => {
    server.use(...networkBffHandlers);
    const { container } = view();
    await screen.findByText('3 services from 3 organisations');
    expect(screen.getByText('Reporters’ phones, covers and moves are your organisation’s own and are not shared across the network.')).toBeInTheDocument();
    expect(container.querySelectorAll('button')).toHaveLength(0);
    expect(container.textContent).not.toMatch(/Move|Holds \d+ services|…\d{4}/);
  });

  it('is "not available" when refused, and says it could not read the phones when the read fails', async () => {
    server.use(http.get('/api/bff/network/phones', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })), ...networkBffHandlers);
    const refused = view();
    expect(await screen.findByText('Network view not available')).toBeInTheDocument();
    refused.unmount();
    server.use(http.get('/api/bff/network/phones', () => HttpResponse.json({ code: 'exception' }, { status: 503 })));
    view();
    expect(await screen.findByText('We could not load the phones.')).toBeInTheDocument();
  });

  it('has no tenant, grant or network id and no axe violations', async () => {
    server.use(...networkBffHandlers);
    const { container } = view();
    await screen.findByText('3 services from 3 organisations');
    expect(container.innerHTML).not.toMatch(/trust-|tenant|net-sample/i);
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
