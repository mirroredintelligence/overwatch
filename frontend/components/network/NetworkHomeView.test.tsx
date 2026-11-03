import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { OTHER_ORGANISATION, OWN_ORGANISATION, SYSTEM_NOW_BODY, THIRD_ORGANISATION } from '@/test/fixtures/network';
import { networkBffHandlers, resetNetworkBff, seenNetworkBff } from '@/test/msw/handlers/networkBff';
import { server } from '@/test/msw/server';
import { parseSystemNow } from '@/lib/network/parse';
import { NetworkHomeView } from './NetworkHomeView';

// WB11, known issue W10-K3 (docs/design/network-ui.md section 9, "Advisor home counts" and "Exec home"), and the
// network home board (planning-analytics-network.md, Network, /network/home; boards NHome and PH4): the counts of
// the network's rows by status as five status tiles, the organisations that share (the viewer's own first, with
// the number of services each shares), two actions, and the scope header. No pending count, no next-due time,
// no service named. The executive's alerts stay the organisation's own (DEC-136 item 9) and the page says so.

const advisor = () => render(<NetworkHomeView audience="advisor" ownHref="/advisor" />);
const exec = () => render(<NetworkHomeView audience="exec" ownHref="/planning" />);

describe('NetworkHomeView: the advisor’s home counts over the network', () => {
  it('says which board it is, and has the page heading, with the switch back to the advisor home', async () => {
    server.use(...networkBffHandlers);
    advisor();
    expect(await screen.findByRole('heading', { level: 1, name: 'Network home' })).toBeInTheDocument();
    const header = await screen.findByRole('region', { name: 'Which board you are viewing' });
    expect(header).toHaveTextContent('Showing: Network, Sample Network');
    expect(within(header).getByRole('link', { name: 'Our organisation' })).toHaveAttribute('href', '/advisor');
  });

  it('shows the five counts of the advisor’s home, with the word of each status, over the network’s rows', async () => {
    server.use(...networkBffHandlers);
    const { container } = advisor();
    await screen.findByText('4 services from 3 organisations');
    const count = (id: string) => container.querySelector(`[data-el="${id}"]`);
    expect(count('NET-HOME-COUNT-ACCEPTING')).toHaveTextContent('1');
    expect(count('NET-HOME-COUNT-LIMITED')).toHaveTextContent('1');
    expect(count('NET-HOME-COUNT-NOT-ACCEPTING')).toHaveTextContent('0');
    expect(count('NET-HOME-COUNT-OVER-CAPACITY')).toHaveTextContent('0');
    expect(count('NET-HOME-COUNT-NOT-UPDATED')).toHaveTextContent('1');
    for (const word of ['Accepting', 'Limited', 'Not accepting', 'Over capacity', 'Not updated']) expect(screen.getAllByText(word).length).toBeGreaterThan(0);
  });

  it('says how many are not available on the network, and has no pending count and no organisation or service named in the counts', async () => {
    server.use(...networkBffHandlers);
    const { container } = advisor();
    await screen.findByText('4 services from 3 organisations');
    expect(screen.getByText('1 not available on the network')).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/pending|next due|UCR/i);
  });

  it('is read only: the note, and no button to book or to start a call from the network’s numbers', async () => {
    server.use(...networkBffHandlers);
    advisor();
    await screen.findByText('4 services from 3 organisations');
    expect(screen.getByText('Read only')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Start a new call|Request booking/ })).toBeNull();
    expect(screen.getByRole('link', { name: 'Open the network board view' })).toHaveAttribute('href', '/network/board');
  });

  it('reads the network once for the one network the server offered, and nothing else', async () => {
    resetNetworkBff();
    server.use(...networkBffHandlers);
    advisor();
    await screen.findByText('4 services from 3 organisations');
    expect(seenNetworkBff.filter((read) => read.path === '/api/bff/network/system-now')).toEqual([{ path: '/api/bff/network/system-now', query: 'networkId=net-sample' }]);
  });

  it('says the board could not be read, never zeros, when the read fails first; and keeps the last counts when a later one fails', async () => {
    server.use(http.get('/api/bff/network/system-now', () => HttpResponse.json({ code: 'unavailable' }, { status: 503 })), http.get('/api/bff/network', () => HttpResponse.json(networkList())));
    advisor();
    expect(await screen.findByRole('alert')).toHaveTextContent('The network could not be read. Try again shortly.');
    expect(document.querySelector('[data-el="NET-HOME-COUNT-ACCEPTING"]')).toBeNull();
  });

  it('is the one "not available" panel when refused', async () => {
    server.use(http.get('/api/bff/network/system-now', () => HttpResponse.json({ code: 'x' }, { status: 404 })));
    server.use(...networkBffHandlers.filter((handler) => !String(handler.info.path).includes('system-now')));
    advisor();
    expect(await screen.findByText('Network view not available')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    server.use(...networkBffHandlers);
    const { container } = advisor();
    await screen.findByText('4 services from 3 organisations');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('NetworkHomeView: the executive’s home over the network', () => {
  it('has the page heading, with the switch back to the executive home, and the same counts', async () => {
    server.use(...networkBffHandlers);
    const { container } = exec();
    expect(await screen.findByRole('heading', { level: 1, name: 'Network home' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Which board you are viewing' })).toHaveTextContent('Showing: Network, Sample Network');
    expect(within(screen.getByRole('region', { name: 'Which board you are viewing' })).getByRole('link', { name: 'Our organisation' })).toHaveAttribute('href', '/planning');
    await screen.findByText('4 services from 3 organisations');
    expect(container.querySelector('[data-el="NET-HOME-COUNT-ACCEPTING"]')).toHaveTextContent('1');
  });

  it('says that alerts are for the executive’s own organisation only, and shows no alert of another’s', async () => {
    server.use(...networkBffHandlers);
    exec();
    expect(await screen.findByText('Alerts are for your own organisation only.')).toBeInTheDocument();
    expect(document.querySelector('[data-el="EXEC-ALERT"]')).toBeNull();
  });

  it('offers the two actions of the board: the network board, and the services of the network', async () => {
    server.use(...networkBffHandlers);
    exec();
    expect(await screen.findByRole('link', { name: 'Open the network board' })).toHaveAttribute('href', '/network/board');
    expect(screen.getByRole('link', { name: 'See the services' })).toHaveAttribute('href', '/network/services');
  });

  it('shows the pressure of the network as a state, when it is raised', async () => {
    server.use(http.get('/api/bff/network/system-now', () => HttpResponse.json(parseSystemNow({ ...SYSTEM_NOW_BODY, pressure: 'high', alert: { raised: true, level: 'high', limited_or_worse: 5, watch_from: 3, high_from: 5 } }, 'backend'))));
    server.use(...networkBffHandlers.filter((handler) => !String(handler.info.path).includes('system-now')));
    exec();
    expect(await screen.findByText('Network pressure is high')).toBeInTheDocument();
  });
});

describe('NetworkHomeView: who shares the network', () => {
  it('lists each organisation once, the viewer’s own first and marked, with the number of services each shares', async () => {
    server.use(...networkBffHandlers);
    advisor();
    const who = await screen.findByRole('region', { name: 'Who shares' });
    const chips = within(who)
      .getAllByRole('listitem')
      .map((item) => item.textContent);
    expect(chips).toEqual([`${OWN_ORGANISATION} · 1 · Your organisation`, `${OTHER_ORGANISATION} · 2`, `${THIRD_ORGANISATION} · 1`]);
  });

  it('says the figures are each organisation’s own, and not ranked', async () => {
    server.use(...networkBffHandlers);
    advisor();
    expect(await screen.findByText('Figures are reported by each organisation. Not ranked.')).toBeInTheDocument();
  });

  it('says the organisations could not be read, and keeps the counts, when the board cannot be read', async () => {
    server.use(http.get('/api/bff/network/board', () => HttpResponse.json({ code: 'unavailable' }, { status: 503 })), ...networkBffHandlers);
    const { container } = advisor();
    expect(await screen.findByText('The organisations could not be read.')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Who shares' })?.querySelectorAll('li').length ?? 0).toBe(0);
    await screen.findByText('4 services from 3 organisations');
    expect(container.querySelector('[data-el="NET-HOME-COUNT-ACCEPTING"]')).toHaveTextContent('1');
  });
});

function networkList() {
  return { ownOrganisation: 'Sample Area A', networks: [{ id: 'net-sample', name: 'Sample Network', systemName: 'Sample capacity', pathwayName: 'Sample pathway', timeZone: 'Europe/London' }] };
}
