import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { SessionTimeline } from './SessionTimeline';

const SESSION = 's-7f3a9c2e1b';
const EVENTS = [
  { kind: 'navigation', offsetMs: 0, route: '/advisor' },
  { kind: 'click', offsetMs: 44000, elementId: 'ADV-OPT-REQUEST-BTN' },
  { kind: 'friction', offsetMs: 46000, elementId: 'ADV-OPT-REQUEST-BTN', outcome: 'rage' },
  { kind: 'api', offsetMs: 46500, route: '/api/bff/bookings', durationMs: 812, status: '201', traceId: '4bf92f3577b34da6a3ce929d0e0e4736' },
];

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

describe('SessionTimeline', () => {
  it('filters to the friction rows when Friction is chosen, and asks the server for that filter', async () => {
    const requested: string[] = [];
    server.use(
      http.get(`/api/bff/console/sessions/${SESSION}/events`, ({ request }) => {
        const filter = new URL(request.url).searchParams.get('filter') ?? 'all';
        requested.push(filter);
        return HttpResponse.json({
          meta: { sessionId: SESSION, filter, count: 1 },
          standout: [],
          events: EVENTS.filter((event) => filter === 'all' || event.kind === filter),
        });
      }),
    );
    render(<SessionTimeline sessionId={SESSION} initialEvents={EVENTS} initialStandout={[]} />);

    await userEvent.click(screen.getByRole('button', { name: 'Friction' }));

    await waitFor(() => expect(requested).toContain('friction'));
    const table = await screen.findByRole('table', { name: /timeline/i });
    expect(within(table).getAllByRole('row')).toHaveLength(2);
    expect(within(table).getByText('rage', { exact: false })).toBeInTheDocument();
  });

  it('links an API row to its trace page', () => {
    render(<SessionTimeline sessionId={SESSION} initialEvents={EVENTS} initialStandout={[]} />);

    const link = screen.getByRole('link', { name: /view trace/i });
    expect(link).toHaveAttribute('href', '/console/trace/4bf92f3577b34da6a3ce929d0e0e4736');
  });

  it('says so, and does not make a link, when an API row has no trace id', () => {
    const withoutTrace = { kind: 'api', offsetMs: 46500, route: '/api/bff/bookings', durationMs: 812, status: '201' };
    render(<SessionTimeline sessionId={SESSION} initialEvents={[withoutTrace]} initialStandout={[]} />);

    expect(screen.queryByRole('link', { name: /view trace/i })).toBeNull();
    expect(screen.getByText('No trace recorded')).toBeInTheDocument();
  });

  it('offers Close session, which ends access', async () => {
    const closed = vi.fn();
    server.use(
      http.delete(`/api/bff/console/sessions/${SESSION}`, () => {
        closed();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    render(<SessionTimeline sessionId={SESSION} initialEvents={EVENTS} initialStandout={[]} />);

    await userEvent.click(screen.getByRole('button', { name: 'Close session' }));

    await waitFor(() => expect(closed).toHaveBeenCalledTimes(1));
  });

  it('passes vitest-axe', async () => {
    const { container } = render(<SessionTimeline sessionId={SESSION} initialEvents={EVENTS} initialStandout={[]} />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
