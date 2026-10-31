import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { networkBffHandlers } from '@/test/msw/handlers/networkBff';
import { server } from '@/test/msw/server';
import { NetworkServicesView } from './NetworkServicesView';

// TEN-071: the network directory. A read-only list of every member's services that the network shares, with
// the organisation and category filters over the rows it has.

const view = () => render(<NetworkServicesView ownHref="/advisor/board" />);
const rows = (container: HTMLElement) => Array.from(container.querySelectorAll<HTMLElement>('[data-el="NET-SERVICES-ROW"]'));

describe('NetworkServicesView', () => {
  it('shows the scope header, the count, the read-only note and a row for each service', async () => {
    server.use(...networkBffHandlers);
    const { container } = view();
    expect(await screen.findByText('2 services from 2 organisations')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Which board you are viewing' })).toHaveTextContent('Showing: Network, Sample Network');
    expect(screen.getByRole('heading', { level: 1, name: 'Sample Network services' })).toBeInTheDocument();
    expect(screen.getByText('Read only')).toBeInTheDocument();
    expect(rows(container).map((r) => r.getAttribute('data-service-ref'))).toEqual(['lst-0001', 'lst-0002']);
  });

  it('marks the viewer’s own organisation', async () => {
    server.use(...networkBffHandlers);
    view();
    await screen.findByText('2 services from 2 organisations');
    expect(screen.getAllByText('Your organisation')).toHaveLength(1);
  });

  it('filters by organisation and by category, in place', async () => {
    server.use(...networkBffHandlers);
    const user = userEvent.setup();
    const { container } = view();
    await screen.findByText('2 services from 2 organisations');
    await user.click(screen.getByRole('button', { name: 'Sample Area B' }));
    expect(rows(container).map((r) => r.getAttribute('data-service-ref'))).toEqual(['lst-0002']);
    await user.click(screen.getByRole('button', { name: 'All organisations' }));
    await user.click(screen.getByRole('button', { name: 'Urgent community response' }));
    expect(rows(container).map((r) => r.getAttribute('data-service-ref'))).toEqual(['lst-0001']);
    expect(screen.getByRole('button', { name: 'Urgent community response' })).toHaveAttribute('aria-pressed', 'true');
    await user.click(screen.getByRole('button', { name: 'Sample Area B' }));
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
    expect(rows(container).map((r) => r.getAttribute('data-service-ref'))).toEqual(['lst-0020']);
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

  it('has no controls on a row but the one link, and no axe violations', async () => {
    server.use(...networkBffHandlers);
    const { container } = view();
    await screen.findByText('2 services from 2 organisations');
    for (const row of rows(container)) expect(within(row).getAllByRole('link')).toHaveLength(1);
    expect(container.innerHTML).not.toMatch(/trust-|tenant|net-sample/i);
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
