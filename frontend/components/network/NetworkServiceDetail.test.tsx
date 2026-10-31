import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { networkBffHandlers } from '@/test/msw/handlers/networkBff';
import { server } from '@/test/msw/server';
import { NetworkServiceDetail } from './NetworkServiceDetail';

// TEN-071 (docs/design/network-ui.md, NetworkServiceDetail): one service of the network, read only. About
// it, its hours, its service line, and its current criteria: the current version only, no reason, no owner,
// no history, and no way to report a problem (the message would go to an organisation the viewer cannot
// message).

const view = (id = 'lst-0001') => render(<NetworkServiceDetail rowRef={id} ownHref="/advisor/board" />);

describe('NetworkServiceDetail', () => {
  it('shows the four sections: about, opening hours, service line and criteria', async () => {
    server.use(...networkBffHandlers);
    view();
    expect(await screen.findByRole('heading', { level: 1, name: 'UCR West' })).toBeInTheDocument();
    for (const name of ['About this service', 'Opening hours', 'Service line', 'Criteria']) {
      expect(screen.getByRole('heading', { level: 2, name })).toBeInTheDocument();
    }
    expect(screen.getByRole('region', { name: 'Which board you are viewing' })).toHaveTextContent('Showing: Network, Sample Network');
  });

  it('says whose service it is, what it is and where, and where the entry came from', async () => {
    server.use(...networkBffHandlers);
    view();
    await screen.findByRole('heading', { level: 1, name: 'UCR West' });
    expect(screen.getByText('Shared by Sample Area A')).toBeInTheDocument();
    expect(screen.getByText('Urgent community response · West hub · DT4')).toBeInTheDocument();
    expect(screen.getByText('Entered by the organisation')).toBeInTheDocument();
    expect(screen.getByText('Mon to Fri 08:00 to 20:00')).toBeInTheDocument();
  });

  it('has the service line as a link to phone it', async () => {
    server.use(...networkBffHandlers);
    view();
    const link = await screen.findByRole('link', { name: 'Phone UCR West on 01632 960010' });
    expect(link).toHaveAttribute('href', 'tel:01632960010');
    expect(link).toHaveAttribute('data-el', 'NET-BOARD-PHONE-LINK');
    expect(screen.getByText('Service line 01632 960010')).toBeInTheDocument();
  });

  it('says "No number shared" with no link when there is none', async () => {
    server.use(...networkBffHandlers);
    view('lst-0002');
    await screen.findByRole('heading', { level: 1, name: 'Virtual ward frailty' });
    expect(screen.getByText('No number shared')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Phone/ })).toBeNull();
  });

  it('shows the current criteria read only, in words', async () => {
    server.use(...networkBffHandlers);
    const { container } = view();
    await screen.findByText('Accepts: Frailty, Wound care');
    const section = container.querySelector('[data-el="NET-SERVICE-CRITERIA-SECTION"]')!;
    expect(section).toHaveTextContent('Does not accept: Dementia');
    expect(section).toHaveTextContent('Ages: 18 to 120');
    expect(section).toHaveTextContent('Districts: DT4, DT5');
    expect(section).toHaveTextContent('Review by 15 January 2027');
    for (const word of ['Report a problem', 'version', 'Version', 'reason', 'Change']) expect(section.textContent).not.toContain(word);
    expect(section.querySelectorAll('button, a')).toHaveLength(0);
  });

  it('says no criteria were shared for a service with none, and keeps the rest of the page', async () => {
    server.use(...networkBffHandlers);
    view('lst-0002');
    expect(await screen.findByText('No criteria shared')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Opening hours' })).toBeInTheDocument();
  });

  it('says the criteria could not be read when only that read fails, and keeps the rest', async () => {
    server.use(http.get('/api/bff/network/criteria', () => HttpResponse.json({ code: 'exception' }, { status: 503 })), ...networkBffHandlers);
    view();
    expect(await screen.findByText('The criteria could not be read. Phone to confirm.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'UCR West' })).toBeInTheDocument();
  });

  it('is the "not available" panel for a service that is not in the network, and for a refused read, with no figure', async () => {
    server.use(...networkBffHandlers);
    const unknown = view('lst-9999');
    expect(await screen.findByText('Network view not available')).toBeInTheDocument();
    unknown.unmount();
    server.use(http.get('/api/bff/network/directory', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    view();
    expect(await screen.findByText('Network view not available')).toBeInTheDocument();
  });

  it('has a way back to the services, and no axe violations', async () => {
    server.use(...networkBffHandlers);
    const { container } = view();
    await screen.findByRole('heading', { level: 1, name: 'UCR West' });
    expect(screen.getByRole('link', { name: 'All network services' })).toHaveAttribute('href', '/network/services');
    expect(container.innerHTML).not.toMatch(/trust-|tenant|net-sample/i);
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
