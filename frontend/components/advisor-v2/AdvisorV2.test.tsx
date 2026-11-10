import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { CapacityOverview } from './CapacityOverview';
import { FindService } from './FindService';
import { V2Services } from './V2Services';
import { V2Switch } from './V2Switch';

// Advisor v2 (DEC-1366): the switch, Find a Service, the capacity overview and the filtered list. Browse only.

function found(over: Record<string, unknown>) {
  return {
    serviceId: 'svc-a',
    name: 'Alpha',
    category: 'urgent-community-response',
    status: 'accepting',
    effectiveAvailable: 5,
    overBy: null,
    unitLabel: 'referrals',
    dataAgeSeconds: 1200,
    reportedAt: '2026-11-10T13:40:00Z',
    nextDueAt: '2026-11-10T15:40:00Z',
    cadence: 'every-2-hrs',
    overdue: false,
    staleWarning: false,
    figureUnavailable: false,
    lastFigure: 5,
    criteriaVersion: 1,
    fits: [],
    warnings: [],
    phone: null,
    travel: { low: 10, high: 15, source: 'Routing data' },
    ...over,
  };
}

const FIND_ANSWER = {
  generatedAt: '2026-11-10T14:00:00Z',
  notFound: false,
  services: [
    found({ serviceId: 'svc-z', name: 'Zed Team' }),
    found({ serviceId: 'svc-b', name: 'Beta Team', status: 'not-accepting', effectiveAvailable: 0, lastFigure: 0, travel: { low: 20, high: 25, source: 'x' } }),
    found({
      serviceId: 'svc-old',
      name: 'Old Report Team',
      figureUnavailable: true,
      overdue: true,
      status: 'accepting',
      lastFigure: 7,
      effectiveAvailable: 7,
      dataAgeSeconds: 14400,
      travel: null,
    }),
    found({ serviceId: 'svc-bed', name: 'Ward D', category: 'inpatient-beds', unitLabel: 'beds free', travel: null }),
  ],
};

let posted: unknown[] = [];

beforeEach(() => {
  resetCsrfCache();
  posted = [];
  server.use(
    http.post('/api/bff/advisor-v2/find', async ({ request }) => {
      posted.push(await request.json());
      return HttpResponse.json(FIND_ANSWER);
    }),
  );
});

async function search(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('Postcode'), 'DT4 8XX');
  await user.click(screen.getByRole('radio', { name: '80+' }));
  await user.click(screen.getByRole('checkbox', { name: 'Frailty' }));
  await user.click(screen.getByRole('radio', { name: 'Within 2 hrs' }));
  await user.click(screen.getByRole('button', { name: 'Find services' }));
}

describe('V2Switch', () => {
  it('is a link pair, Capacity and Find a Service, with the current one marked', () => {
    render(<V2Switch current="find" />);
    const nav = screen.getByRole('navigation', { name: 'Advisor view' });
    expect(within(nav).getByRole('link', { name: 'Find a Service' })).toHaveAttribute('aria-current', 'page');
    expect(within(nav).getByRole('link', { name: 'Capacity' })).not.toHaveAttribute('aria-current');
    expect(within(nav).getByRole('link', { name: 'Capacity' })).toHaveAttribute('href', '/advisor/v2?mode=capacity');
  });
});

describe('FindService', () => {
  it('says it opens no case and stores nothing', () => {
    render(<FindService />);
    expect(screen.getByText(/opens no case and nothing is stored/i)).toBeInTheDocument();
  });

  it('asks for a full postcode before it searches, and sends nothing without one', async () => {
    const user = userEvent.setup();
    render(<FindService />);
    await user.type(screen.getByLabelText('Postcode'), 'DT4');
    await user.click(screen.getByRole('radio', { name: '80+' }));
    await user.click(screen.getByRole('checkbox', { name: 'Frailty' }));
    await user.click(screen.getByRole('radio', { name: 'Today' }));
    await user.click(screen.getByRole('button', { name: 'Find services' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/full postcode/i);
    expect(posted).toHaveLength(0);
  });

  it('sends the postcode in a body, then shows one card per service group, by name', async () => {
    const user = userEvent.setup();
    render(<FindService />);
    await search(user);
    const groups = within(await screen.findByRole('list', { name: 'Service groups' })).getAllByRole('button');
    expect(posted[0]).toEqual({ postcode: 'DT4 8XX', ageBand: '80+', needs: ['frailty'], urgency: 'within-2-hrs' });
    expect(groups.map((group) => group.textContent)).toEqual([
      expect.stringContaining('Inpatient beds'),
      expect.stringContaining('Urgent community response'),
    ]);
    expect(within(groups[1]!).getByText('3 services')).toBeInTheDocument();
  });

  it('suggests postcodes as it is typed, as the needs form does, and fills the one picked', async () => {
    const asked: string[] = [];
    server.use(
      http.get('/api/bff/advisor/postcodes', ({ request }) => {
        asked.push(new URL(request.url).searchParams.get('prefix') ?? '');
        return HttpResponse.json({ postcodes: ['DT4 4GB', 'DT4 4GR'] });
      }),
      http.get('/api/bff/advisor/postcodes/locate', () => HttpResponse.json({ status: 'found', lat: 50.60921, lon: -2.4561 })),
    );
    const user = userEvent.setup();
    render(<FindService />);
    await user.type(screen.getByRole('combobox'), 'DT4');
    await user.click(await screen.findByRole('option', { name: 'DT4 4GR' }));
    expect(asked).toContain('DT4');
    expect(screen.getByRole('combobox')).toHaveValue('DT4 4GR');
    expect(await screen.findByText(/Found: 50\.60921, -2\.45610 \(OS Places\)\./)).toBeInTheDocument();
  });

  it('still searches when the postcode lookup cannot answer', async () => {
    server.use(
      http.get('/api/bff/advisor/postcodes', () => HttpResponse.json({}, { status: 503 })),
      http.get('/api/bff/advisor/postcodes/locate', () => HttpResponse.json({ status: 'unavailable' })),
    );
    const user = userEvent.setup();
    render(<FindService />);
    await search(user);
    expect(await screen.findByRole('list', { name: 'Service groups' })).toBeInTheDocument();
    expect(posted[0]).toMatchObject({ postcode: 'DT4 8XX' });
  });

  it('lists the services of the chosen group in travel order, with a link to each, never ranked by status', async () => {
    const user = userEvent.setup();
    render(<FindService />);
    await search(user);
    await user.click(await screen.findByRole('button', { name: /Urgent community response/ }));
    const list = screen.getByRole('list', { name: 'Services in this group' });
    const names = within(list).getAllByRole('heading', { level: 3 }).map((heading) => heading.textContent);
    expect(names).toEqual(['Zed Team', 'Beta Team', 'Old Report Team']); // travel 10, 20, none: the back end's order
    expect(within(list).getByRole('link', { name: 'Open Zed Team' })).toHaveAttribute('href', '/advisor/v2/services/svc-z');
    expect(screen.getByText('Listed by travel time. Not ranked by status.')).toBeInTheDocument();
  });

  it('can list the group by name instead', async () => {
    const user = userEvent.setup();
    render(<FindService />);
    await search(user);
    await user.click(await screen.findByRole('button', { name: /Urgent community response/ }));
    await user.click(screen.getByRole('radio', { name: 'Name' }));
    const names = within(screen.getByRole('list', { name: 'Services in this group' }))
      .getAllByRole('heading', { level: 3 })
      .map((heading) => heading.textContent);
    expect(names).toEqual(['Beta Team', 'Old Report Team', 'Zed Team']);
  });

  it('reads a late figure as "Current capacity unavailable" with the last figure small, never as spare capacity', async () => {
    const user = userEvent.setup();
    render(<FindService />);
    await search(user);
    await user.click(await screen.findByRole('button', { name: /Urgent community response/ }));
    const card = screen.getByRole('article', { name: 'Old Report Team' });
    expect(within(card).getByText('Current capacity unavailable')).toBeInTheDocument();
    expect(within(card.closest('li')!).getByText(/Last reported: 7 referrals/)).toBeInTheDocument();
    expect(within(card).queryByText('7')).toBeNull();
  });

  it('keeps the postcode out of the page address and out of browser storage', async () => {
    const user = userEvent.setup();
    render(<FindService />);
    await search(user);
    await screen.findByRole('list', { name: 'Service groups' });
    expect(window.location.href).not.toMatch(/DT4/i);
    expect(JSON.stringify({ ...window.localStorage })).not.toMatch(/DT4/i);
    expect(JSON.stringify({ ...window.sessionStorage })).not.toMatch(/DT4/i);
  });

  it('says so when nothing fits, and when the search could not run', async () => {
    const user = userEvent.setup();
    server.use(http.post('/api/bff/advisor-v2/find', () => HttpResponse.json({ ...FIND_ANSWER, services: [] })));
    render(<FindService />);
    await search(user);
    expect(await screen.findByText(/No service takes this patient/)).toBeInTheDocument();

    server.use(http.post('/api/bff/advisor-v2/find', () => HttpResponse.json({ code: 'exception' }, { status: 502 })));
    await user.click(screen.getByRole('button', { name: 'Find services' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not be searched/i);
  });

  it('has no axe violations with results showing', async () => {
    const user = userEvent.setup();
    const { container } = render(<FindService />);
    await search(user);
    await user.click(await screen.findByRole('button', { name: /Urgent community response/ }));
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

const OVERVIEW = {
  generatedAt: '2026-11-10T14:00:00Z',
  counts: { accepting: 3, limited: 2, notAccepting: 1, overCapacity: 1, notUpdated: 2 },
  attentionShown: 3,
  underPressure: [
    { serviceId: 'a', name: 'Pressed A', status: 'over-capacity', reason: '2 over normal capacity', usedPercent: 120 },
    { serviceId: 'b', name: 'Pressed B', status: 'limited', reason: 'Figure is old. Confirm before redirecting demand.', usedPercent: null },
    { serviceId: 'c', name: 'Pressed C', status: 'not-accepting', reason: 'Not accepting referrals', usedPercent: 100 },
    { serviceId: 'd', name: 'Pressed D', status: 'limited', reason: 'Limited: 1 left of 10', usedPercent: 90 },
  ],
  underutilised: [{ serviceId: 'e', name: 'Roomy E', usedPercent: 20, spare: 8, unitLabel: 'beds free' }],
  services: [
    { serviceId: 'a', name: 'Pressed A', category: 'inpatient-beds', status: 'over-capacity', effectiveAvailable: null, overBy: 2, unitLabel: 'beds free', reportedAt: '2026-11-10T13:50:00Z', figureUnavailable: false, lastFigure: 12 },
    { serviceId: 'b', name: 'Pressed B', category: 'inpatient-beds', status: 'limited', effectiveAvailable: 1, overBy: null, unitLabel: 'beds free', reportedAt: '2026-11-10T09:00:00Z', figureUnavailable: true, lastFigure: 1 },
    { serviceId: 'e', name: 'Roomy E', category: 'inpatient-beds', status: 'accepting', effectiveAvailable: 8, overBy: null, unitLabel: 'beds free', reportedAt: '2026-11-10T13:50:00Z', figureUnavailable: false, lastFigure: 8 },
  ],
};

describe('CapacityOverview', () => {
  beforeEach(() => {
    server.use(http.get('/api/bff/advisor-v2/capacity', () => HttpResponse.json(OVERVIEW)));
  });

  it('shows the five counts, each a link to its filtered list', async () => {
    render(<CapacityOverview />);
    const limited = await screen.findByRole('link', { name: /Limited/ });
    expect(limited).toHaveAttribute('href', '/advisor/v2/services?status=limited');
    expect(limited).toHaveTextContent('2');
    expect(screen.getAllByRole('link', { name: /Accepting|Limited|Over capacity|Not accepting|Not updated/ })).toHaveLength(5);
  });

  it('shows a short Needs attention list of three and counts the rest', async () => {
    render(<CapacityOverview />);
    const section = await screen.findByRole('region', { name: 'Needs attention' });
    expect(within(section).getAllByText(/Pressed/)).toHaveLength(3);
    expect(within(section).getByText('and 1 more')).toBeInTheDocument();
  });

  it('shows no percentage for an old figure under pressure and says to confirm', async () => {
    render(<CapacityOverview />);
    const row = (await screen.findByText('Pressed B')).closest('li')!;
    expect(row).toHaveTextContent('Unknown');
    expect(row).toHaveTextContent(/Confirm/);
    expect(row).not.toHaveTextContent('%');
  });

  it('lists a service with room as underutilised on a current figure, and says it is not a recommendation', async () => {
    render(<CapacityOverview />);
    const room = await screen.findByRole('region', { name: 'Underutilised' });
    expect(within(room).getByText('Roomy E')).toBeInTheDocument();
    expect(within(room).getByText(/not a recommendation/i)).toBeInTheDocument();
  });

  it('says it opens no case and stores nothing', async () => {
    render(<CapacityOverview />);
    expect(await screen.findByText(/opens no case and nothing is stored/i)).toBeInTheDocument();
  });

  it('says so when the overview could not be read', async () => {
    server.use(http.get('/api/bff/advisor-v2/capacity', () => HttpResponse.json({ code: 'exception' }, { status: 502 })));
    render(<CapacityOverview />);
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not be read/i);
  });

  it('has no axe violations', async () => {
    const { container } = render(<CapacityOverview />);
    await screen.findByRole('region', { name: 'Needs attention' });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('V2Services', () => {
  beforeEach(() => {
    server.use(http.get('/api/bff/advisor-v2/capacity', () => HttpResponse.json(OVERVIEW)));
  });

  it('lists the chosen state by name, with a link to each service, and reads an old figure as unavailable', async () => {
    render(<V2Services initial={['limited']} />);
    await waitFor(() => expect(screen.getAllByRole('article')).toHaveLength(1));
    const card = screen.getByRole('article', { name: 'Pressed B' });
    expect(within(card).getByText('Current capacity unavailable')).toBeInTheDocument();
    expect(within(card).getByRole('link', { name: 'Open Pressed B' })).toHaveAttribute('href', '/advisor/v2/services/b');
    expect(screen.getByText('Listed by name, not ranked.')).toBeInTheDocument();
  });

  it('shows all five states by name when none is chosen', async () => {
    render(<V2Services initial={[]} />);
    await waitFor(() => expect(screen.getAllByRole('article')).toHaveLength(3));
    const names = screen.getAllByRole('heading', { level: 3 }).map((heading) => heading.textContent);
    expect(names).toEqual(['Pressed A', 'Pressed B', 'Roomy E']);
  });
});
