// Tests for the find-a-service workspace (WS-ADV, DEC-1376, DEC-1379): the intake in the thread, the results as one flat
// list, the list beside the map and the services that were not suitable on the canvas, the URL as the only navigation
// state, and the privacy rule. The map and the reasons are built by other components (MapPane, NotSuitableList): they are
// replaced here by stand-ins that show what they were given, so these tests cover the wiring only. jsdom cannot lay
// anything out, so how many rows fit a height is tested in ResultsList.test.tsx with a stubbed height.

import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { useState, type ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { AdvisorWorkspace } from './AdvisorWorkspace';
import { useWorkspace, WorkspaceProvider } from './WorkspaceProvider';

// The router is a small in-memory location. push and replace move it, and the page reads it through useSearchParams, as
// the browser does. The criteria live in the provider, so a test that needs them keeps one provider mounted; a hard load
// is a fresh mount with the location set first.
const nav = vi.hoisted(() => {
  const listeners = new Set<() => void>();
  const current = { search: new URLSearchParams() };
  return {
    current,
    subscribe: (listener: () => void): (() => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    go(href: string): void {
      current.search = new URLSearchParams(href.split('?')[1] ?? '');
      for (const listener of listeners) listener();
    },
    push: vi.fn<(href: string) => void>(),
    replace: vi.fn<(href: string) => void>(),
  };
});

vi.mock('next/navigation', async () => {
  const { useSyncExternalStore } = await import('react');
  return {
    useRouter: () => ({ push: nav.push, replace: nav.replace }),
    useSearchParams: () => useSyncExternalStore(nav.subscribe, () => nav.current.search),
    usePathname: () => '/advisor/v2',
  };
});

// The stand-ins keep the props they were given. The real components have their own tests.
type MapProps = { services: { serviceId: string; name: string }[]; patient: unknown; onOpen: (service: unknown) => void };
type WhyProps = {
  items: { serviceId: string; name: string }[];
  suitableCount: number;
  summaryLine: string | null;
  serviceHref: (serviceId: string) => string;
  backHref: string;
};
const seen = vi.hoisted(() => ({ map: null as MapProps | null, why: null as WhyProps | null }));

vi.mock('./MapPane', () => ({
  MapPane: (props: MapProps) => {
    seen.map = props;
    return (
      <div data-testid="map-pane">
        {props.services.map((service) => (
          <button key={service.serviceId} type="button" onClick={() => props.onOpen(service)}>
            {`Pin ${service.name}`}
          </button>
        ))}
      </div>
    );
  },
}));

vi.mock('./NotSuitableList', () => ({
  NotSuitableList: (props: WhyProps) => {
    seen.why = props;
    return (
      <div data-testid="why-list">
        <h1>{`${props.items.length} stand-in reasons`}</h1>
        {props.items.map((item) => (
          <a key={item.serviceId} href={props.serviceHref(item.serviceId)}>
            {item.name}
          </a>
        ))}
      </div>
    );
  },
}));

// The find answer, built as AdvisorV2.test.tsx builds it.
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
    position: { lat: 50.7, lon: -2.4 },
    coverage: { districts: [], circle: null },
    ...over,
  };
}

const FIND_ANSWER = {
  generatedAt: '2026-11-10T14:00:00Z',
  notFound: false,
  groupTotals: { 'urgent-community-response': 5, 'inpatient-beds': 2 },
  notSuitable: [
    { serviceId: 'ns-1', name: 'North Beds', category: 'inpatient-beds', status: 'over-capacity', reasons: ['Outside the catchment'], position: null },
    { serviceId: 'ns-2', name: 'Purbeck Home Care', category: 'urgent-community-response', status: 'accepting', reasons: ['Does not take this age band'], position: null },
  ],
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

const POSTCODE = 'DT4 8XX';
const HIDDEN_KEY_SUFFIX = ':workspace.assistant.hidden';
const INTAKE_MESSAGE = "Let's find a service for your patient. Two short steps, then I will show who can take them.";
const NEED_QUESTION = 'What does the patient need, and by when?';
const FAILED = 'The services could not be searched. Change a choice to try again, or phone the services.';
const NONE = 'No service takes this patient on its criteria. Phone to confirm, or change the criteria.';
const BY_TRAVEL = "4 services meet this patient's criteria, sorted by travel time. Not ranked. 2 were not suitable, and I can say why.";
const BY_NAME = "4 services meet this patient's criteria, listed by name. Not ranked.";
const MAP_REPLY = 'Here is the map. Visiting services show the area they cover; sites show where they are. Tap a service to open it, or ask:';
const WHY_REPLY = '2 services were not suitable for this patient. Each has its reason, and nothing is hidden.';
const SUMMARY = '65 to 79 · DT4 · Frailty · Today';
const RESULTS_URL = '/advisor/v2?mode=find&view=list';
const MAP_URL = '/advisor/v2?mode=find&view=map';
const WHY_URL = '/advisor/v2?mode=find&view=why';
const NEED_URL = '/advisor/v2?mode=find&view=find&step=need';
const AGE_URL = '/advisor/v2?mode=find&view=find&step=age';

let posted: unknown[] = [];

beforeEach(() => {
  resetCsrfCache();
  posted = [];
  seen.map = null;
  seen.why = null;
  window.localStorage.clear();
  window.sessionStorage.clear();
  nav.current.search = new URLSearchParams();
  nav.push.mockReset();
  nav.push.mockImplementation((href) => nav.go(href));
  nav.replace.mockReset();
  nav.replace.mockImplementation((href) => nav.go(href));
  server.use(
    http.get('/api/bff/advisor/postcodes', () => HttpResponse.json({ postcodes: [POSTCODE] })),
    http.get('/api/bff/advisor/postcodes/locate', () => HttpResponse.json({ status: 'found', lat: 50.60921, lon: -2.4561 })),
    http.post('/api/bff/advisor-v2/find', async ({ request }) => {
      posted.push(await request.json());
      return HttpResponse.json(FIND_ANSWER);
    }),
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function renderWorkspace(extra: ReactNode = null) {
  return render(
    <WorkspaceProvider role="advisor-v2">
      <AdvisorWorkspace />
      {extra}
    </WorkspaceProvider>,
  );
}

// A probe inside the provider: it shows the service the provider remembers (the opened service).
function OpenedProbe() {
  const { opened } = useWorkspace();
  return <span data-probe="opened">{opened?.serviceName ?? 'none'}</span>;
}

const openedName = () => document.querySelector('[data-probe="opened"]')?.textContent;
const thread = () => screen.getByRole('complementary', { name: 'Assistant' });
const conversation = () => within(thread()).getByRole('log', { name: 'Conversation' });
const canvas = () => screen.getByRole('main', { name: 'Canvas' });
const criteria = () => screen.getByRole('region', { name: 'Criteria' });

const NAMES = ['Zed Team', 'Beta Team', 'Old Report Team', 'Ward D'];
// The names of the rows of a list, in order: each row is one link whose text starts with the service's name.
const serviceNames = (list: HTMLElement) =>
  within(list)
    .getAllByRole('link')
    .map((link) => NAMES.find((name) => link.textContent?.startsWith(name)));
const resultsList = () => screen.getByRole('list', { name: 'Matching services' });

function go(href: string): void {
  act(() => {
    nav.go(href);
  });
}

async function chooseAgeAndPostcode(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: '65 to 79' }));
  await user.type(screen.getByLabelText('Postcode'), 'DT4');
  await user.click(await screen.findByRole('option', { name: POSTCODE }));
}

async function goToNeedStep(user: ReturnType<typeof userEvent.setup>) {
  await chooseAgeAndPostcode(user);
  await user.click(screen.getByRole('button', { name: 'Next' }));
}

async function chooseNeedAndTime(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Frailty' }));
  await user.click(screen.getByRole('button', { name: 'Today' }));
}

// The whole intake, ending on the results list.
async function reachResults(user: ReturnType<typeof userEvent.setup>) {
  await goToNeedStep(user);
  await chooseNeedAndTime(user);
  await screen.findByRole('list', { name: 'Matching services' });
}

describe('AdvisorWorkspace (WS-ADV)', () => {
  it('WS-ADV-T01 hard load with no parameters shows the frame "Find a service", the assistant intake, the age card, criteria "Not set" four times and no navigation landmark', async () => {
    renderWorkspace();
    expect(within(screen.getByRole('banner')).getByText('Find a service')).toBeInTheDocument();
    expect(within(conversation()).getByText(INTAKE_MESSAGE)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Step 1 of 2 · Age and postcode' })).toBeInTheDocument();
    expect(within(criteria()).getAllByText(/Not set/)).toHaveLength(4);
    expect(within(canvas()).getByRole('status')).toHaveTextContent('Choose the postcode, age, need and time to list services.');
    expect(screen.queryByRole('navigation')).toBeNull();
  });

  it('WS-ADV-T02 choosing 65 to 79 and accepting a full postcode enables Next; Next pushes the need step; the thread shows "65 to 79 · DT4" and the need question; the full postcode leaves the page', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await user.click(screen.getByRole('button', { name: '65 to 79' }));
    await user.type(screen.getByLabelText('Postcode'), 'DT4');
    await user.click(await screen.findByRole('option', { name: POSTCODE }));
    const next = screen.getByRole('button', { name: 'Next' });
    expect(next).not.toHaveAttribute('aria-disabled', 'true');
    await user.click(next);
    expect(nav.push).toHaveBeenCalledWith(NEED_URL);
    expect(within(conversation()).getByText('65 to 79 · DT4')).toHaveAttribute('data-from', 'person');
    expect(within(conversation()).getByText(NEED_QUESTION)).toHaveAttribute('data-from', 'assistant');
    expect(within(criteria()).getByText('DT4')).toBeInTheDocument();
    expect(screen.queryByRole('combobox')).toBeNull();
    expect(screen.queryByText(new RegExp(POSTCODE))).toBeNull();
  });

  it('WS-ADV-T03 on the need step the search runs once, 250 ms after the criteria are complete, with the postcode in the body; there is no Find button', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await goToNeedStep(user);
    // shouldAdvanceTime keeps user-event's own waits moving (the repo's other tests do the same); with it the strict
    // 249 ms boundary cannot be asserted, so the debounce is shown by "no request right after the second click, one
    // request once at least 250 ms have passed".
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const timed = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await timed.click(screen.getByRole('button', { name: 'Frailty' }));
    expect(posted).toHaveLength(0);
    await timed.click(screen.getByRole('button', { name: 'Today' }));
    expect(posted).toHaveLength(0);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    await vi.waitFor(() => expect(posted).toHaveLength(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(posted).toEqual([{ postcode: POSTCODE, ageBand: '65-79', needs: ['frailty'], urgency: 'today' }]);
    expect(screen.queryByRole('button', { name: /find/i })).toBeNull();
  });

  it('WS-ADV-T04 after a successful search the page is pushed to the results list; the thread shows the count, the not-suitable count, the summary line and a Change criteria link to the need step', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await goToNeedStep(user);
    await chooseNeedAndTime(user);
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(RESULTS_URL));
    expect(posted).toHaveLength(1);
    expect(within(conversation()).getByText(BY_TRAVEL)).toBeInTheDocument();
    expect(within(thread()).getByText('Criteria set')).toBeInTheDocument();
    expect(within(thread()).getByText(SUMMARY)).toBeInTheDocument();
    expect(within(thread()).getByRole('link', { name: 'Change criteria' })).toHaveAttribute('href', NEED_URL);
  });

  it("WS-ADV-T05 the results are one flat list in the back end's order under \"4 services meet this patient's criteria\", with no group cards and no Return button; a row links to its page and remembers its service", async () => {
    const user = userEvent.setup();
    renderWorkspace(<OpenedProbe />);
    await reachResults(user);
    const list = resultsList();
    expect(within(canvas()).getByRole('heading', { level: 1, name: "4 services meet this patient's criteria" })).toBeInTheDocument();
    expect(within(canvas()).getByText('Sorted by travel time. Not ranked.')).toBeInTheDocument();
    expect(serviceNames(list)).toEqual(['Zed Team', 'Beta Team', 'Old Report Team', 'Ward D']);
    expect(screen.queryByRole('list', { name: 'Service groups' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Return to service groups' })).toBeNull();
    const row = within(list).getByRole('link', { name: /^Zed Team/ });
    expect(row).toHaveAttribute('href', '/advisor/v2/services/svc-z');
    await user.click(row);
    expect(openedName()).toBe('Zed Team');
  });

  it('WS-ADV-T06 the thread chip "List by name" links to the name list; the reply says listed by name; the flat list is then ordered by name', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await reachResults(user);
    const chip = within(screen.getByRole('list', { name: 'Suggested replies' })).getByRole('link', { name: 'List by name' });
    expect(chip).toHaveAttribute('href', '/advisor/v2?mode=find&view=list&order=name');
    go(chip.getAttribute('href') ?? '');
    expect(within(conversation()).getByText(BY_NAME)).toBeInTheDocument();
    expect(serviceNames(resultsList())).toEqual(['Beta Team', 'Old Report Team', 'Ward D', 'Zed Team']);
    expect(within(canvas()).getByText('Listed by name. Not ranked.')).toBeInTheDocument();
  });

  it('WS-ADV-T07 a failed search shows the alert and the same sentence as the thread reply', async () => {
    server.use(http.post('/api/bff/advisor-v2/find', () => HttpResponse.json({ code: 'exception' }, { status: 500 })));
    const user = userEvent.setup();
    renderWorkspace();
    await goToNeedStep(user);
    await chooseNeedAndTime(user);
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(RESULTS_URL));
    expect(await screen.findByRole('alert')).toHaveTextContent(FAILED);
    expect(within(conversation()).getByText(FAILED)).toBeInTheDocument();
  });

  it('WS-ADV-T08 an answer with no services shows the note on the canvas and the same sentence as the thread reply', async () => {
    server.use(http.post('/api/bff/advisor-v2/find', () => HttpResponse.json({ ...FIND_ANSWER, services: [], notSuitable: [] })));
    const user = userEvent.setup();
    renderWorkspace();
    await goToNeedStep(user);
    await chooseNeedAndTime(user);
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(RESULTS_URL));
    expect(within(canvas()).getByText(NONE)).toBeInTheDocument();
    expect(within(conversation()).getByText(NONE)).toBeInTheDocument();
  });

  it('WS-ADV-T09 privacy: no URL pushed or replaced has an age, postcode, need or when key or the district in it; storage is written only for the hidden flag; the find body is the only one with the postcode', async () => {
    const user = userEvent.setup();
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    renderWorkspace();
    await goToNeedStep(user);
    await chooseNeedAndTime(user);
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(RESULTS_URL));
    await user.click(await screen.findByRole('button', { name: 'List and map' }));
    await user.click(await screen.findByRole('button', { name: 'List' }));
    await user.click(screen.getByRole('button', { name: 'Hide the assistant' }));
    const urls = [...nav.push.mock.calls, ...nav.replace.mock.calls].map(([href]) => href);
    expect(urls.length).toBeGreaterThan(0);
    for (const href of urls) {
      const keys = [...new URL(href, 'http://workspace.test').searchParams.keys()];
      expect(keys.filter((key) => ['age', 'postcode', 'need', 'when'].includes(key))).toEqual([]);
      expect(href).not.toContain('DT4');
    }
    expect(setItem.mock.calls.length).toBeGreaterThan(0);
    expect(setItem.mock.calls.every(([key]) => key.startsWith('overwatch:v1:') && key.endsWith(HIDDEN_KEY_SUFFIX))).toBe(true);
    expect(posted).toHaveLength(1);
    expect(posted[0]).toMatchObject({ postcode: POSTCODE });
  });

  it('WS-ADV-T10 Hide removes the drawer and shows "Show the assistant"; Show restores the same messages; a remounted provider stays hidden', async () => {
    const user = userEvent.setup();
    const first = renderWorkspace();
    const before = conversation().textContent;
    await user.click(screen.getByRole('button', { name: 'Hide the assistant' }));
    expect(screen.queryByRole('complementary', { name: 'Assistant' })).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Show the assistant' }));
    expect(conversation().textContent).toBe(before);
    await user.click(screen.getByRole('button', { name: 'Hide the assistant' }));
    first.unmount();
    renderWorkspace();
    expect(screen.getByRole('button', { name: 'Show the assistant' })).toBeInTheDocument();
    expect(screen.queryByRole('complementary', { name: 'Assistant' })).toBeNull();
  });

  it('WS-ADV-T11 a hard load at view=list with no criteria replaces once with the age step; with an age and a full postcode but no need, replaces once with the need step', async () => {
    const user = userEvent.setup();
    nav.current.search = new URLSearchParams('view=list');
    const first = renderWorkspace();
    await waitFor(() => expect(nav.replace).toHaveBeenCalledTimes(1));
    expect(nav.replace).toHaveBeenCalledWith(AGE_URL);
    first.unmount();

    // A reload loses the criteria, so this half keeps one provider mounted and changes the URL instead.
    nav.replace.mockClear();
    renderWorkspace();
    await chooseAgeAndPostcode(user);
    go('/advisor/v2?mode=find&view=list');
    await waitFor(() => expect(nav.replace).toHaveBeenCalledTimes(1));
    expect(nav.replace).toHaveBeenCalledWith(NEED_URL);
  });

  it('WS-ADV-T12 the "Show it as" switch has List and List and map as buttons, the current one pressed; List and map pushes the map URL, List pushes the list URL, both with only view and order', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await reachResults(user);
    const switcher = within(canvas()).getByRole('group', { name: 'Show it as' });
    expect(within(switcher).getByRole('button', { name: 'List' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(switcher).getByRole('button', { name: 'List and map' })).toHaveAttribute('aria-pressed', 'false');
    await user.click(within(switcher).getByRole('button', { name: 'List and map' }));
    expect(nav.push).toHaveBeenLastCalledWith(MAP_URL);
    const onMap = within(canvas()).getByRole('group', { name: 'Show it as' });
    expect(within(onMap).getByRole('button', { name: 'List and map' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(onMap).getByRole('button', { name: 'List' })).toHaveAttribute('aria-pressed', 'false');
    await user.click(within(onMap).getByRole('button', { name: 'List' }));
    expect(nav.push).toHaveBeenLastCalledWith(RESULTS_URL);
    expect(within(canvas()).getByRole('heading', { level: 1, name: "4 services meet this patient's criteria" })).toBeInTheDocument();
  });

  it('WS-ADV-T13 the age step, the need step, the list, the map and the reasons all pass runAxe, and only the logo image carries a style attribute', async () => {
    const user = userEvent.setup();
    const { container } = renderWorkspace();
    expect(await runAxe(container)).toHaveNoViolations();
    await goToNeedStep(user);
    expect(await runAxe(container)).toHaveNoViolations();
    await chooseNeedAndTime(user);
    await screen.findByRole('list', { name: 'Matching services' });
    expect(await runAxe(container)).toHaveNoViolations();
    go(MAP_URL);
    expect(await screen.findByTestId('map-pane')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
    go(WHY_URL);
    expect(await screen.findByTestId('why-list')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
    const styled = [...container.querySelectorAll('[style]')];
    expect(styled.every((element) => element.tagName === 'IMG')).toBe(true);
  });

  it('WS-ADV-T14 each row shows the name, the group, when it was updated, the status as a word, and the figure with its unit; a figure that is not current shows "?" and "Unknown"; no delivery mode, demonstration text or place is shown', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await reachResults(user);
    const zed = within(resultsList()).getByRole('link', { name: /^Zed Team/ });
    expect(within(zed).getByText('Urgent community response · updated 20 min ago')).toBeInTheDocument();
    expect(within(zed).getByText('Accepting')).toBeInTheDocument();
    expect(within(zed).getByText('5')).toBeInTheDocument();
    expect(within(zed).getByText('Referrals')).toBeInTheDocument();
    expect(within(zed).getByText('Open')).toBeInTheDocument();
    const beta = within(resultsList()).getByRole('link', { name: /^Beta Team/ });
    expect(within(beta).getByText('Not accepting')).toBeInTheDocument();
    expect(within(beta).getByText('0')).toBeInTheDocument();
    const old = within(resultsList()).getByRole('link', { name: /^Old Report Team/ });
    expect(within(old).getByText('?')).toBeInTheDocument();
    expect(within(old).getByText('Unknown')).toBeInTheDocument();
    expect(within(old).getByText('Current capacity unavailable')).toBeInTheDocument();
    expect(within(old).getByText(/capacity report overdue · updated 4 hrs ago/)).toBeInTheDocument();
    expect(within(old).queryByText('7')).toBeNull();
    expect(within(canvas()).queryByText(/Visits the patient|Goes to a place|Remote|demonstration|Dorset/i)).toBeNull();
  });

  it('WS-ADV-T15 view=map shows the list beside the map: "4 services", the compact rows, and the map given the services in list order, the patient\'s place from the postcode lookup, and an open handler; it does not replace the URL', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await reachResults(user);
    nav.replace.mockClear();
    go(MAP_URL);
    expect(await screen.findByTestId('map-pane')).toBeInTheDocument();
    expect(nav.replace).not.toHaveBeenCalled();
    expect(within(canvas()).getByRole('heading', { level: 1, name: '4 services' })).toBeInTheDocument();
    expect(serviceNames(resultsList())).toEqual(['Zed Team', 'Beta Team', 'Old Report Team', 'Ward D']);
    expect(within(resultsList()).getAllByText('Accepting · 5')).toHaveLength(2);
    expect(seen.map?.services.map((service) => service.name)).toEqual(['Zed Team', 'Beta Team', 'Old Report Team', 'Ward D']);
    expect(seen.map?.patient).toEqual({ lat: 50.60921, lon: -2.4561 });
  });

  it('WS-ADV-T16 the map gets patient null when the postcode could not be placed, and never a postcode', async () => {
    server.use(http.get('/api/bff/advisor/postcodes/locate', () => HttpResponse.json({ status: 'not-found' })));
    const user = userEvent.setup();
    renderWorkspace();
    await reachResults(user);
    go(MAP_URL);
    expect(await screen.findByTestId('map-pane')).toBeInTheDocument();
    expect(seen.map?.patient).toBeNull();
    expect(JSON.stringify(seen.map?.patient)).not.toContain('DT4');
  });

  it('WS-ADV-T17 choosing a service on the map remembers it for the thread and pushes its page', async () => {
    const user = userEvent.setup();
    renderWorkspace(<OpenedProbe />);
    await reachResults(user);
    go(MAP_URL);
    await user.click(await screen.findByRole('button', { name: 'Pin Beta Team' }));
    expect(openedName()).toBe('Beta Team');
    expect(nav.push).toHaveBeenLastCalledWith('/advisor/v2/services/svc-b');
  });

  it('WS-ADV-T18 view=why shows the services that were not suitable, given the list, the count of suitable services, the summary line, a service link and the results link', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await reachResults(user);
    nav.replace.mockClear();
    go(WHY_URL);
    expect(await screen.findByTestId('why-list')).toBeInTheDocument();
    expect(nav.replace).not.toHaveBeenCalled();
    expect(within(screen.getByRole('banner')).getByText('Not suitable, and why')).toBeInTheDocument();
    expect(seen.why?.items.map((item) => item.name)).toEqual(['North Beds', 'Purbeck Home Care']);
    expect(seen.why?.suitableCount).toBe(4);
    expect(seen.why?.summaryLine).toBe(SUMMARY);
    expect(seen.why?.serviceHref('ns-1')).toBe('/advisor/v2/services/ns-1');
    expect(seen.why?.backHref).toBe(RESULTS_URL);
    expect(screen.queryByRole('list', { name: 'Matching services' })).toBeNull();
  });

  it('WS-ADV-T19 the thread chips "List and map" and "Why were 2 not suitable?" link to the map and the reasons; on each the thread shows its turn and its own chips', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await reachResults(user);
    const chips = () => within(screen.getByRole('list', { name: 'Suggested replies' }));
    expect(chips().getByRole('link', { name: 'List and map' })).toHaveAttribute('href', MAP_URL);
    expect(chips().getByRole('link', { name: 'Why were 2 not suitable?' })).toHaveAttribute('href', WHY_URL);

    go(MAP_URL);
    await screen.findByTestId('map-pane');
    expect(within(conversation()).getByText('List and map')).toHaveAttribute('data-from', 'person');
    expect(within(conversation()).getByText(MAP_REPLY)).toHaveAttribute('data-from', 'assistant');
    expect(chips().getByRole('link', { name: 'Why were 2 not suitable?' })).toHaveAttribute('href', WHY_URL);
    expect(chips().getByRole('link', { name: 'Back to the list' })).toHaveAttribute('href', RESULTS_URL);

    go(WHY_URL);
    await screen.findByTestId('why-list');
    expect(within(conversation()).getByText('Why were 2 not suitable?')).toHaveAttribute('data-from', 'person');
    expect(within(conversation()).getByText(WHY_REPLY)).toHaveAttribute('data-from', 'assistant');
    expect(chips().getByRole('link', { name: 'Back to the 4 suitable services' })).toHaveAttribute('href', RESULTS_URL);
  });

  it('WS-ADV-T20 one service not suitable reads in the singular, and with none the thread offers no reasons chip', async () => {
    server.use(http.post('/api/bff/advisor-v2/find', () => HttpResponse.json({ ...FIND_ANSWER, notSuitable: FIND_ANSWER.notSuitable.slice(0, 1) })));
    const user = userEvent.setup();
    renderWorkspace();
    await reachResults(user);
    expect(within(conversation()).getByText(/1 was not suitable, and I can say why\./)).toBeInTheDocument();
    expect(within(screen.getByRole('list', { name: 'Suggested replies' })).getByRole('link', { name: 'Why was 1 not suitable?' })).toBeInTheDocument();
    go(WHY_URL);
    await screen.findByTestId('why-list');
    expect(within(conversation()).getByText('1 service was not suitable for this patient. Each has its reason, and nothing is hidden.')).toBeInTheDocument();
  });

  it('WS-ADV-T21 with nothing not suitable the results turn has no reasons chip', async () => {
    server.use(http.post('/api/bff/advisor-v2/find', () => HttpResponse.json({ ...FIND_ANSWER, notSuitable: [] })));
    const user = userEvent.setup();
    renderWorkspace();
    await reachResults(user);
    const replies = within(screen.getByRole('list', { name: 'Suggested replies' }));
    expect(replies.queryByRole('link', { name: /not suitable/ })).toBeNull();
    expect(replies.getByRole('link', { name: 'List and map' })).toBeInTheDocument();
  });

  it('WS-ADV-T22 a hard load at view=map or view=why with no criteria replaces once with the age step; with an age and a full postcode but no need, with the need step', async () => {
    const user = userEvent.setup();
    for (const view of ['map', 'why']) {
      nav.replace.mockClear();
      nav.current.search = new URLSearchParams(`view=${view}`);
      const mounted = renderWorkspace();
      await waitFor(() => expect(nav.replace).toHaveBeenCalledTimes(1));
      expect(nav.replace).toHaveBeenCalledWith(AGE_URL);
      expect(screen.queryByTestId('map-pane')).toBeNull();
      expect(screen.queryByTestId('why-list')).toBeNull();
      mounted.unmount();
    }
    nav.replace.mockClear();
    renderWorkspace();
    await chooseAgeAndPostcode(user);
    go(MAP_URL);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledTimes(1));
    expect(nav.replace).toHaveBeenCalledWith(NEED_URL);
  });

  it('WS-ADV-T23 a failed search shows the alert and the failed sentence on the map and reasons views, and no map or reasons list', async () => {
    server.use(http.post('/api/bff/advisor-v2/find', () => HttpResponse.json({ code: 'exception' }, { status: 500 })));
    const user = userEvent.setup();
    renderWorkspace();
    await goToNeedStep(user);
    await chooseNeedAndTime(user);
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(RESULTS_URL));
    for (const href of [MAP_URL, WHY_URL]) {
      go(href);
      expect(await screen.findByRole('alert')).toHaveTextContent(FAILED);
      expect(within(conversation()).getByText(FAILED)).toBeInTheDocument();
      expect(screen.queryByTestId('map-pane')).toBeNull();
      expect(screen.queryByTestId('why-list')).toBeNull();
    }
  });

  it('WS-ADV-T24 an answer with no services but some not suitable shows the reasons, and the map view shows the note', async () => {
    server.use(http.post('/api/bff/advisor-v2/find', () => HttpResponse.json({ ...FIND_ANSWER, services: [] })));
    const user = userEvent.setup();
    renderWorkspace();
    await goToNeedStep(user);
    await chooseNeedAndTime(user);
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(RESULTS_URL));
    expect(await within(canvas()).findByText(NONE)).toBeInTheDocument();
    expect(within(screen.getByRole('list', { name: 'Suggested replies' })).getByRole('link', { name: 'Why were 2 not suitable?' })).toBeInTheDocument();
    go(WHY_URL);
    expect(await screen.findByTestId('why-list')).toBeInTheDocument();
    expect(seen.why?.suitableCount).toBe(0);
    go(MAP_URL);
    expect(await within(canvas()).findByText(NONE)).toBeInTheDocument();
    expect(screen.queryByTestId('map-pane')).toBeNull();
  });

  it('WS-ADV-T25 the postcode could not be placed: the list shows the note and the thread says there is no travel time', async () => {
    server.use(http.post('/api/bff/advisor-v2/find', () => HttpResponse.json({ ...FIND_ANSWER, notFound: true })));
    const user = userEvent.setup();
    renderWorkspace();
    await reachResults(user);
    expect(within(canvas()).getByText('The postcode could not be placed, so no travel time is shown. Services are listed by name.')).toBeInTheDocument();
    expect(within(conversation()).getByText(/The postcode could not be placed, so there is no travel time/)).toBeInTheDocument();
  });

  it('WS-ADV-T26 coming back to the results after the page was left (a service was opened) searches again with the criteria still in memory, and stays on the results', async () => {
    const user = userEvent.setup();
    function Away() {
      const [away, setAway] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setAway((value) => !value)}>
            toggle page
          </button>
          {away ? null : <AdvisorWorkspace />}
        </>
      );
    }
    render(
      <WorkspaceProvider role="advisor-v2">
        <Away />
      </WorkspaceProvider>,
    );
    await goToNeedStep(user);
    await chooseNeedAndTime(user);
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(RESULTS_URL));
    expect(await screen.findByRole('list', { name: 'Matching services' })).toBeInTheDocument();
    expect(posted).toHaveLength(1);

    // Leave (a service page is opened), then come back to the results URL.
    await user.click(screen.getByRole('button', { name: 'toggle page' }));
    nav.push.mockClear();
    await user.click(screen.getByRole('button', { name: 'toggle page' }));
    expect(await screen.findByRole('list', { name: 'Matching services' })).toBeInTheDocument();
    expect(posted).toHaveLength(2);
    expect(nav.push).not.toHaveBeenCalled();
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it('WS-ADV-T27 Back is always there: the first step leaves to the capacity overview, the need step goes back to the age step', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    expect(screen.getByRole('link', { name: 'Back' })).toHaveAttribute('href', '/advisor/v2');
    await goToNeedStep(user);
    expect(screen.getByRole('link', { name: 'Back' })).toHaveAttribute('href', AGE_URL);
  });
});
