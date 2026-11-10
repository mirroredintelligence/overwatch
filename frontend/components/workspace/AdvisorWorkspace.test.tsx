// Tests for the find-a-service workspace (WS-ADV, DEC-1376): the intake in the thread, the results on the canvas, the
// URL as the only navigation state, and the privacy rule. They describe the built component; against the stub every
// test fails with 'not built'.

import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import type { ReactNode } from 'react';
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
    ...over,
  };
}

const FIND_ANSWER = {
  generatedAt: '2026-11-10T14:00:00Z',
  notFound: false,
  groupTotals: { 'urgent-community-response': 5, 'inpatient-beds': 2 },
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
const BY_TRAVEL = "4 services meet this patient's criteria, sorted by travel time. Not ranked.";
const BY_NAME = "4 services meet this patient's criteria, listed by name. Not ranked.";
const SUMMARY = '65 to 79 · DT4 · Frailty · Today';
const RESULTS_URL = '/advisor/v2?mode=find&view=list';
const NEED_URL = '/advisor/v2?mode=find&view=find&step=need';
const GROUP_URL = '/advisor/v2?mode=find&view=list&group=urgent-community-response';

let posted: unknown[] = [];

beforeEach(() => {
  resetCsrfCache();
  posted = [];
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

const serviceNames = (list: HTMLElement) =>
  within(list)
    .getAllByRole('link')
    .map((link) => link.getAttribute('aria-label')?.split(',')[0]);

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

  it('WS-ADV-T04 after a successful search the page is pushed to the results list; the thread shows the count, the summary line and a Change criteria link to the need step', async () => {
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

  it('WS-ADV-T05 the group cards show "3 of 5 services"; a group pushes its group URL; there the tiles show, a Return button pushes the list without group, and a tile remembers its service', async () => {
    const user = userEvent.setup();
    renderWorkspace(<OpenedProbe />);
    await goToNeedStep(user);
    await chooseNeedAndTime(user);
    const groups = await screen.findByRole('list', { name: 'Service groups' });
    expect(within(groups).getByText('3 of 5 services')).toBeInTheDocument();
    await user.click(within(groups).getByRole('button', { name: /Urgent community response/ }));
    expect(nav.push).toHaveBeenLastCalledWith(GROUP_URL);
    const tiles = await screen.findByRole('list', { name: 'Services in this group' });
    expect(serviceNames(tiles)).toHaveLength(3);
    await user.click(within(tiles).getByRole('link', { name: /^Zed Team/ }));
    expect(openedName()).toBe('Zed Team');
    await user.click(screen.getByRole('button', { name: 'Return to service groups' }));
    expect(nav.push).toHaveBeenLastCalledWith(RESULTS_URL);
  });

  it('WS-ADV-T06 the thread chip "List by name" links to the name list; the reply says listed by name; grouped tiles are then ordered by name', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await goToNeedStep(user);
    await chooseNeedAndTime(user);
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(RESULTS_URL));
    const chip = within(screen.getByRole('list', { name: 'Suggested replies' })).getByRole('link', { name: 'List by name' });
    expect(chip).toHaveAttribute('href', '/advisor/v2?mode=find&view=list&order=name');
    go(chip.getAttribute('href') ?? '');
    expect(within(conversation()).getByText(BY_NAME)).toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: /Urgent community response/ }));
    expect(nav.push).toHaveBeenLastCalledWith('/advisor/v2?mode=find&view=list&group=urgent-community-response&order=name');
    const tiles = screen.getByRole('list', { name: 'Services in this group' });
    expect(serviceNames(tiles)).toEqual(['Beta Team', 'Old Report Team', 'Zed Team']);
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
    server.use(http.post('/api/bff/advisor-v2/find', () => HttpResponse.json({ ...FIND_ANSWER, services: [] })));
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
    await user.click(await screen.findByRole('button', { name: /Urgent community response/ }));
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
    expect(nav.replace).toHaveBeenCalledWith('/advisor/v2?mode=find&view=find&step=age');
    first.unmount();

    // A reload loses the criteria, so this half keeps one provider mounted and changes the URL instead.
    nav.replace.mockClear();
    renderWorkspace();
    await chooseAgeAndPostcode(user);
    go('/advisor/v2?mode=find&view=list');
    await waitFor(() => expect(nav.replace).toHaveBeenCalledTimes(1));
    expect(nav.replace).toHaveBeenCalledWith(NEED_URL);
  });

  it('WS-ADV-T12 view=map with complete criteria is shown as the list and does not replace the URL', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await goToNeedStep(user);
    await chooseNeedAndTime(user);
    await screen.findByRole('list', { name: 'Service groups' });
    nav.replace.mockClear();
    go('/advisor/v2?mode=find&view=map');
    expect(screen.getByRole('list', { name: 'Service groups' })).toBeInTheDocument();
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it('WS-ADV-T13 the age step, the need step and the results all pass runAxe, and only the logo image carries a style attribute', async () => {
    const user = userEvent.setup();
    const { container } = renderWorkspace();
    expect(await runAxe(container)).toHaveNoViolations();
    await goToNeedStep(user);
    expect(await runAxe(container)).toHaveNoViolations();
    await chooseNeedAndTime(user);
    await screen.findByRole('list', { name: 'Service groups' });
    expect(await runAxe(container)).toHaveNoViolations();
    const styled = [...container.querySelectorAll('[style]')];
    expect(styled.every((element) => element.tagName === 'IMG')).toBe(true);
  });
});
