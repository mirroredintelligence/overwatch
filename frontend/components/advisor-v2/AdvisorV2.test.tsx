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

// Advisor v2 (DEC-1366), built on the owner's SPoA design: the switch, Find a Service (criteria on the left, live
// results on the right), the capacity overview and the filtered list. Browse only.

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

async function criteria(user: ReturnType<typeof userEvent.setup>, postcode = 'DT4 8XX') {
  await user.type(screen.getByLabelText('Postcode'), postcode);
  await user.click(screen.getByRole('button', { name: '80+' }));
  await user.click(screen.getByRole('button', { name: 'Frailty' }));
  await user.click(screen.getByRole('button', { name: 'Within 2 hrs' }));
}

const serviceNames = (list: HTMLElement) =>
  within(list)
    .getAllByRole('link')
    .map((link) => link.getAttribute('aria-label')?.split(',')[0]);

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
  it('says it opens no case and stores nothing, and has no Find button: the results follow the criteria', () => {
    render(<FindService />);
    expect(screen.getByText(/opens no case and nothing is stored/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Find services' })).toBeNull();
    expect(screen.getByRole('heading', { level: 2, name: 'Patient criteria' })).toBeInTheDocument();
  });

  it('has the four criteria as quick steps, and asks for what is missing before it lists anything', () => {
    render(<FindService />);
    const steps = screen.getByRole('tablist', { name: 'Quick filter categories' });
    expect(within(steps).getAllByRole('tab').map((tab) => tab.textContent)).toEqual(['Age', 'Postcode', 'Need', 'Time']);
    expect(screen.getByRole('status')).toHaveTextContent(/Choose the postcode, age, need and time/);
  });

  it('sends nothing for a partial postcode, and says a full one is needed', async () => {
    const user = userEvent.setup();
    render(<FindService />);
    await criteria(user, 'DT4');
    expect(screen.getByText(/Enter a full postcode/i)).toBeInTheDocument();
    expect(posted).toHaveLength(0);
  });

  it('searches once the criteria are complete, with the postcode in a body, and lists one card per group by name', async () => {
    const user = userEvent.setup();
    render(<FindService />);
    await criteria(user);
    const groups = within(await screen.findByRole('list', { name: 'Service groups' })).getAllByRole('button');
    expect(posted).toHaveLength(1);
    expect(posted[0]).toEqual({ postcode: 'DT4 8XX', ageBand: '80+', needs: ['frailty'], urgency: 'within-2-hrs' });
    expect(groups.map((group) => group.textContent)).toEqual([
      expect.stringContaining('Inpatient beds'),
      expect.stringContaining('Urgent community response'),
    ]);
    expect(within(groups[1]!).getByText('3')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('2 service groups · 4 services');
  });

  it('opens a group with a return button and lists its services by travel, each a link, never ranked by status', async () => {
    const user = userEvent.setup();
    render(<FindService />);
    await criteria(user);
    await user.click(await screen.findByRole('button', { name: /Urgent community response/ }));
    expect(screen.getByRole('button', { name: 'Return to service groups' })).toBeInTheDocument();
    const list = screen.getByRole('list', { name: 'Services in this group' });
    expect(serviceNames(list)).toEqual(['Zed Team', 'Beta Team', 'Old Report Team']); // travel 10, 20, none
    expect(within(list).getByRole('link', { name: /^Zed Team/ })).toHaveAttribute('href', '/advisor/v2/services/svc-z');
    expect(screen.getByText('Listed by travel time. Not ranked by status.')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('3 matching services');
  });

  it('returns to the groups, and can list the group by name', async () => {
    const user = userEvent.setup();
    render(<FindService />);
    await criteria(user);
    await user.click(await screen.findByRole('button', { name: /Urgent community response/ }));
    await user.click(screen.getByRole('button', { name: 'Name' }));
    expect(serviceNames(screen.getByRole('list', { name: 'Services in this group' }))).toEqual(['Beta Team', 'Old Report Team', 'Zed Team']);
    await user.click(screen.getByRole('button', { name: 'Return to service groups' }));
    expect(screen.getByRole('list', { name: 'Service groups' })).toBeInTheDocument();
  });

  it('shows the status as a word beside its dot, not colour alone', async () => {
    const user = userEvent.setup();
    render(<FindService />);
    await criteria(user);
    await user.click(await screen.findByRole('button', { name: /Urgent community response/ }));
    const beta = within(screen.getByRole('list', { name: 'Services in this group' })).getByRole('link', { name: /^Beta Team/ });
    expect(within(beta).getByText('Not accepting')).toBeInTheDocument();
  });

  it('reads a late figure as "Current capacity unavailable" with the last figure small, never as spare capacity', async () => {
    const user = userEvent.setup();
    render(<FindService />);
    await criteria(user);
    await user.click(await screen.findByRole('button', { name: /Urgent community response/ }));
    const old = within(screen.getByRole('list', { name: 'Services in this group' })).getByRole('link', { name: /^Old Report Team/ });
    expect(within(old).getByText('Current capacity unavailable')).toBeInTheDocument();
    expect(within(old).getByText(/Last reported: 7 referrals/)).toBeInTheDocument();
    expect(within(old).queryByText('7')).toBeNull();
    expect(old.getAttribute('aria-label')).not.toMatch(/7 referrals remaining/);
  });

  it('resets the filters and the results', async () => {
    const user = userEvent.setup();
    render(<FindService />);
    await criteria(user);
    await screen.findByRole('list', { name: 'Service groups' });
    await user.click(screen.getByRole('button', { name: 'Reset filters' }));
    expect(screen.getByLabelText('Postcode')).toHaveValue('');
    expect(screen.queryByRole('list', { name: 'Service groups' })).toBeNull();
  });

  it('keeps the postcode out of the page address and out of browser storage', async () => {
    const user = userEvent.setup();
    render(<FindService />);
    await criteria(user);
    await screen.findByRole('list', { name: 'Service groups' });
    expect(window.location.href).not.toMatch(/DT4/i);
    expect(JSON.stringify({ ...window.localStorage })).not.toMatch(/DT4/i);
    expect(JSON.stringify({ ...window.sessionStorage })).not.toMatch(/DT4/i);
  });

  it('says so when nothing fits, and when the search could not run', async () => {
    const user = userEvent.setup();
    server.use(http.post('/api/bff/advisor-v2/find', () => HttpResponse.json({ ...FIND_ANSWER, services: [] })));
    render(<FindService />);
    await criteria(user);
    expect(await screen.findByText(/No service takes this patient/)).toBeInTheDocument();

    server.use(http.post('/api/bff/advisor-v2/find', () => HttpResponse.json({ code: 'exception' }, { status: 502 })));
    await user.click(screen.getByRole('button', { name: 'Today' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not be searched/i);
  });

  it('has no axe violations with results showing', async () => {
    const user = userEvent.setup();
    const { container } = render(<FindService />);
    await criteria(user);
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
    { serviceId: 'e', name: 'Roomy E', category: 'urgent-community-response', status: 'accepting', effectiveAvailable: 8, overBy: null, unitLabel: 'beds free', reportedAt: '2026-11-10T13:50:00Z', figureUnavailable: false, lastFigure: 8 },
  ],
};

describe('CapacityOverview', () => {
  beforeEach(() => {
    server.use(http.get('/api/bff/advisor-v2/capacity', () => HttpResponse.json(OVERVIEW)));
  });

  it('shows the five counts, each a link to its filtered list, with the status word beside its dot', async () => {
    render(<CapacityOverview />);
    const limited = await screen.findByRole('link', { name: /^Limited/ });
    expect(limited).toHaveAttribute('href', '/advisor/v2/services?status=limited');
    expect(limited).toHaveTextContent('2');
    expect(screen.getAllByRole('link', { name: /^(Accepting|Limited|Over capacity|Not accepting|Not updated)/ })).toHaveLength(5);
  });

  it('shows a short Needs attention list of three and counts the rest', async () => {
    render(<CapacityOverview />);
    const section = await screen.findByRole('region', { name: 'Needs attention' });
    expect(within(section).getAllByText(/^Pressed/)).toHaveLength(3);
    expect(within(section).getByText('and 1 more')).toBeInTheDocument();
  });

  it('shows no percentage for an old figure under pressure and says to confirm', async () => {
    render(<CapacityOverview />);
    const row = (await screen.findByText('Pressed B')).closest('a')!;
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

  it('has one card per service group, with its count, linking to that group list', async () => {
    render(<CapacityOverview />);
    const groups = await screen.findByRole('region', { name: 'Service groups' });
    const beds = within(groups).getByRole('link', { name: /Inpatient beds/ });
    expect(beds).toHaveAttribute('href', '/advisor/v2/services?group=inpatient-beds');
    expect(beds).toHaveTextContent('2');
  });

  it('says it opens no case and stores nothing, and shows no places total', async () => {
    render(<CapacityOverview />);
    expect(await screen.findByText(/opens no case and nothing is stored/i)).toBeInTheDocument();
    expect(screen.queryByText(/places available/i)).toBeNull();
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

  it('lists the chosen state by name, a link to each service, and reads an old figure as unavailable', async () => {
    render(<V2Services initial={['limited']} group={null} />);
    const link = await screen.findByRole('link', { name: /^Pressed B/ });
    expect(link).toHaveAttribute('href', '/advisor/v2/services/b');
    expect(within(link).getByText('Current capacity unavailable')).toBeInTheDocument();
    expect(screen.getByText('Listed by name, not ranked.')).toBeInTheDocument();
  });

  it('shows all five states by name when none is chosen', async () => {
    render(<V2Services initial={[]} group={null} />);
    await waitFor(() => expect(screen.getAllByRole('link', { name: /^(Pressed|Roomy)/ })).toHaveLength(3));
    const names = screen.getAllByRole('link', { name: /^(Pressed|Roomy)/ }).map((link) => link.getAttribute('aria-label')?.split(',')[0]);
    expect(names).toEqual(['Pressed A', 'Pressed B', 'Roomy E']);
  });

  it('shows one group when a group is named, with a breadcrumb back to Capacity', async () => {
    render(<V2Services initial={[]} group="inpatient-beds" />);
    await waitFor(() => expect(screen.getAllByRole('link', { name: /^Pressed/ })).toHaveLength(2));
    expect(screen.queryByRole('link', { name: /^Roomy/ })).toBeNull();
    expect(within(screen.getByRole('navigation', { name: 'Breadcrumb' })).getByRole('link', { name: 'Capacity' })).toHaveAttribute('href', '/advisor/v2?mode=capacity');
  });
});
