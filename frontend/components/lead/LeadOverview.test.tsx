import { act, configure, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { OVERVIEW_NOTHING_TO_CHASE, OVERVIEW_SHIFT_LEAD } from '@/test/fixtures/lead';
import { resetLeadPosts, seenLeadPosts } from '@/test/msw/handlers/lead';
import { server } from '@/test/msw/server';
import { LeadOverview } from './LeadOverview';

// The shift lead's main page (W17, redesign LDR-01). The overview and the reminder go through the BFF, which
// the tests answer with MSW. The live stream is a stand-in that the test can send an event on.

// The first read of this page is one tick after mount; under a full parallel run that can pass the 1 s
// default of findBy, so this file waits longer for an answer (not a change to what is expected).
configure({ asyncUtilTimeout: 4000 });

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners = new Map<string, (event: MessageEvent) => void>();
  readyState = 1;
  onopen = null;
  onerror = null;
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, listener: (event: MessageEvent) => void) {
    this.listeners.set(type, listener);
  }
  close() {
    this.readyState = 2;
  }
  emit(type: string) {
    this.listeners.get(type)?.(new MessageEvent(type, { data: '' }));
  }
}

const UNAVAILABLE = () => HttpResponse.json({ code: 'unavailable', message: 'x' }, { status: 503 });
const CHASE_HEADING = '2 services need chasing';

beforeEach(() => {
  resetLeadPosts();
  FakeEventSource.instances = [];
  vi.stubGlobal('EventSource', FakeEventSource);
  document.cookie = 'overwatch_csrf=test-csrf-token';
  window.history.replaceState(null, '', '/lead');
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = 'overwatch_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT';
  window.history.replaceState(null, '', '/');
});

async function loaded() {
  const view = render(<LeadOverview />);
  await screen.findByRole('heading', { name: CHASE_HEADING });
  return view;
}

describe('LeadOverview: the busy shift', () => {
  it('has one h1, Your shift, with the time under it', async () => {
    await loaded();
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(screen.getByRole('heading', { level: 1, name: 'Your shift' })).toBeInTheDocument();
    expect(document.querySelector('time')).not.toBeNull();
  });

  it('shows the chasing count and each service that needs chasing, with the ladder inline', async () => {
    await loaded();
    expect(screen.getByRole('heading', { name: 'Virtual ward' })).toBeInTheDocument();
    expect(
      screen.getByText('Report was due 12:00. Overdue by 2 hrs 12 min. Last figure: 3 beds free.'),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/Reminder sent/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Advisor phone task/).length).toBeGreaterThan(0);
  });

  it('shows the attention counters: services to chase and reports to check, and no reviews counter without data', async () => {
    await loaded();
    expect(await screen.findByRole('group', { name: '2 services to chase, overdue now' })).toBeInTheDocument();
    expect(await screen.findByRole('group', { name: '2 reports to check, looks wrong' })).toBeInTheDocument();
    expect(screen.queryByText(/criteria reviews/i)).not.toBeInTheDocument();
  });

  it('says one service to chase in the singular', async () => {
    server.use(
      http.get('/api/bff/lead/overview', () =>
        HttpResponse.json({ ...OVERVIEW_SHIFT_LEAD, chasing: [OVERVIEW_SHIFT_LEAD.chasing[0]] }),
      ),
    );
    render(<LeadOverview />);
    expect(await screen.findByRole('group', { name: '1 service to chase, overdue now' })).toBeInTheDocument();
  });

  it('leaves out the reports-to-check counter when the flags could not be read, and still shows the page', async () => {
    server.use(http.get('/api/bff/lead/flags', UNAVAILABLE));
    await loaded();
    expect(screen.getByRole('group', { name: '2 services to chase, overdue now' })).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: /report/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows the getting-old card under the chase cards', async () => {
    await loaded();
    expect(screen.getByRole('heading', { level: 3, name: 'Reablement' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ask for an update now' })).toBeInTheDocument();
  });

  it('shows the covering rows and the system counts with their words, in the column on the right', async () => {
    await loaded();
    expect(screen.getByRole('region', { name: 'System now' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Covering today' })).toHaveTextContent('ending 4821 · cover until 20:00');
    expect(screen.getByText('9 services reporting today')).toBeInTheDocument();
    expect(screen.getByText('Accepting').nextElementSibling).toHaveTextContent('4');
  });

  it('links to the wall screens page, whatever the overview did (W9I)', async () => {
    server.use(http.get('/api/bff/lead/overview', UNAVAILABLE));
    render(<LeadOverview />);
    const nav = screen.getByRole('navigation', { name: 'Shift lead pages' });
    expect(within(nav).getByRole('link', { name: 'Wall screens' })).toHaveAttribute('href', '/lead/screens');
    await screen.findByRole('alert');
    expect(within(nav).getByRole('link', { name: 'Wall screens' })).toBeInTheDocument();
  });

  it('links to where coverage runs out, a page a lead may open', async () => {
    server.use(http.get('/api/bff/lead/overview', UNAVAILABLE));
    render(<LeadOverview />);
    const nav = screen.getByRole('navigation', { name: 'Shift lead pages' });
    expect(within(nav).getByRole('link', { name: 'Where coverage runs out' })).toHaveAttribute('href', '/planning/coverage');
    await screen.findByRole('alert');
  });

  it('shows no rows for criteria or declined cases when the data does not have them', async () => {
    await loaded();
    expect(screen.queryByRole('button', { name: /Criteria to review/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Declined despite showing capacity/ })).not.toBeInTheDocument();
  });

  it('shows the closed rows it is given, and opens one at a time', async () => {
    render(
      <LeadOverview
        disclosures={[
          { id: 'criteria', title: 'Criteria to review', hint: '2 services, the soonest in 7 days', detail: <p>Two services.</p> },
          { id: 'declined', title: 'Declined despite showing capacity', hint: '2 cases today', detail: <p>Two cases.</p> },
        ]}
      />,
    );
    await screen.findByRole('heading', { name: CHASE_HEADING });
    const first = screen.getByRole('button', { name: /Criteria to review/ });
    const second = screen.getByRole('button', { name: /Declined despite showing capacity/ });
    expect(first).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(first);
    expect(first).toHaveAttribute('aria-expanded', 'true');
    await userEvent.click(second);
    expect(second).toHaveAttribute('aria-expanded', 'true');
    expect(first).toHaveAttribute('aria-expanded', 'false');
  });

  it('shows the loading placeholders in the same layout, and says what is loading', async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.get('/api/bff/lead/overview', async () => {
        await gate;
        return HttpResponse.json(OVERVIEW_SHIFT_LEAD);
      }),
    );
    render(<LeadOverview />);
    expect(screen.getByText('Loading the services to chase.')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: CHASE_HEADING })).not.toBeInTheDocument();
    release();
    await screen.findByRole('heading', { name: CHASE_HEADING });
    expect(screen.queryByText('Loading the services to chase.')).not.toBeInTheDocument();
  });
});

describe('LeadOverview: a quiet shift', () => {
  beforeEach(() => {
    server.use(http.get('/api/bff/lead/overview', () => HttpResponse.json(OVERVIEW_NOTHING_TO_CHASE)));
  });

  it('says nothing needs chasing, never an empty card', async () => {
    render(<LeadOverview />);
    expect(await screen.findByRole('heading', { name: 'Nothing needs chasing' })).toBeInTheDocument();
    expect(screen.getByText(/Every service has reported on time\./)).toBeInTheDocument();
    expect(screen.getByText(/This page updates by itself\./)).toBeInTheDocument();
    expect(screen.queryByText('No services need chasing.')).not.toBeInTheDocument();
    expect(screen.getByRole('group', { name: '0 services to chase, overdue now' })).toBeInTheDocument();
  });

  it('keeps the right column, and offers to set up another service', async () => {
    render(<LeadOverview />);
    await screen.findByRole('heading', { name: 'Nothing needs chasing' });
    expect(screen.getByRole('region', { name: 'System now' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Covering today' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Add a service' })).toHaveAttribute('href', '/lead/services/new');
  });
});

describe('LeadOverview: a read that fails (H-330)', () => {
  it('never says nothing needs chasing when the overview could not be read', async () => {
    server.use(http.get('/api/bff/lead/overview', UNAVAILABLE));
    render(<LeadOverview />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the shift lead page.');
    expect(screen.queryByText(/Nothing needs chasing/)).not.toBeInTheDocument();
    expect(screen.queryByText('No services need chasing.')).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'System now' })).not.toBeInTheDocument();
  });

  it('offers Try again, which reads the overview again and then shows the page', async () => {
    let fail = true;
    server.use(
      http.get('/api/bff/lead/overview', () => (fail ? UNAVAILABLE() : HttpResponse.json(OVERVIEW_SHIFT_LEAD))),
    );
    render(<LeadOverview />);
    await screen.findByRole('alert');
    fail = false;
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('heading', { name: CHASE_HEADING })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  describe('after a good page', () => {
    let fail = false;
    beforeEach(() => {
      fail = false;
      server.use(
        http.get('/api/bff/lead/overview', () => (fail ? UNAVAILABLE() : HttpResponse.json(OVERVIEW_SHIFT_LEAD))),
      );
    });

    async function failTheNextRead() {
      await loaded();
      fail = true;
      await act(async () => FakeEventSource.instances[0].emit('board.updated'));
      return screen.findByRole('alert');
    }

    it('keeps the last good page and says when it is from, in an amber alert', async () => {
      const alert = await failTheNextRead();
      expect(alert).toHaveTextContent('We could not refresh this page');
      expect(alert).toHaveTextContent(/You are looking at what we had at \d\d:\d\d\. Figures may have changed\./);
      expect(screen.getByRole('heading', { name: 'Virtual ward' })).toBeInTheDocument();
      expect(screen.getByRole('heading', { name: CHASE_HEADING })).toBeInTheDocument();
      expect(screen.queryByText(/Nothing needs chasing/)).not.toBeInTheDocument();
    });

    it('switches off the actions that need fresh data, and keeps the page readable', async () => {
      await failTheNextRead();
      for (const button of screen.getAllByRole('button', { name: 'Send reminder again' })) expect(button).toBeDisabled();
      for (const button of screen.getAllByRole('button', { name: 'Enter what they told me by phone' })) expect(button).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Ask for an update now' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Try again' })).toBeEnabled();
    });

    it('switches them back on when Try again works', async () => {
      await failTheNextRead();
      fail = false;
      await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
      await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
      for (const button of screen.getAllByRole('button', { name: 'Send reminder again' })) expect(button).toBeEnabled();
      expect(screen.getByRole('button', { name: 'Ask for an update now' })).toBeEnabled();
    });
  });
});

describe('LeadOverview: acting on a service', () => {
  it('sends the reminder with the CSRF token and an idempotency key, then says it was sent', async () => {
    await loaded();
    const [first] = screen.getAllByRole('button', { name: 'Send reminder again' });
    await userEvent.click(first);
    expect(await screen.findByRole('status')).toHaveTextContent('Reminder sent');
    expect(seenLeadPosts).toHaveLength(1);
    expect(seenLeadPosts[0]).toMatchObject({
      path: '/api/bff/lead/services/s-virtual-ward/remind',
      csrf: 'test-csrf-token',
    });
    expect(seenLeadPosts[0].idempotencyKey).toBeTruthy();
  });

  it('asks the service for an update from the getting-old card', async () => {
    await loaded();
    await userEvent.click(screen.getByRole('button', { name: 'Ask for an update now' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Reminder sent');
    expect(seenLeadPosts[0].path).toBe(
      `/api/bff/lead/services/${OVERVIEW_SHIFT_LEAD.gettingOld[0].serviceId}/remind`,
    );
  });

  it('opens the phoned sheet for the service the button belongs to, with no case reference', async () => {
    await loaded();
    const [first] = screen.getAllByRole('button', { name: 'Enter what they told me by phone' });
    await userEvent.click(first);
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('What did Virtual ward tell you?')).toBeInTheDocument();
    expect(dialog.textContent ?? '').not.toMatch(/case|reference/i);
  });
});

describe('LeadOverview: a chase opens (the morph)', () => {
  async function openFirst() {
    await loaded();
    const [first] = screen.getAllByRole('button', { name: 'Enter what they told me by phone' });
    await userEvent.click(first);
    return screen.findByRole('dialog');
  }

  it('takes the chosen card to the stage with the full ladder and a Close button, and gives the state an address', async () => {
    await openFirst();
    expect(window.location.search).toBe('?chase=s-virtual-ward&sheet=phone');
    expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument();
    expect(screen.getByText('Chasing')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Suspend this service' })).toHaveAttribute(
      'href',
      '/lead/services/s-virtual-ward/suspend',
    );
  });

  it('keeps System now on screen while the sheet is open', async () => {
    await openFirst();
    expect(screen.getByRole('region', { name: 'System now' })).toBeInTheDocument();
  });

  it('puts the cards behind it out of reach: the list layer is inert and hidden from readers', async () => {
    await openFirst();
    const hidden = document.querySelector('[data-layer][inert]');
    expect(hidden).not.toBeNull();
    expect(hidden).toHaveAttribute('aria-hidden', 'true');
  });

  it('closes the sheet from Cancel and leaves the card open, then returns focus to the card button', async () => {
    await openFirst();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(window.location.search).toBe('?chase=s-virtual-ward');
    expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument();
    await waitFor(() => {
      expect(document.activeElement).toHaveAccessibleName('Enter what they told me by phone');
      expect(document.activeElement?.closest('[data-layer]')).toHaveAttribute('data-layer', 'current');
    });
  });

  it('closes the sheet from Escape', async () => {
    await openFirst();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('returns to the list from Close, and focus goes back to that service\'s button', async () => {
    await openFirst();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await userEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(window.location.search).toBe('');
    expect(screen.queryByRole('button', { name: 'Close' })).not.toBeInTheDocument();
    await waitFor(() => {
      const active = document.activeElement as HTMLElement | null;
      expect(active).toHaveAccessibleName('Enter what they told me by phone');
      expect(active?.closest('[data-service-id]')).toHaveAttribute('data-service-id', 's-virtual-ward');
    });
  });

  it('opens straight to a chase from its address, without the sheet', async () => {
    window.history.replaceState(null, '', '/lead?chase=s-ucr-east');
    render(<LeadOverview />);
    expect(await screen.findByRole('button', { name: 'Close' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'UCR East' })).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('opens straight to a chase and its sheet from the address', async () => {
    window.history.replaceState(null, '', '/lead?chase=s-ucr-east&sheet=phone');
    render(<LeadOverview />);
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('What did UCR East tell you?')).toBeInTheDocument();
  });

  it('shows the list when the address names a service that is no longer being chased', async () => {
    window.history.replaceState(null, '', '/lead?chase=s-gone');
    await loaded();
    expect(screen.queryByRole('button', { name: 'Close' })).not.toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Send reminder again' })).toHaveLength(2);
  });

  it('follows Back: the address going back to the list closes the card', async () => {
    await openFirst();
    await act(async () => {
      window.history.replaceState(null, '', '/lead');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Close' })).not.toBeInTheDocument();
  });
});

describe('LeadOverview: refresh', () => {
  it('reads the overview again when a board update arrives', async () => {
    let reads = 0;
    server.use(
      http.get('/api/bff/lead/overview', () => {
        reads += 1;
        return HttpResponse.json(OVERVIEW_NOTHING_TO_CHASE);
      }),
    );
    render(<LeadOverview />);
    await screen.findByRole('heading', { name: 'Nothing needs chasing' });
    const stream = FakeEventSource.instances[0];
    expect(stream.url).toBe('/api/bff/events');
    await act(async () => stream.emit('board.updated'));
    await waitFor(() => expect(reads).toBeGreaterThanOrEqual(2));
  });

  describe('what a screen reader is told', () => {
    let next = OVERVIEW_SHIFT_LEAD;
    beforeEach(() => {
      next = OVERVIEW_SHIFT_LEAD;
      server.use(http.get('/api/bff/lead/overview', () => HttpResponse.json(next)));
    });

    const region = (container: HTMLElement) => container.querySelector('[data-el="LEAD-ANNOUNCE"]');

    it('has a polite region that says nothing on the first read', async () => {
      const { container } = await loaded();
      expect(region(container)).toHaveAttribute('aria-live', 'polite');
      expect(region(container)).toHaveTextContent('');
    });

    it('says "A service needs chasing" when a new service starts to need chasing', async () => {
      const { container } = await loaded();
      next = {
        ...OVERVIEW_SHIFT_LEAD,
        chasing: [
          ...OVERVIEW_SHIFT_LEAD.chasing,
          { ...OVERVIEW_SHIFT_LEAD.chasing[0], serviceId: 's-new', name: 'Brand new' },
        ],
      };
      await act(async () => FakeEventSource.instances[0].emit('board.updated'));
      await waitFor(() => expect(region(container)).toHaveTextContent('A service needs chasing'));
    });

    it('says nothing when only a count changes', async () => {
      const { container } = await loaded();
      next = { ...OVERVIEW_SHIFT_LEAD, counts: { ...OVERVIEW_SHIFT_LEAD.counts, accepting: 7 }, reportingToday: 10 };
      await act(async () => FakeEventSource.instances[0].emit('board.updated'));
      await screen.findByText('10 services reporting today');
      expect(region(container)).toHaveTextContent('');
    });

    it('says nothing when a service stops needing chasing', async () => {
      const { container } = await loaded();
      next = { ...OVERVIEW_SHIFT_LEAD, chasing: [OVERVIEW_SHIFT_LEAD.chasing[0]] };
      await act(async () => FakeEventSource.instances[0].emit('board.updated'));
      await screen.findByRole('heading', { name: '1 service needs chasing' });
      expect(region(container)).toHaveTextContent('');
    });
  });
});

describe('LeadOverview: accessibility', () => {
  it('has no axe violations once loaded', async () => {
    const { container } = await loaded();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('has no axe violations on a quiet shift', async () => {
    server.use(http.get('/api/bff/lead/overview', () => HttpResponse.json(OVERVIEW_NOTHING_TO_CHASE)));
    const { container } = render(<LeadOverview />);
    await screen.findByRole('heading', { name: 'Nothing needs chasing' });
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('has no axe violations on a failed first read', async () => {
    server.use(http.get('/api/bff/lead/overview', UNAVAILABLE));
    const { container } = render(<LeadOverview />);
    await screen.findByRole('alert');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
