import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { ANALYTICS_OVERVIEW, ANALYTICS_OVERVIEW_AREAS } from '@/test/fixtures/analytics';
import { server } from '@/test/msw/server';
import type { AnalyticsOverview as Overview, AnalyticsService } from '@/lib/analytics/types';
import { AnalyticsOverview } from './AnalyticsOverview';

// The Analytics User's overview (DEC-1368), after the owner's Mark design (DEC-1343): the five counts, Needs attention
// directly under them as one panel, Location groups and Service groups side by side, and the drill-down. Figures
// only; no total of places; status in shapes and words. On a phone the three blocks are tabs with a short paged list.

async function loaded(overview: Overview = ANALYTICS_OVERVIEW) {
  server.use(http.get('/api/bff/analytics/overview', () => HttpResponse.json(overview)));
  const view = render(<AnalyticsOverview />);
  await waitFor(() => byEl('AN-COUNTS'));
  return view;
}

function narrow(on: boolean) {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      matches: on,
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
      onchange: null,
    }),
  });
}

afterEach(() => {
  Reflect.deleteProperty(window, 'matchMedia');
});

/** Services in `n` districts, one each: for the paged lists. */
function manyDistricts(n: number): Overview {
  const services: AnalyticsService[] = Array.from({ length: n }, (_, i) => ({
    serviceId: `svc-${i}`,
    name: `Service ${String(i).padStart(2, '0')}`,
    category: 'urgent-treatment',
    status: 'accepting',
    districts: [`BH${String(i).padStart(2, '0')}`],
    area: null,
    figureCurrent: true,
    available: 3,
    overBy: null,
    unitLabel: 'appointment slots',
    reportedAt: '2026-11-10T13:30:00Z',
  }));
  return { ...ANALYTICS_OVERVIEW, services };
}

describe('the counts', () => {
  it('are five cards in the advisor board order, each with a word, a number and "services", and no total of places', async () => {
    await loaded();
    const cards = within(byEl('AN-COUNTS')).getAllByRole('button');
    expect(cards.map((card) => card.getAttribute('data-status'))).toEqual(['accepting', 'limited', 'over-capacity', 'not-accepting', 'not-updated']);
    expect(cards[0]).toHaveTextContent('Accepting');
    expect(cards[0]).toHaveTextContent('1');
    expect(cards[0]).toHaveTextContent('service');
    expect(cards[0]?.querySelector('svg')).not.toBeNull();
    expect(document.body.textContent).not.toMatch(/places? available|patient places/i);
  });
});

describe('the layout', () => {
  it('puts Needs attention directly under the counts, then the two group blocks', async () => {
    await loaded();
    const order = ['AN-COUNTS', 'AN-ATTENTION', 'AN-LOCATIONS', 'AN-GROUPS'].map((id) => byEl(id));
    for (let i = 0; i < order.length - 1; i += 1) {
      expect(order[i]?.compareDocumentPosition(order[i + 1] as HTMLElement) ?? 0).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    }
  });

  it('carries a count pill on each block header', async () => {
    await loaded();
    expect(byEl('AN-LOCATIONS-COUNT')).toHaveTextContent('5 services');
    expect(byEl('AN-GROUPS-COUNT')).toHaveTextContent('8 groups');
    expect(byEl('AN-PRESSURE-COUNT')).toHaveTextContent('2 services');
    expect(byEl('AN-UNDERUSED-COUNT')).toHaveTextContent('1 service');
  });
});

describe('Needs attention', () => {
  it('is one panel with Under pressure and Underutilised, compact rows, each name linked to its page', async () => {
    await loaded();
    const panel = byEl('AN-ATTENTION');
    const pressure = within(byEl('AN-PRESSURE'));
    const spare = within(byEl('AN-UNDERUSED'));
    expect(panel).toContainElement(byEl('AN-PRESSURE'));
    expect(panel).toContainElement(byEl('AN-UNDERUSED'));
    expect(pressure.getByRole('link', { name: 'Ward Z' })).toHaveAttribute('href', '/analytics/services/svc-ward');
    expect(pressure.getByText('120% used')).toBeInTheDocument();
    expect(pressure.getByText('2 over normal capacity')).toBeInTheDocument();
    expect(spare.getByRole('link', { name: 'Poole UTC' })).toHaveAttribute('href', '/analytics/services/svc-poole');
    expect(spare.getByText('20% used')).toBeInTheDocument();
    expect(panel.querySelector('[data-size]')).toBeNull();
  });

  it('says Unknown, never a percentage, for an old figure, and never lists it as spare capacity', async () => {
    await loaded();
    const pressure = within(byEl('AN-PRESSURE'));
    expect(pressure.getByText('Unknown')).toBeInTheDocument();
    expect(pressure.getByText('Figure is old. Confirm before redirecting demand.')).toBeInTheDocument();
    expect(within(byEl('AN-UNDERUSED')).queryByText('Hospital at home')).toBeNull();
  });

  it('says so when a list is empty', async () => {
    await loaded({ ...ANALYTICS_OVERVIEW, underPressure: [], underutilised: [] });
    expect(within(byEl('AN-PRESSURE')).getByText('No service is under pressure.')).toBeInTheDocument();
    expect(within(byEl('AN-UNDERUSED')).getByText('No service has spare room on a current figure.')).toBeInTheDocument();
  });
});

describe('Location groups and Service groups', () => {
  it('have a card per district and a "Not placed" card, each with its count', async () => {
    await loaded();
    const section = within(byEl('AN-LOCATIONS'));
    expect(section.getAllByRole('button').map((button) => button.getAttribute('data-group'))).toEqual(['BH15', 'BH21', 'BH7', '__not-placed']);
    expect(section.getByRole('button', { name: /Not placed/ })).toHaveTextContent('1 service');
  });

  it('write each status as a count and a word beside a shape, not by colour alone', async () => {
    await loaded();
    const card = within(byEl('AN-LOCATIONS')).getByRole('button', { name: /BH15/ });
    expect(card).toHaveTextContent('1 Accepting');
    expect(card).toHaveTextContent('1 Limited');
    expect(card.querySelector('svg')).not.toBeNull();
  });

  it('show all eight service groups, each with its count', async () => {
    await loaded();
    const tiles = within(byEl('AN-GROUPS')).getAllByRole('button');
    expect(tiles).toHaveLength(8);
    expect(within(byEl('AN-GROUPS')).getByRole('button', { name: /Care packages/ })).toHaveTextContent('1 service');
  });
});

describe('on a phone', () => {
  it('shows tabs for Locations, Attention and Groups and one block at a time', async () => {
    narrow(true);
    await loaded();
    const tabs = within(screen.getByRole('tablist', { name: 'Overview sections' })).getAllByRole('tab');
    expect(tabs.map((tab) => tab.textContent)).toEqual(['Locations', 'Attention', 'Groups']);
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true');
    expect(byEl('AN-LOCATIONS')).toBeInTheDocument();
    expect(screen.queryByText('Under pressure')).toBeNull();
    await userEvent.click(tabs[1] as HTMLElement);
    expect(byEl('AN-ATTENTION')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: /Location groups/ })).toBeNull();
    await userEvent.click(tabs[2] as HTMLElement);
    expect(byEl('AN-GROUPS')).toBeInTheDocument();
  });

  it('pages a long list of locations five at a time with Previous and Next', async () => {
    narrow(true);
    await loaded(manyDistricts(7));
    const groupButtons = () => byEl('AN-LOCATIONS').querySelectorAll('button[data-group]');
    expect(groupButtons()).toHaveLength(5);
    expect(screen.getByText('1–5 of 7 locations')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(groupButtons()).toHaveLength(2);
    expect(screen.getByText('6–7 of 7 locations')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
  });

  it('does not show tabs on a wide screen: all three blocks are there', async () => {
    await loaded();
    expect(screen.queryByRole('tablist')).toBeNull();
    for (const id of ['AN-LOCATIONS', 'AN-ATTENTION', 'AN-GROUPS']) expect(byEl(id)).toBeInTheDocument();
  });
});

describe('the drill-down', () => {
  async function open(name: RegExp) {
    await loaded();
    await userEvent.click(within(byEl('AN-LOCATIONS')).getByRole('button', { name }));
  }

  it('is headed by the area name with an "N services" pill, under a breadcrumb with Back', async () => {
    await open(/BH7/);
    expect(screen.getByRole('heading', { level: 2, name: 'BH7' })).toBeInTheDocument();
    expect(byEl('AN-DRILL-COUNT')).toHaveTextContent('2 services');
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' });
    expect(crumbs).toHaveTextContent('Overview');
    expect(crumbs).toHaveTextContent('Location: BH7');
    expect(screen.queryByText('Needs attention')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(byEl('AN-COUNTS')).toBeInTheDocument();
  });

  it('shows a strip of the five status counts for the set, in words', async () => {
    await open(/BH7/);
    const strip = byEl('AN-DRILL-STRIP');
    expect(within(strip).getAllByRole('listitem').map((item) => item.textContent)).toEqual(['0Accepting', '1Limited', '1Over capacity', '0Not accepting', '0Not updated']);
  });

  it('lists the services by name in a grid of cards, each name linked to its page, with a "1–2 of 2 services" line', async () => {
    await open(/BH7/);
    const list = within(byEl('AN-DRILL-LIST'));
    expect(list.getAllByRole('link').map((link) => link.textContent)).toEqual(['Bournemouth SDEC', 'Ward Z']);
    expect(list.getAllByRole('link')[0]).toHaveAttribute('href', '/analytics/services/svc-sdec');
    expect(screen.getByText('1–2 of 2 services')).toBeInTheDocument();
  });

  it('pages more than six services six at a time', async () => {
    const services: AnalyticsService[] = Array.from({ length: 8 }, (_, i) => ({
      ...(ANALYTICS_OVERVIEW.services[0] as AnalyticsService),
      serviceId: `s${i}`,
      name: `Service ${i}`,
      districts: ['BH1'],
    }));
    server.use(http.get('/api/bff/analytics/overview', () => HttpResponse.json({ ...ANALYTICS_OVERVIEW, services })));
    render(<AnalyticsOverview />);
    await waitFor(() => byEl('AN-COUNTS'));
    await userEvent.click(within(byEl('AN-LOCATIONS')).getByRole('button', { name: /BH1/ }));
    expect(within(byEl('AN-DRILL-LIST')).getAllByRole('link')).toHaveLength(6);
    expect(screen.getByText('1–6 of 8 services')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(within(byEl('AN-DRILL-LIST')).getAllByRole('link')).toHaveLength(2);
    expect(screen.getByText('7–8 of 8 services')).toBeInTheDocument();
  });

  it('opens a status count and a service group, and an old figure reads unavailable, never a number', async () => {
    await loaded();
    await userEvent.click(within(byEl('AN-COUNTS')).getByRole('button', { name: /Not updated/ }));
    expect(screen.getByRole('heading', { level: 2, name: 'Not updated' })).toBeInTheDocument();
    expect(within(byEl('AN-DRILL-LIST')).getByText('Current capacity unavailable')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Back' }));
    await userEvent.click(within(byEl('AN-GROUPS')).getByRole('button', { name: /Care packages/ }));
    expect(within(byEl('AN-DRILL-LIST')).getByText('Wimborne reablement')).toBeInTheDocument();
  });

  it('says it has no service when the set is empty', async () => {
    await loaded({ ...ANALYTICS_OVERVIEW, services: ANALYTICS_OVERVIEW.services.filter((service) => service.status !== 'over-capacity') });
    await userEvent.click(within(byEl('AN-COUNTS')).getByRole('button', { name: /Over capacity/ }));
    expect(screen.getByText('No service here.')).toBeInTheDocument();
    expect(byEl('AN-DRILL-COUNT')).toHaveTextContent('0 services');
  });
});

describe('failure and access', () => {
  it('says it could not read the overview, and shows no figures, when the read fails', async () => {
    server.use(http.get('/api/bff/analytics/overview', () => HttpResponse.json({}, { status: 503 })));
    render(<AnalyticsOverview />);
    expect(await screen.findByText(/could not be read/i)).toBeInTheDocument();
    expect(screen.queryByText('Accepting')).toBeNull();
  });

  it('has no axe violations on the overview, the phone view or the drill-down', async () => {
    const { container, unmount } = await loaded();
    expect(await runAxe(container)).toHaveNoViolations();
    await userEvent.click(within(byEl('AN-LOCATIONS')).getByRole('button', { name: /BH7/ }));
    expect(await runAxe(container)).toHaveNoViolations();
    unmount();
    narrow(true);
    const phone = await loaded();
    expect(await runAxe(phone.container)).toHaveNoViolations();
  });
});

describe('Location groups by area (DEC-1375)', () => {
  it('shows one row per area in the order given, with its places, each service counted once, and Not placed last', async () => {
    await loaded(ANALYTICS_OVERVIEW_AREAS);
    const block = byEl('AN-LOCATIONS');
    const rows = within(block).getAllByRole('button');
    expect(rows.map((row) => row.getAttribute('data-group'))).toEqual(['area-one', 'area-two', 'network', '__not-placed']);
    expect(rows[0]).toHaveTextContent('Area One');
    expect(rows[0]).toHaveTextContent('Alpha · Beta');
    expect(rows.map((row) => /(\d+) service/.exec(row.textContent ?? '')?.[1])).toEqual(['2', '1', '1', '1']);
    expect(block).toHaveTextContent('Each service is counted once');
    expect(block).not.toHaveTextContent('counted in each');
    expect(within(block).queryByText('BH15')).toBeNull();
  });

  it('opens the area\'s own list, titled with its name, and goes back to the overview', async () => {
    const user = userEvent.setup();
    await loaded(ANALYTICS_OVERVIEW_AREAS);
    await user.click(within(byEl('AN-LOCATIONS')).getByRole('button', { name: /Area One/ }));
    expect(screen.getByRole('heading', { name: 'Area One' })).toBeInTheDocument();
    expect(byEl('AN-DRILL-COUNT')).toHaveTextContent('2 services');
    expect(within(byEl('AN-DRILL-LIST')).getAllByRole('link').map((link) => link.textContent)).toEqual(['Poole UTC', 'Ward Z']);
    expect(screen.getByText('Area: Area One')).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('covers several districts');
    await user.click(screen.getByRole('button', { name: 'Back' }));
    expect(byEl('AN-LOCATIONS')).toBeInTheDocument();
  });

  it('keeps the postcode districts when the organisation has no areas', async () => {
    await loaded(ANALYTICS_OVERVIEW);
    const rows = within(byEl('AN-LOCATIONS')).getAllByRole('button');
    expect(rows.map((row) => row.getAttribute('data-group'))).toEqual(['BH15', 'BH21', 'BH7', '__not-placed']);
  });

  it('has no axe violations with areas showing', async () => {
    const { container } = await loaded(ANALYTICS_OVERVIEW_AREAS);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
