import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { networkBffHandlers } from '@/test/msw/handlers/networkBff';
import { server } from '@/test/msw/server';
import { OwnScopeHeader } from './OwnScopeHeader';

// The scope header on the organisation's own pages (W17, W43, the exec week, the advisor's board): it says
// "Showing: Our organisation" always, and offers the switch to the network variant only when the viewer's
// organisation is in a network. A read that fails leaves the label and no switch: the own page never waits
// for, or breaks on, the network.

describe('OwnScopeHeader', () => {
  it('says it is the organisation’s own, at once, with no switch before the networks are known', () => {
    server.use(...networkBffHandlers);
    render(<OwnScopeHeader ownHref="/lead" networkHref="/network/system-now" />);
    expect(screen.getByText('Showing: Our organisation')).toBeInTheDocument();
    expect(screen.queryByRole('navigation')).toBeNull();
  });

  it('offers the switch to the network page when the organisation is in a network', async () => {
    server.use(...networkBffHandlers);
    render(<OwnScopeHeader ownHref="/lead" networkHref="/network/system-now" />);
    const network = await screen.findByRole('link', { name: 'Network' });
    expect(network).toHaveAttribute('href', '/network/system-now');
    expect(screen.getByRole('link', { name: 'Our organisation' })).toHaveAttribute('aria-current', 'page');
  });

  it('has no switch for an organisation in no network', async () => {
    server.use(http.get('/api/bff/network', () => HttpResponse.json({ ownOrganisation: 'Sample Area A', networks: [] })));
    render(<OwnScopeHeader ownHref="/lead" networkHref="/network/system-now" />);
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByRole('navigation')).toBeNull();
    expect(screen.getByText('Showing: Our organisation')).toBeInTheDocument();
  });

  it.each([403, 404, 503])('has no switch, and still the label, when the read answers %s', async (status) => {
    server.use(http.get('/api/bff/network', () => HttpResponse.json({ code: 'x' }, { status })));
    render(<OwnScopeHeader ownHref="/lead" networkHref="/network/system-now" />);
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByRole('navigation')).toBeNull();
    expect(screen.getByText('Showing: Our organisation')).toBeInTheDocument();
  });
});
