import { fireEvent, render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { networkBffHandlers } from '@/test/msw/handlers/networkBff';
import { server } from '@/test/msw/server';
import { NetworkPhonesView } from './NetworkPhonesView';

// W43, network variant (`GET /network/{id}/phones`): the services of the network and the service line each
// organisation shared. Phoning is the only action. No reporter's number, no cover, no role and no move:
// those are an organisation's own and are never shared (DEC-136 items 1 and 5). The board (NPhones) shows
// four columns: service, organisation, service line and last reported; there is no status or category column.

const view = () => render(<NetworkPhonesView ownHref="/lead/phones" />);
const COUNT = '3 services from 3 organisations';

describe('NetworkPhonesView', () => {
  it('shows the scope header, the count and a row for each service with its organisation and service line', async () => {
    server.use(...networkBffHandlers);
    view();
    expect(await screen.findByText(COUNT)).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Sample Network phones' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Which board you are viewing' })).toHaveTextContent('Showing: Network, Sample Network');
    const rows = screen.getAllByRole('row').slice(1);
    expect(rows).toHaveLength(3);
    expect(within(rows[0]!).getByText('UCR West')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('Sample Area A')).toBeInTheDocument();
    expect(within(rows[0]!).getByRole('link', { name: 'Phone UCR West on 01632 960010' })).toBeInTheDocument();
  });

  it('has the four columns the board shows, and no category or status column', async () => {
    server.use(...networkBffHandlers);
    view();
    await screen.findByText(COUNT);
    const headers = screen.getAllByRole('columnheader').map((th) => th.textContent);
    expect(headers).toEqual(['Service', 'Organisation', 'Service line', 'Last reported']);
    expect(screen.queryByText('Urgent community response')).toBeNull();
    expect(screen.queryByText('Accepting')).toBeNull();
  });

  it('marks the viewer’s own organisation in words, beside the service name', async () => {
    server.use(...networkBffHandlers);
    view();
    await screen.findByText(COUNT);
    const rows = screen.getAllByRole('row').slice(1);
    expect(screen.getAllByText('Your organisation')).toHaveLength(1);
    expect(within(rows[0]!).getByText('Your organisation')).toBeInTheDocument();
  });

  it('has the service line as a link to phone, and "Phone to confirm" when none was shared', async () => {
    server.use(...networkBffHandlers);
    view();
    await screen.findByText(COUNT);
    const rows = screen.getAllByRole('row').slice(1);
    const link = within(rows[0]!).getByRole('link', { name: 'Phone UCR West on 01632 960010' });
    expect(link).toHaveAttribute('href', 'tel:01632960010');
    expect(within(rows[1]!).getByText('Phone to confirm')).toBeInTheDocument();
    expect(within(rows[1]!).queryByRole('link')).toBeNull();
  });

  it('shows the last report in London time, and says when a service has not been updated since', async () => {
    server.use(...networkBffHandlers);
    view();
    await screen.findByText(COUNT);
    const rows = screen.getAllByRole('row').slice(1);
    expect(within(rows[0]!).getByText('23 Oct 14:08')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('23 Oct 10:02, not updated since')).toBeInTheDocument();
  });

  it('shows a paused listing as not available on the network, in the last report column', async () => {
    server.use(...networkBffHandlers);
    view();
    await screen.findByText(COUNT);
    const rows = screen.getAllByRole('row').slice(1);
    expect(within(rows[2]!).getByText('Not available on the network')).toBeInTheDocument();
    expect(within(rows[2]!).queryByRole('link')).toBeNull();
    expect(screen.queryByText(/Limited|Not updated/)).toBeNull();
  });

  it('filters the rows by organisation with the organisation chips, and the count follows the filter', async () => {
    server.use(...networkBffHandlers);
    view();
    await screen.findByText(COUNT);
    expect(screen.getByRole('button', { name: 'All organisations' })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByRole('button', { name: 'Sample Area B' }));
    expect(screen.getByRole('button', { name: 'Sample Area B' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'All organisations' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByText('1 service from 1 organisation')).toBeInTheDocument();
    const rows = screen.getAllByRole('row').slice(1);
    expect(rows).toHaveLength(1);
    expect(within(rows[0]!).getByText('Care packages north')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'All organisations' }));
    expect(screen.getAllByRole('row').slice(1)).toHaveLength(3);
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

  it('says why there is no reporter phone, move or cover here, and offers none', async () => {
    server.use(...networkBffHandlers);
    const { container } = view();
    await screen.findByText(COUNT);
    expect(screen.getByText('Phoning is the only action. Reporters’ phones, covers and moves are your organisation’s own and are not shared across the network. No patient information on this screen.')).toBeInTheDocument();
    expect(screen.getAllByRole('button')).toHaveLength(4);
    expect(container.textContent).not.toMatch(/Move|Holds \d+ services|…\d{4}/);
  });

  it('has no tenant, grant or network id and no axe violations', async () => {
    server.use(...networkBffHandlers);
    const { container } = view();
    await screen.findByText(COUNT);
    expect(container.innerHTML).not.toMatch(/trust-|tenant|net-sample/i);
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
