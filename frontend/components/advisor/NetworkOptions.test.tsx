import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { OPTIONS_BODY } from '@/test/fixtures/network';
import { networkBffHandlers, resetNetworkBff, seenNetworkBff } from '@/test/msw/handlers/networkBff';
import { server } from '@/test/msw/server';
import { parseNetworkOptions } from '@/lib/network/parse';
import { NetworkOptions } from './NetworkOptions';

// WB11 (docs/design/network-ui.md section 9, "Options and not-suitable list"): the services of the other
// organisations in the network that meet the case's criteria, read only, labelled by organisation, with
// "Sorted by travel time. Not ranked." and none of Request booking, I phoned, They declined or a clinical
// escalation on a row: the only thing to do with a row is to phone the service.

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

beforeEach(() => {
  resetNetworkBff();
  server.use(...networkBffHandlers);
});

const optionsReads = () => seenNetworkBff.filter((read) => read.path === '/api/bff/network/options');

describe('NetworkOptions', () => {
  it('says which board it is, with the switch back to the case’s own options, and says it is read only', async () => {
    render(<NetworkOptions caseId="4821" />);
    await screen.findByText('2 services in Sample Network meet this patient’s criteria');
    const header = screen.getByRole('region', { name: 'Which board you are viewing' });
    expect(header).toHaveTextContent('Showing: Network, Sample Network');
    expect(within(header).getByRole('link', { name: 'Our organisation' })).toHaveAttribute('href', '/advisor/case/4821/options');
    expect(within(header).getByRole('link', { name: 'Network' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByText('Read only')).toBeInTheDocument();
    expect(screen.getByText('You cannot book or change these services from here. Phone the service to check.')).toBeInTheDocument();
  });

  it('lists the services in the order the back end sent them, each with its organisation, status, figure, age and why it fits, and says it is not ranked', async () => {
    render(<NetworkOptions caseId="4821" />);
    await screen.findByText('Sorted by travel time. Not ranked.');
    const cards = screen.getAllByRole('article');
    expect(cards.map((card) => within(card).getByRole('heading', { level: 3 }).textContent)).toEqual(['Virtual ward frailty', 'Reablement south']);
    const first = cards[0] as HTMLElement;
    expect(within(first).getByText('Sample Area B')).toBeInTheDocument();
    expect(within(first).getByText('Limited')).toBeInTheDocument();
    expect(within(first).getByText('Response or travel: about 12 to 24 min')).toBeInTheDocument();
    expect(within(first).getByText('Data age: 20 min ago')).toBeInTheDocument();
    expect(within(first).getByText('Covers this postcode')).toBeInTheDocument();
    expect(within(first).getByText('Limited: phone to confirm')).toBeInTheDocument();
    expect(screen.queryByText(/best|rank(?!ed)|score/i)).toBeNull();
  });

  it('has the service line to phone on a row, "No number shared" where there is none, and nothing to book, phone-record, decline or escalate', async () => {
    render(<NetworkOptions caseId="4821" />);
    await screen.findAllByRole('article');
    const [first, second] = screen.getAllByRole('article') as [HTMLElement, HTMLElement];
    expect(within(first).getByRole('link', { name: 'Phone Virtual ward frailty on 01632 960010' })).toHaveAttribute('href', 'tel:01632960010');
    expect(within(second).getByText('No number shared')).toBeInTheDocument();
    for (const name of [/Request booking/, /I phoned/, /They declined/, /Ask clinical/, /Booking/]) {
      expect(screen.queryAllByRole('button', { name }).filter((button) => button.closest('article'))).toHaveLength(0);
    }
    for (const card of [first, second]) expect(within(card).getByRole('button', { name: 'Criteria' })).toBeInTheDocument();
  });

  it('lists the services that are not suitable, with the organisation and the reason', async () => {
    const user = userEvent.setup();
    render(<NetworkOptions caseId="4821" />);
    await user.click(await screen.findByRole('button', { name: '2 services not suitable, and why' }));
    expect(screen.getByText('Care packages north (Sample Area B): not updated for 4 hrs. Phone to confirm.')).toBeInTheDocument();
    expect(screen.getByText('Paused listing (Sample Area D): not available on the network. Phone to confirm.')).toBeInTheDocument();
  });

  it('reads the options once, for the one network, with the case reference and nothing else of the case', async () => {
    render(<NetworkOptions caseId="4821" />);
    await screen.findAllByRole('article');
    expect(optionsReads()).toEqual([{ path: '/api/bff/network/options', query: 'networkId=net-sample&case=4821' }]);
  });

  it('opens the criteria of the service, read only, from the row’s Criteria button', async () => {
    const user = userEvent.setup();
    render(<NetworkOptions caseId="4821" />);
    const [first] = (await screen.findAllByRole('article')) as [HTMLElement];
    await user.click(within(first).getByRole('button', { name: 'Criteria' }));
    const dialog = await screen.findByRole('dialog', { name: 'Criteria: Virtual ward frailty' });
    expect(dialog).toHaveAttribute('data-el', 'ADV-CRIT-DIALOG');
    expect(within(dialog).queryByRole('link', { name: /Report a problem/ })).toBeNull();
  });

  it('says no service in the network meets the criteria, and to phone, when there is none', async () => {
    server.use(http.get('/api/bff/network/options', () => HttpResponse.json({ ...parseNetworkOptions(OPTIONS_BODY, 'backend'), options: [] })));
    render(<NetworkOptions caseId="4821" />);
    expect(await screen.findByText('No service in Sample Network meets this patient’s criteria. Phone services to check.')).toBeInTheDocument();
    expect(screen.queryByText(/Sorted by travel time/)).toBeNull();
  });

  it('says the postcode is not found, or outside the network’s areas, without offering another district to try', async () => {
    server.use(http.get('/api/bff/network/options', () => HttpResponse.json({ ...parseNetworkOptions(OPTIONS_BODY, 'backend'), options: [], notFound: true })));
    const first = render(<NetworkOptions caseId="4821" />);
    expect(await screen.findByText('We could not place this postcode, so no travel time can be shown.')).toBeInTheDocument();
    first.unmount();
    server.use(http.get('/api/bff/network/options', () => HttpResponse.json({ ...parseNetworkOptions(OPTIONS_BODY, 'backend'), options: [], outOfArea: true })));
    render(<NetworkOptions caseId="4821" />);
    expect(await screen.findByText('No service in Sample Network covers this postcode.')).toBeInTheDocument();
  });

  it.each([404, 403, 401])('is the one "not available" panel when the read is refused (%i)', async (status) => {
    server.use(http.get('/api/bff/network/options', () => HttpResponse.json({ code: 'x' }, { status })));
    render(<NetworkOptions caseId="4821" />);
    expect(await screen.findByText('Network view not available')).toBeInTheDocument();
    expect(screen.queryAllByRole('article')).toHaveLength(0);
  });

  it('says the options could not be read, with a way to try again, when the read fails; never an empty list', async () => {
    const user = userEvent.setup();
    let fail = true;
    server.use(
      http.get('/api/bff/network/options', () =>
        fail ? HttpResponse.json({ code: 'unavailable' }, { status: 503 }) : HttpResponse.json(parseNetworkOptions(OPTIONS_BODY, 'backend')),
      ),
    );
    render(<NetworkOptions caseId="4821" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('The network options could not be read. Phone services to check.');
    expect(screen.queryByText(/No service in/)).toBeNull();
    fail = false;
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(screen.getAllByRole('article')).toHaveLength(2));
  });

  it('shows no tenant, network or source identifier, and no case data', async () => {
    const { container } = render(<NetworkOptions caseId="4821" />);
    await screen.findAllByRole('article');
    expect(container.textContent).not.toMatch(/net-sample|tenant|grant|DT4|postcode/i);
  });

  it('has the toggle between the list and the map of the same case', async () => {
    render(<NetworkOptions caseId="4821" />);
    await screen.findAllByRole('article');
    expect(screen.getByRole('button', { name: 'List' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Map' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('has no axe violations', async () => {
    const { container } = render(<NetworkOptions caseId="4821" />);
    await screen.findAllByRole('article');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
