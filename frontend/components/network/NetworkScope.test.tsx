import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { NETWORKS_BODY } from '@/test/fixtures/network';
import { networkBffHandlers, NETWORK_LIST } from '@/test/msw/handlers/networkBff';
import { server } from '@/test/msw/server';
import { NetworkScope } from './NetworkScope';

// TEN-068/070: the gate every network page stands in. It reads the networks the server offers, and shows
// the page only for one of them; any refusal is the one "not available" panel; a failure is "offline"
// with a way to try again. With more than one network it lets the viewer choose, in the page and not in
// the address.

const LINKS = { ownHref: '/advisor/board', networkHref: '/network/board' };

function page() {
  return render(
    <NetworkScope {...LINKS}>
      {({ network, ownOrganisation, switchTo }) => (
        <p data-testid="page" data-own={switchTo.ownHref} data-network={switchTo.networkHref}>{`${network.name} for ${ownOrganisation}`}</p>
      )}
    </NetworkScope>,
  );
}

describe('NetworkScope', () => {
  it('shows the page for the one network, giving it the network, the viewer’s organisation and the two routes of the switch', async () => {
    server.use(...networkBffHandlers);
    page();
    expect(screen.getByRole('status')).toHaveTextContent('Loading the network');
    const shown = await screen.findByTestId('page');
    expect(shown).toHaveTextContent('Sample Network for Sample Area A');
    expect(shown).toHaveAttribute('data-own', '/advisor/board');
    expect(shown).toHaveAttribute('data-network', '/network/board');
    expect(screen.queryByRole('group', { name: 'Which network' })).toBeNull();
  });

  it('is the one "not available" panel for a viewer in no network', async () => {
    server.use(http.get('/api/bff/network', () => HttpResponse.json({ ownOrganisation: 'Sample Area A', networks: [] })));
    page();
    expect(await screen.findByText('Network view not available')).toBeInTheDocument();
    expect(screen.queryByTestId('page')).toBeNull();
    expect(screen.getByRole('link', { name: 'Back to our organisation' })).toHaveAttribute('href', '/advisor/board');
  });

  it.each([401, 403, 404])('is the same panel for a %s', async (status) => {
    server.use(http.get('/api/bff/network', () => HttpResponse.json({ code: 'x' }, { status })));
    page();
    expect(await screen.findByText('Network view not available')).toBeInTheDocument();
  });

  it('is offline, with a way to try again, when the list cannot be read, and recovers', async () => {
    server.use(http.get('/api/bff/network', () => HttpResponse.json({ code: 'exception' }, { status: 503 })));
    page();
    expect(await screen.findByText(/Network board offline/)).toBeInTheDocument();
    server.use(...networkBffHandlers);
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByTestId('page')).toBeInTheDocument();
  });

  it('lets the viewer choose between networks, in the page, and gives the page the one chosen', async () => {
    const two = {
      ...NETWORK_LIST,
      networks: [...NETWORK_LIST.networks, { ...NETWORKS_BODY.networks[0]!, id: 'net-second', name: 'Second Network', systemName: 'S', pathwayName: 'P', timeZone: 'Europe/London' }],
    };
    server.use(http.get('/api/bff/network', () => HttpResponse.json(two)));
    page();
    expect(await screen.findByText('Sample Network for Sample Area A')).toBeInTheDocument();
    const chooser = screen.getByRole('group', { name: 'Which network' });
    expect(chooser).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Second Network' }));
    expect(await screen.findByText('Second Network for Sample Area A')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Second Network' })).toHaveAttribute('aria-pressed', 'true'));
  });

  it('puts no network id in the address or the page’s attributes', async () => {
    server.use(...networkBffHandlers);
    const { container } = page();
    await screen.findByTestId('page');
    expect(window.location.href).not.toMatch(/net-/);
    expect(container.innerHTML).not.toMatch(/net-sample/);
  });
});
