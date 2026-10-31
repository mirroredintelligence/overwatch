import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { OPTIONS_BODY } from '@/test/fixtures/network';
import { networkBffHandlers, resetNetworkBff, seenNetworkBff } from '@/test/msw/handlers/networkBff';
import { server } from '@/test/msw/server';
import { parseNetworkOptions } from '@/lib/network/parse';
import { NetworkMap } from './NetworkMap';

// WB11 (docs/design/network-ui.md section 9, "Map"): the network's rows with a map pin, the same toggles as the
// advisor's own map (ADV-MAP-TOGGLE-LIST and ADV-MAP-TOGGLE-MAP), and no booking action. A row with no shared
// place has no pin; the list holds every service the map shows.

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

beforeEach(() => {
  resetNetworkBff();
  server.use(...networkBffHandlers);
});

describe('NetworkMap', () => {
  it('says which board it is, that it is read only, and has the two toggles with the map pressed', async () => {
    const { container } = render(<NetworkMap caseId="4821" />);
    await screen.findByRole('button', { name: 'Virtual ward frailty' });
    expect(screen.getByRole('region', { name: 'Which board you are viewing' })).toHaveTextContent('Showing: Network, Sample Network');
    expect(screen.getByText('Read only')).toBeInTheDocument();
    expect(container.querySelector('[data-el="ADV-MAP-TOGGLE-MAP"]')).toHaveAttribute('aria-pressed', 'true');
    expect(container.querySelector('[data-el="ADV-MAP-TOGGLE-LIST"]')).toHaveAttribute('aria-pressed', 'false');
  });

  it('draws a pin for each row that has a place, and none for one that has none, and says so', async () => {
    render(<NetworkMap caseId="4821" />);
    expect(await screen.findByRole('button', { name: 'Virtual ward frailty' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Reablement south' })).toBeNull();
    expect(screen.getByText('1 service has no place on the map. See the list.')).toBeInTheDocument();
  });

  it('shows the pinned service’s card with its organisation, its figure, its service line, and no booking action', async () => {
    const user = userEvent.setup();
    render(<NetworkMap caseId="4821" />);
    await user.click(await screen.findByRole('button', { name: 'Virtual ward frailty' }));
    const card = screen.getByRole('region', { name: 'Virtual ward frailty' });
    expect(within(card).getByText('Sample Area B')).toBeInTheDocument();
    expect(within(card).getByText('Free 1 beds')).toBeInTheDocument();
    expect(within(card).getByRole('link', { name: 'Phone Virtual ward frailty on 01632 960010' })).toBeInTheDocument();
    for (const name of [/Request booking/, /I phoned/, /They declined/, /Ask clinical/]) expect(within(card).queryByRole('button', { name })).toBeNull();
    expect(within(card).getByRole('button', { name: 'Criteria' })).toBeInTheDocument();
  });

  it('opens the criteria of the pinned service, read only', async () => {
    const user = userEvent.setup();
    render(<NetworkMap caseId="4821" />);
    await user.click(await screen.findByRole('button', { name: 'Virtual ward frailty' }));
    await user.click(screen.getByRole('button', { name: 'Criteria' }));
    expect(await screen.findByRole('dialog', { name: 'Criteria: Virtual ward frailty' })).toBeInTheDocument();
  });

  it('reads the options once, for the one network and the case reference only', async () => {
    render(<NetworkMap caseId="4821" />);
    await screen.findByRole('button', { name: 'Virtual ward frailty' });
    expect(seenNetworkBff.filter((read) => read.path === '/api/bff/network/options')).toEqual([{ path: '/api/bff/network/options', query: 'networkId=net-sample&case=4821' }]);
  });

  it('says no service has a place when none does, and the postcode states without a district to choose', async () => {
    server.use(http.get('/api/bff/network/options', () => HttpResponse.json({ ...parseNetworkOptions(OPTIONS_BODY, 'backend'), notFound: true })));
    const first = render(<NetworkMap caseId="4821" />);
    expect(await screen.findByText('We could not place this postcode, so the map cannot be drawn.')).toBeInTheDocument();
    first.unmount();
    server.use(http.get('/api/bff/network/options', () => HttpResponse.json({ ...parseNetworkOptions(OPTIONS_BODY, 'backend'), outOfArea: true })));
    render(<NetworkMap caseId="4821" />);
    expect(await screen.findByText('No service in Sample Network covers this postcode.')).toBeInTheDocument();
  });

  it('is the one "not available" panel when refused, and says it could not be read when the read fails', async () => {
    server.use(http.get('/api/bff/network/options', () => HttpResponse.json({ code: 'x' }, { status: 404 })));
    const refused = render(<NetworkMap caseId="4821" />);
    expect(await screen.findByText('Network view not available')).toBeInTheDocument();
    refused.unmount();
    server.use(http.get('/api/bff/network/options', () => HttpResponse.json({ code: 'unavailable' }, { status: 503 })));
    render(<NetworkMap caseId="4821" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('The network map could not be read. Phone services to check.');
  });

  it('has no axe violations', async () => {
    const { container } = render(<NetworkMap caseId="4821" />);
    await screen.findByRole('button', { name: 'Virtual ward frailty' });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
