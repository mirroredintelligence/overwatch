import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { ServiceDetail } from './ServiceDetail';

// The one service detail page (DEC-1367), shared by the Analytics User and the advisor pages: name, group, districts and
// status; the capacity as "n / normal" or "Current capacity unavailable"; the day chart; the reporting strip; the
// service's contact; the criteria; the catchment. A person's email or mobile is never shown, and a field the system
// does not hold is left out, not invented.

const ANSWER = {
  serviceId: 'svc-a',
  name: 'Ward A',
  category: 'inpatient-beds',
  status: 'limited',
  unitLabel: 'beds',
  established: 10,
  used: 8,
  effectiveAvailable: 2,
  overBy: null,
  lastFigure: 2,
  reportedAt: '2026-10-30T06:30:00Z',
  nextDueAt: '2026-10-30T08:30:00Z',
  cadence: 'every-2-hrs',
  overdue: false,
  staleWarning: false,
  dataAgeSeconds: 1800,
  phone: '01305 000000',
  openingHours: [{ days: [0, 1, 2, 3, 4], allDay: false, start: '08:00', end: '18:00' }],
  accepts: ['frailty', 'wound-care'],
  excludes: ['iv-therapy'],
  ageMin: 18,
  ageMax: null,
  districts: ['DT4', 'DT5'],
};

function serve(change: Record<string, unknown> = {}, status = 200) {
  server.use(
    http.get('/api/bff/advisor/services/:id/detail', () =>
      status === 200 ? HttpResponse.json({ ...ANSWER, ...change }) : HttpResponse.json({}, { status }),
    ),
  );
}

function renderPage() {
  return render(
    <ServiceDetail serviceId="svc-a" backHref="/analytics" backLabel="Back to the overview" rootLabel="Capacity Board" />,
  );
}

describe('ServiceDetail', () => {
  it('shows the name, group, districts and status first', async () => {
    serve();
    renderPage();
    expect(await screen.findByRole('heading', { level: 1, name: 'Ward A' })).toBeInTheDocument();
    const head = screen.getByRole('region', { name: 'Service' });
    expect(within(head).getByText('Inpatient beds')).toBeInTheDocument();
    expect(within(head).getByText('DT4 · DT5')).toBeInTheDocument();
    expect(within(head).getByText('Limited')).toBeInTheDocument();
  });

  it('shows the capacity remaining as n over normal when the figure is current', async () => {
    serve();
    renderPage();
    const capacity = await screen.findByRole('region', { name: 'Capacity remaining' });
    expect(within(capacity).getByText('2')).toBeInTheDocument();
    expect(within(capacity).getByText('/ 10')).toBeInTheDocument();
    expect(within(capacity).queryByText('Current capacity unavailable')).toBeNull();
  });

  it('says "Current capacity unavailable" with the last figure small when the report is late', async () => {
    serve({ overdue: true, dataAgeSeconds: 4 * 60 * 60 });
    renderPage();
    const capacity = await screen.findByRole('region', { name: 'Capacity remaining' });
    expect(within(capacity).getByText('Current capacity unavailable')).toBeInTheDocument();
    expect(within(capacity).getByText(/Last reported: 2 beds/)).toBeInTheDocument();
    expect(within(capacity).queryByText('2')).toBeNull();
  });

  it('draws the day chart', async () => {
    serve();
    renderPage();
    expect(await screen.findByRole('img')).toBeInTheDocument();
  });

  it('shows the reporting strip: last update, frequency, next due, and the schedule in words', async () => {
    serve();
    renderPage();
    const strip = await screen.findByRole('region', { name: 'Capacity reporting' });
    expect(within(strip).getByText('Last update')).toBeInTheDocument();
    expect(within(strip).getByText('Every 2 hrs')).toBeInTheDocument();
    expect(within(strip).getByText('Next due')).toBeInTheDocument();
    expect(within(strip).getByText('On schedule')).toBeInTheDocument();
  });

  it('says Overdue in words when the report is late', async () => {
    serve({ overdue: true });
    renderPage();
    const strip = await screen.findByRole('region', { name: 'Capacity reporting' });
    expect(within(strip).getByText('Overdue')).toBeInTheDocument();
  });

  it('shows the service contact with a Copy number button, and the opening hours', async () => {
    serve();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    renderPage();
    const contact = await screen.findByRole('region', { name: 'Contact' });
    expect(within(contact).getByText('01305 000000')).toBeInTheDocument();
    expect(within(contact).getByText('Mon to Fri, 08:00 to 18:00')).toBeInTheDocument();
    await userEvent.click(within(contact).getByRole('button', { name: 'Copy number' }));
    expect(writeText).toHaveBeenCalledWith('01305 000000');
    expect(await within(contact).findByText('Number copied')).toBeInTheDocument();
  });

  it('says no number is held, and offers no button, when the service has none', async () => {
    serve({ phone: null });
    renderPage();
    const contact = await screen.findByRole('region', { name: 'Contact' });
    expect(within(contact).getByText(/No phone number is held/)).toBeInTheDocument();
    expect(within(contact).queryByRole('button', { name: 'Copy number' })).toBeNull();
  });

  it('shows the criteria as one panel: accepts, a divider, example exclusions, and the caveat at the bottom', async () => {
    serve();
    renderPage();
    const panel = await screen.findByRole('region', { name: 'Referral criteria' });
    expect(within(panel).getByRole('heading', { name: 'Potentially accepts' })).toBeInTheDocument();
    expect(within(panel).getByText('Frailty')).toBeInTheDocument();
    expect(within(panel).getByText('Wound care')).toBeInTheDocument();
    expect(within(panel).getByText('Age 18+')).toBeInTheDocument();
    expect(within(panel).getByRole('separator')).toBeInTheDocument();
    expect(within(panel).getByRole('heading', { name: 'Example exclusions' })).toBeInTheDocument();
    expect(within(panel).getByText('IV therapy')).toBeInTheDocument();
    const caveat = within(panel).getByText(/receiving service confirms/i);
    expect(panel.lastElementChild).toBe(caveat);
    expect(screen.queryByRole('region', { name: 'Exclusions' })).toBeNull();
  });

  it('says the criteria are not held, and to phone, when there are none', async () => {
    serve({ accepts: null, excludes: null, ageMin: null });
    renderPage();
    const panel = await screen.findByRole('region', { name: 'Referral criteria' });
    expect(within(panel).getAllByText(/Not held/).length).toBeGreaterThanOrEqual(1);
  });

  it('puts the catchment in the contact panel beside the opening hours, not in a panel of its own', async () => {
    serve();
    renderPage();
    const contact = await screen.findByRole('region', { name: 'Contact' });
    const meta = within(contact).getByRole('list', { name: 'Service details' });
    expect(within(meta).getByText('Opening hours')).toBeInTheDocument();
    expect(within(meta).getByText('Catchment')).toBeInTheDocument();
    expect(within(meta).getByText('DT4, DT5')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Catchment' })).toBeNull();
  });

  it('shows how many places are in use under the figure', async () => {
    serve();
    renderPage();
    const capacity = await screen.findByRole('region', { name: 'Capacity remaining' });
    expect(within(capacity).getByText('8 beds in use')).toBeInTheDocument();
  });

  it('does not show places in use when the figure is not current', async () => {
    serve({ overdue: true });
    renderPage();
    const capacity = await screen.findByRole('region', { name: 'Capacity remaining' });
    expect(within(capacity).queryByText(/in use/)).toBeNull();
  });

  it('has a breadcrumb: the root, the area, then Service capacity, and a back control', async () => {
    serve();
    renderPage();
    const crumbs = await screen.findByRole('navigation', { name: 'Breadcrumb' });
    expect(within(crumbs).getByRole('link', { name: 'Capacity Board' })).toHaveAttribute('href', '/analytics');
    expect(within(crumbs).getByText('DT4, DT5')).toBeInTheDocument();
    expect(within(crumbs).getByText('Service capacity')).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Back to the overview' })).toHaveAttribute('href', '/analytics');
  });

  it('is a figure and a chart side by side, with chips that keep their own height', () => {
    const css = readFileSync(join(__dirname, 'ServiceDetail.module.css'), 'utf8');
    expect(css).toMatch(/\.overview\s*\{[^}]*grid-template-columns:\s*repeat\(2/);
    expect(css).toMatch(/@media[^{]*max-width[^{]*\{[^}]*\.overview\s*\{[^}]*grid-template-columns:\s*1fr/);
    expect(css).toMatch(/\.chips\s*\{[^}]*align-items:\s*flex-start/);
    expect(css).toMatch(/\.chips\s*\{[^}]*align-content:\s*flex-start/);
    expect(css).not.toMatch(/font-size:\s*1[0-3]px/);
  });

  it('shows no email, no mobile, no contact role and no indicative response, and invents none', async () => {
    serve();
    renderPage();
    await screen.findByRole('heading', { level: 1 });
    expect(document.querySelector('a[href^="mailto:"]')).toBeNull();
    expect(document.body.textContent).not.toMatch(/@|\b07\d{3}|Indicative response|Contact role/i);
  });

  it.each([404, 503])('says so and shows nothing else when the service cannot be read (%i)', async (status) => {
    serve({}, status);
    renderPage();
    await waitFor(() => expect(screen.getByText('The service could not be read.')).toBeInTheDocument());
    expect(screen.queryByRole('heading', { level: 1, name: 'Ward A' })).toBeNull();
  });

  it('has no axe violations', async () => {
    serve();
    const { container } = renderPage();
    await screen.findByRole('img');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
