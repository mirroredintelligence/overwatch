import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { OVERVIEW_NOTHING_TO_CHASE } from '@/test/fixtures/lead';
import { resetLeadPosts, seenLeadPosts } from '@/test/msw/handlers/lead';
import { server } from '@/test/msw/server';
import { LeadOverview } from './LeadOverview';

// The shift lead's main page (W17). The overview and the reminder go through the BFF, which the
// tests answer with MSW. The live stream is a stand-in that the test can send an event on.

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

beforeEach(() => {
  resetLeadPosts();
  FakeEventSource.instances = [];
  vi.stubGlobal('EventSource', FakeEventSource);
  document.cookie = 'diucs_csrf=test-csrf-token';
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = 'diucs_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT';
});

describe('LeadOverview', () => {
  it('shows the header, the chasing count and each service that needs chasing', async () => {
    render(<LeadOverview />);
    expect(await screen.findByRole('heading', { name: '2 services need chasing' })).toBeInTheDocument();
    expect(screen.getByText('DIUCS capacity · Shift lead')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Virtual ward' })).toBeInTheDocument();
    expect(
      screen.getByText('Report was due 12:00. Overdue by 2 hrs 12 min. Last figure: 3 beds free.'),
    ).toBeInTheDocument();
  });

  it('shows the covering rows and the system counts with their words', async () => {
    render(<LeadOverview />);
    await screen.findByRole('heading', { name: '2 services need chasing' });
    expect(screen.getByText('UCR East · number ending 4821 · cover until 20:00')).toBeInTheDocument();
    expect(screen.getByText('9 services reporting today')).toBeInTheDocument();
    expect(screen.getByText('Accepting').nextElementSibling).toHaveTextContent('4');
  });

  it('says there is nothing to chase when there is nothing to chase', async () => {
    server.use(
      http.get('/api/bff/lead/overview', () => HttpResponse.json(OVERVIEW_NOTHING_TO_CHASE)),
    );
    render(<LeadOverview />);
    expect(await screen.findByText('No services need chasing.')).toBeInTheDocument();
  });

  it('never says nothing needs chasing when the overview could not be read', async () => {
    server.use(
      http.get('/api/bff/lead/overview', () =>
        HttpResponse.json({ code: 'not-built', message: 'x' }, { status: 501 }),
      ),
    );
    render(<LeadOverview />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the shift lead page.');
    expect(screen.queryByText('No services need chasing.')).not.toBeInTheDocument();
  });

  it('sends the reminder with the CSRF token and an idempotency key, then says it was sent', async () => {
    render(<LeadOverview />);
    await screen.findByRole('heading', { name: '2 services need chasing' });
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

  it('opens the phoned dialog for the service the button belongs to, with no case reference', async () => {
    render(<LeadOverview />);
    await screen.findByRole('heading', { name: '2 services need chasing' });
    const [first] = screen.getAllByRole('button', { name: 'Enter what they told me by phone' });
    await userEvent.click(first);
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/Virtual ward/)).toBeInTheDocument();
    expect(dialog.textContent ?? '').not.toMatch(/case|reference/i);
  });

  it('reads the overview again when a board update arrives', async () => {
    let reads = 0;
    server.use(
      http.get('/api/bff/lead/overview', () => {
        reads += 1;
        return HttpResponse.json(OVERVIEW_NOTHING_TO_CHASE);
      }),
    );
    render(<LeadOverview />);
    await screen.findByText('No services need chasing.');
    const stream = FakeEventSource.instances[0];
    expect(stream.url).toBe('/api/bff/events');
    await act(async () => stream.emit('board.updated'));
    await waitFor(() => expect(reads).toBeGreaterThanOrEqual(2));
  });

  it('has no axe violations once loaded', async () => {
    const { container } = render(<LeadOverview />);
    await screen.findByRole('heading', { name: '2 services need chasing' });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
