import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { CRITERIA_BODY } from '@/test/fixtures/network';
import { NETWORK_LIST, networkBffHandlers } from '@/test/msw/handlers/networkBff';
import { server } from '@/test/msw/server';
import { parseCriteria } from '@/lib/network/parse';
import { NetworkServiceDetail } from './NetworkServiceDetail';

// TEN-071 (docs/design/network-ui.md, NetworkServiceDetail): one service of the network, read only. It is
// shown as its page shows it: the directory, with this service open beside it. About it, its hours, its
// service line, and its current criteria: the current version only, no reason, no owner, no history, and no
// way to report a problem (the message would go to an organisation the viewer cannot message).

const view = (id = 'lst-0001') => render(<NetworkServiceDetail rowRef={id} ownHref="/advisor/board" />);

/** The open service, once the directory is read: the stage beside the list, and only that. */
async function pane() {
  await screen.findByText('2 services from 2 organisations');
  return within(document.querySelector<HTMLElement>('[data-area="stage"]')!);
}

describe('NetworkServiceDetail', () => {
  it('shows the service name, then four sections: about, opening hours, service line and criteria', async () => {
    server.use(...networkBffHandlers);
    view();
    const p = await pane();
    expect(p.getByRole('heading', { level: 2, name: 'UCR West' })).toBeInTheDocument();
    for (const name of ['About this service', 'Opening hours', 'Service line', 'Criteria']) {
      expect(p.getByRole('heading', { level: 3, name })).toBeInTheDocument();
    }
  });

  it('says whose service it is, what it is and where, and where the entry came from', async () => {
    server.use(...networkBffHandlers);
    view();
    const p = await pane();
    expect(p.getByText('Shared by Sample Area A')).toBeInTheDocument();
    expect(p.getByText('Urgent community response · West hub · DT4')).toBeInTheDocument();
    expect(p.getByText('Entered by the organisation')).toBeInTheDocument();
    expect(p.getByText('Mon to Fri 08:00 to 20:00')).toBeInTheDocument();
  });

  it('marks the viewer’s own organisation in words', async () => {
    server.use(...networkBffHandlers);
    view();
    const p = await pane();
    expect(p.getByText('Your organisation')).toBeInTheDocument();
  });

  it('marks no organisation as the viewer’s own when the viewer has none', async () => {
    server.use(http.get('/api/bff/network', () => HttpResponse.json({ ownOrganisation: null, networks: NETWORK_LIST.networks })), ...networkBffHandlers);
    view();
    const p = await pane();
    expect(p.queryByText('Your organisation')).toBeNull();
    expect(screen.queryByText('Your organisation')).toBeNull();
  });

  it('has the service line as a link to phone it', async () => {
    server.use(...networkBffHandlers);
    view();
    const p = await pane();
    const link = p.getByRole('link', { name: 'Phone UCR West on 01632 960010' });
    expect(link).toHaveAttribute('href', 'tel:01632960010');
    expect(link).toHaveAttribute('data-el', 'NET-BOARD-PHONE-LINK');
    expect(p.getByText('Service line 01632 960010')).toBeInTheDocument();
  });

  it('says "No number shared" with no link when there is none', async () => {
    server.use(...networkBffHandlers);
    view('lst-0002');
    const p = await pane();
    expect(p.getByRole('heading', { level: 2, name: 'Virtual ward frailty' })).toBeInTheDocument();
    expect(p.getByText('No number shared')).toBeInTheDocument();
    expect(p.queryByRole('link', { name: /Phone/ })).toBeNull();
  });

  it('shows the current criteria read only, as label and value pairs', async () => {
    server.use(...networkBffHandlers);
    view();
    const p = await pane();
    const section = await p.findByRole('region', { name: 'Criteria' });
    expect(await within(section).findByText('Frailty, Wound care')).toBeInTheDocument();
    for (const [label, value] of [
      ['Accepts', 'Frailty, Wound care'],
      ['Does not accept', 'Dementia'],
      ['Ages', '18 to 120'],
      ['Districts', 'DT4, DT5'],
      ['Review by', '15 January 2027'],
    ]) {
      expect(within(section).getByText(label)).toBeInTheDocument();
      expect(within(section).getByText(value)).toBeInTheDocument();
    }
    expect(section.textContent).toContain('Current criteria, read only');
    for (const word of ['Report a problem', 'version', 'Version', 'reason', 'Change']) expect(section.textContent).not.toContain(word);
    expect(section.querySelectorAll('button, a')).toHaveLength(0);
  });

  it('says no criteria were shared for a service with none, and keeps the rest of the page', async () => {
    server.use(http.get('/api/bff/network/criteria', () => HttpResponse.json({ ...parseCriteria(CRITERIA_BODY, 'backend'), entries: [] })), ...networkBffHandlers);
    view('lst-0002');
    const p = await pane();
    expect(await p.findByText('No criteria shared')).toBeInTheDocument();
    expect(p.getByRole('heading', { level: 3, name: 'Opening hours' })).toBeInTheDocument();
  });

  it('says the criteria could not be read when only that read fails, and keeps the rest', async () => {
    server.use(http.get('/api/bff/network/criteria', () => HttpResponse.json({ code: 'exception' }, { status: 503 })), ...networkBffHandlers);
    view();
    const p = await pane();
    expect(await p.findByText('The criteria could not be read. Phone to confirm.')).toBeInTheDocument();
    expect(p.getByRole('heading', { level: 2, name: 'UCR West' })).toBeInTheDocument();
  });

  it('has a way back to the services, and no axe violations', async () => {
    server.use(...networkBffHandlers);
    const { container } = view();
    const p = await pane();
    await p.findByText('Frailty, Wound care');
    expect(p.getByRole('link', { name: 'All network services' })).toHaveAttribute('href', '/network/services');
    expect(container.innerHTML).not.toMatch(/trust-|tenant|net-sample/i);
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
