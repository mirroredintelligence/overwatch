import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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

  it('opens on the API event, showing what it was and how long it took', () => {
    render(<SessionTimeline sessionId={SESSION} initialEvents={EVENTS} initialStandout={[]} />);

    expect(screen.getByText('Selected: 00:46 · API')).toBeInTheDocument();
    expect(screen.getByText('The request took 812 ms.')).toBeInTheDocument();
  });

  it('links the selected API event to its trace page, and keeps the session to return to', () => {
    render(<SessionTimeline sessionId={SESSION} initialEvents={EVENTS} initialStandout={[]} />);

    const link = screen.getByRole('link', { name: /view trace/i });
    expect(link).toHaveAttribute('href', `/console/trace/4bf92f3577b34da6a3ce929d0e0e4736?session=${SESSION}`);
  });

  it('says so, and does not make a link, when the selected API event has no trace id', () => {
    const withoutTrace = { kind: 'api', offsetMs: 46500, route: '/api/bff/bookings', durationMs: 812, status: '201' };
    render(<SessionTimeline sessionId={SESSION} initialEvents={[withoutTrace]} initialStandout={[]} />);

    expect(screen.queryByRole('link', { name: /view trace/i })).toBeNull();
    expect(screen.getByText('No trace recorded for this request.')).toBeInTheDocument();
  });

  it('selects the event whose offset is pressed, and shows no trace link for a click', async () => {
    render(<SessionTimeline sessionId={SESSION} initialEvents={EVENTS} initialStandout={[]} />);

    const press = screen.getByRole('button', { name: '00:44' });
    expect(press).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(press);

    expect(press).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('Selected: 00:44 · Click')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /view trace/i })).toBeNull();
  });

  it('opens on the moment named in the link, when one is given', () => {
    render(<SessionTimeline sessionId={SESSION} initialEvents={EVENTS} initialStandout={[]} initialAt={44000} />);

    expect(screen.getByText('Selected: 00:44 · Click')).toBeInTheDocument();
  });

  it('names friction rows in words, with the mark hidden from screen readers', () => {
    render(<SessionTimeline sessionId={SESSION} initialEvents={EVENTS} initialStandout={[]} />);

    const table = screen.getByRole('table', { name: /timeline/i });
    expect(within(table).getByRole('cell', { name: 'Friction' })).toBeInTheDocument();
  });

  it('copies a link to this moment, and says so', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(<SessionTimeline sessionId={SESSION} initialEvents={EVENTS} initialStandout={[]} />);

    fireEvent.click(screen.getByRole('button', { name: 'Copy link to this moment' }));

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expect(writeText.mock.calls[0][0]).toContain(`/console/session/${SESSION}?at=46500`);
    expect(await screen.findByRole('status')).toHaveTextContent('Link copied.');
  });

  it('says so when the link could not be copied', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('denied'));
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(<SessionTimeline sessionId={SESSION} initialEvents={EVENTS} initialStandout={[]} />);

    fireEvent.click(screen.getByRole('button', { name: 'Copy link to this moment' }));

    expect(await screen.findByRole('status')).toHaveTextContent('The link could not be copied.');
  });

  it('lists what stands out, and says so when nothing does', () => {
    const { unmount } = render(
      <SessionTimeline
        sessionId={SESSION}
        initialEvents={EVENTS}
        initialStandout={[{ kind: 'friction', offsetMs: 46000, elementId: 'ADV-OPT-REQUEST-BTN', outcome: 'rage' }]}
      />,
    );
    const card = screen.getByRole('region', { name: 'What stands out' });
    expect(within(card).getByRole('listitem')).toHaveTextContent(/00:46 Friction ADV-OPT-REQUEST-BTN/);
    unmount();

    render(<SessionTimeline sessionId={SESSION} initialEvents={EVENTS} initialStandout={[]} />);
    expect(screen.getByText('Nothing stands out in this session.')).toBeInTheDocument();
  });

  it('shows an alert when the chosen filter cannot be loaded', async () => {
    server.use(
      http.get(`/api/bff/console/sessions/${SESSION}/events`, () => new HttpResponse(null, { status: 500 })),
    );
    render(<SessionTimeline sessionId={SESSION} initialEvents={EVENTS} initialStandout={[]} />);

    await userEvent.click(screen.getByRole('button', { name: 'Errors' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('The timeline could not be loaded.');
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
