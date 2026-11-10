import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { ANALYTICS_OVERVIEW } from '@/test/fixtures/analytics';
import { server } from '@/test/msw/server';
import { AnalyticsOverview } from './AnalyticsOverview';

// The Analytics User's overview (DEC-1368): five counts, location groups, service groups, what needs attention, and
// the drill-down to a list of services. Figures only; no total of places; status in shapes and words.

async function loaded() {
  server.use(http.get('/api/bff/analytics/overview', () => HttpResponse.json(ANALYTICS_OVERVIEW)));
  const view = render(<AnalyticsOverview />);
  await waitFor(() => byEl('AN-COUNTS'));
  return view;
}

describe('AnalyticsOverview', () => {
  it('shows the five status counts in words, and no total of places available', async () => {
    await loaded();
    const counts = byEl('AN-COUNTS');
    for (const word of ['Accepting', 'Limited', 'Not accepting', 'Over capacity', 'Not updated']) {
      expect(within(counts).getByText(word)).toBeInTheDocument();
    }
    expect(document.body.textContent).not.toMatch(/places? available|patient places/i);
  });

  it('has one card per district and a "Not placed" card for a service with no district', async () => {
    await loaded();
    const section = byEl('AN-LOCATIONS');
    const names = within(section)
      .getAllByRole('heading', { level: 3 })
      .map((heading) => heading.textContent);
    expect(names).toEqual(['BH15', 'BH21', 'BH7', 'Not placed']);
    expect(within(section).getByRole('button', { name: /Not placed/ })).toBeInTheDocument();
  });

  it('writes each card status as counts in words, not by colour alone', async () => {
    await loaded();
    const card = within(byEl('AN-LOCATIONS')).getByRole('button', { name: /BH15/ });
    expect(card).toHaveTextContent('1 Accepting');
    expect(card).toHaveTextContent('1 Limited');
    expect(card.querySelector('svg')).not.toBeNull();
  });

  it('has the eight service groups', async () => {
    await loaded();
    const section = byEl('AN-GROUPS');
    expect(within(section).getAllByRole('heading', { level: 3 })).toHaveLength(8);
  });

  it('lists what needs attention, with each service linked to its page, and an old figure is not spare capacity', async () => {
    await loaded();
    const pressure = byEl('LEAD-PRESSURE');
    expect(within(pressure).getByRole('link', { name: 'Ward Z' })).toHaveAttribute('href', '/analytics/services/svc-ward');
    const spare = byEl('LEAD-UNDERUSED');
    expect(within(spare).getByRole('link', { name: 'Poole UTC' })).toHaveAttribute('href', '/analytics/services/svc-poole');
    expect(within(spare).queryByText('Hospital at home')).toBeNull();
  });

  it('opens a district to its services by name, with a breadcrumb and Back', async () => {
    await loaded();
    await userEvent.click(within(byEl('AN-LOCATIONS')).getByRole('button', { name: /BH7/ }));
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' });
    expect(crumbs).toHaveTextContent('Overview');
    expect(crumbs).toHaveTextContent('BH7');
    const list = byEl('AN-DRILL-LIST');
    const names = within(list)
      .getAllByRole('link')
      .map((link) => link.textContent);
    expect(names).toEqual(['Bournemouth SDEC', 'Ward Z']);
    expect(within(list).getAllByRole('link')[0]).toHaveAttribute('href', '/analytics/services/svc-sdec');
    expect(screen.queryByText('Needs attention')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(byEl('AN-COUNTS')).toBeInTheDocument();
  });

  it('opens a status count to the services in that status, and an old figure reads unavailable', async () => {
    await loaded();
    await userEvent.click(within(byEl('AN-COUNTS')).getByRole('button', { name: /Not updated/ }));
    const list = byEl('AN-DRILL-LIST');
    expect(within(list).getByText('Hospital at home')).toBeInTheDocument();
    expect(within(list).getByText('Current capacity unavailable')).toBeInTheDocument();
  });

  it('opens a service group to its services', async () => {
    await loaded();
    await userEvent.click(within(byEl('AN-GROUPS')).getByRole('button', { name: /Care packages/ }));
    expect(within(byEl('AN-DRILL-LIST')).getByText('Wimborne reablement')).toBeInTheDocument();
  });

  it('says it could not read the overview, and shows no figures, when the read fails', async () => {
    server.use(http.get('/api/bff/analytics/overview', () => HttpResponse.json({}, { status: 503 })));
    render(<AnalyticsOverview />);
    expect(await screen.findByText(/could not be read/i)).toBeInTheDocument();
    expect(screen.queryByText('Accepting')).toBeNull();
  });

  it('has no axe violations on the overview or the drill-down', async () => {
    const { container } = await loaded();
    expect(await runAxe(container)).toHaveNoViolations();
    await userEvent.click(within(byEl('AN-LOCATIONS')).getByRole('button', { name: /BH7/ }));
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
