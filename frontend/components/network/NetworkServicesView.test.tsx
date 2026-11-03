import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { networkBffHandlers } from '@/test/msw/handlers/networkBff';
import { server } from '@/test/msw/server';
import { NetworkServicesView } from './NetworkServicesView';

// TEN-071: the network directory. A read-only list of every member's services that the network shares, with
// the organisation and category filters over the rows it has. The list stays on screen when a service is
// open: the open service's detail sits beside it (the board NServices), and a service that is not in the
// directory is the one "not available" panel in that place.

const view = (selectedRef?: string) => render(<NetworkServicesView ownHref="/advisor/board" selectedRef={selectedRef} />);
const rows = (container: HTMLElement) => Array.from(container.querySelectorAll<HTMLElement>('[data-el="NET-SERVICES-ROW"]'));
const rowRefs = (container: HTMLElement) => rows(container).map((r) => r.getAttribute('data-service-ref'));
const stageOf = (container: HTMLElement) => container.querySelector<HTMLElement>('[data-area="stage"]')!;

describe('NetworkServicesView', () => {
  it('shows the scope header, the count, the read-only note and a row for each service', async () => {
    server.use(...networkBffHandlers);
    const { container } = view();
    expect(await screen.findByText('2 services from 2 organisations')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Which board you are viewing' })).toHaveTextContent('Showing: Network, Sample Network');
    expect(screen.getByRole('heading', { level: 1, name: 'Sample Network services' })).toBeInTheDocument();
    expect(screen.getByText('Read only')).toBeInTheDocument();
    expect(rowRefs(container)).toEqual(['lst-0001', 'lst-0002']);
  });

  it('marks the viewer’s own organisation', async () => {
    server.use(...networkBffHandlers);
    view();
    await screen.findByText('2 services from 2 organisations');
    expect(screen.getAllByText('Your organisation')).toHaveLength(1);
  });

  it('offers "Any category" first, and filters by organisation and by category, in place', async () => {
    server.use(...networkBffHandlers);
    const user = userEvent.setup();
    const { container } = view();
    await screen.findByText('2 services from 2 organisations');
    expect(screen.getByRole('button', { name: 'Any category' })).toHaveAttribute('aria-pressed', 'true');
    await user.click(screen.getByRole('button', { name: 'Sample Area B' }));
    expect(rowRefs(container)).toEqual(['lst-0002']);
    await user.click(screen.getByRole('button', { name: 'All organisations' }));
    await user.click(screen.getByRole('button', { name: 'Urgent community response' }));
    expect(rowRefs(container)).toEqual(['lst-0001']);
    expect(screen.getByRole('button', { name: 'Urgent community response' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Any category' })).toHaveAttribute('aria-pressed', 'false');
    await user.click(screen.getByRole('button', { name: 'Any category' }));
    expect(rowRefs(container)).toEqual(['lst-0001', 'lst-0002']);
    await user.click(screen.getByRole('button', { name: 'Sample Area B' }));
    await user.click(screen.getByRole('button', { name: 'Urgent community response' }));
    expect(screen.getByText('No services match this filter')).toBeInTheDocument();
  });

  it('says no services are shared yet for an empty network', async () => {
    server.use(http.get('/api/bff/network/directory', () => HttpResponse.json({ entries: [], systemName: 'a', pathwayName: 'b', timeZone: 'Europe/London' })), ...networkBffHandlers);
    view();
    expect(await screen.findByText('No services are shared yet')).toBeInTheDocument();
  });

  it('leaves out a service its organisation has set inactive', async () => {
    const entry = (rowRef: string, active: boolean) => ({ rowRef, organisationName: 'Sample Area B', serviceName: rowRef, category: 'other', active, source: 'manual', contactLabel: null, contactPhone: null, location: null, openingHours: [], presentation: 'shown', endedAt: null, endReason: null });
    server.use(http.get('/api/bff/network/directory', () => HttpResponse.json({ entries: [entry('lst-0020', true), entry('lst-0021', false)], systemName: 'a', pathwayName: 'b', timeZone: 'Europe/London' })), ...networkBffHandlers);
    const { container } = view();
    await screen.findByText('1 service from 1 organisation');
    expect(rowRefs(container)).toEqual(['lst-0020']);
  });

  it('is "not available" when the read is refused, and says it could not read it when it fails', async () => {
    server.use(http.get('/api/bff/network/directory', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })), ...networkBffHandlers);
    const first = view();
    expect(await screen.findByText('Network view not available')).toBeInTheDocument();
    first.unmount();
    server.use(http.get('/api/bff/network/directory', () => HttpResponse.json({ code: 'exception' }, { status: 503 })));
    view();
    expect(await screen.findByText('The services could not be read. Try again shortly.')).toBeInTheDocument();
  });

  it('says the services are loading, in words, while they are read', async () => {
    server.use(http.get('/api/bff/network/directory', () => new Promise(() => {})), ...networkBffHandlers);
    view();
    expect(await screen.findByText('Loading the services')).toBeInTheDocument();
  });

  it('is a list alone, with the stage closed, when no service is open', async () => {
    server.use(...networkBffHandlers);
    const { container } = view();
    await screen.findByText('2 services from 2 organisations');
    expect(container.querySelector('[data-stage]')).toHaveAttribute('data-stage', '0');
    expect(within(stageOf(container)).queryByRole('heading')).toBeNull();
    for (const row of rows(container)) expect(within(row).getByRole('link')).not.toHaveAttribute('aria-current');
  });

  it('opens the chosen service beside the list, with the list still there and the chosen row marked', async () => {
    server.use(...networkBffHandlers);
    const { container } = view('lst-0001');
    await screen.findByText('2 services from 2 organisations');
    expect(container.querySelector('[data-stage]')).toHaveAttribute('data-stage', '1');
    expect(rowRefs(container)).toEqual(['lst-0001', 'lst-0002']);
    expect(within(rows(container)[0]!).getByRole('link', { name: 'UCR West' })).toHaveAttribute('aria-current', 'true');
    expect(await within(stageOf(container)).findByRole('heading', { level: 2, name: 'UCR West' })).toBeInTheDocument();
    expect(within(stageOf(container)).getByRole('link', { name: 'Phone UCR West on 01632 960010' })).toHaveAttribute('href', 'tel:01632960010');
  });

  it('says "not available" in the place of the detail for a service that is not in the directory, and keeps the list', async () => {
    server.use(...networkBffHandlers);
    const { container } = view('lst-9999');
    expect(await screen.findByText('Network view not available')).toBeInTheDocument();
    expect(rowRefs(container)).toEqual(['lst-0001', 'lst-0002']);
  });

  it('says the criteria of the open service are loading while they are read', async () => {
    server.use(http.get('/api/bff/network/criteria', () => new Promise(() => {})), ...networkBffHandlers);
    const { container } = view('lst-0001');
    await screen.findByText('2 services from 2 organisations');
    expect(await within(stageOf(container)).findByText('Loading the criteria')).toBeInTheDocument();
  });

  it('has no controls on a row but the one link, and no axe violations', async () => {
    server.use(...networkBffHandlers);
    const { container } = view();
    await screen.findByText('2 services from 2 organisations');
    for (const row of rows(container)) expect(within(row).getAllByRole('link')).toHaveLength(1);
    expect(container.innerHTML).not.toMatch(/trust-|tenant|net-sample/i);
    expect((await runAxe(container)).violations).toEqual([]);
  });

  it('has no axe violations with a service open beside the list', async () => {
    server.use(...networkBffHandlers);
    const { container } = view('lst-0001');
    await screen.findByText('2 services from 2 organisations');
    await within(stageOf(container)).findByRole('heading', { level: 2, name: 'UCR West' });
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
