import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { clinicalBffHandlers, QUEUE_ITEMS, resetClinicalBff, seenBff as seenClinical } from '@/test/msw/handlers/clinical';
import { server } from '@/test/msw/server';
import { QueueList } from './QueueList';

const { push, refresh } = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, refresh, replace: vi.fn() }) }));

beforeEach(() => {
  resetClinicalBff();
  push.mockClear();
  refresh.mockClear();
  server.use(...clinicalBffHandlers);
});

afterEach(() => {
  vi.useRealTimers();
});

async function queueShown() {
  await waitFor(() => expect(screen.getAllByRole('article')).toHaveLength(QUEUE_ITEMS.length));
}

describe('QueueList, Waiting', () => {
  it('shows each request with its urgency, one summary line of the case, and the note on taking one', async () => {
    render(<QueueList />);
    await queueShown();
    const now = screen.getByRole('article', { name: /Now/ });
    expect(within(now).getByText('Now')).toBeInTheDocument();
    expect(within(now).getByText('80+ · Frailty, Fall · NEWS2 2 · Within 2 hrs')).toBeInTheDocument();
    expect(within(now).getByText('Borderline criteria')).toBeInTheDocument();
    expect(screen.getByRole('article', { name: /Within 15 min/ })).toBeInTheDocument();
    expect(screen.getByText('Once you take a request, no one else can. It returns to the queue if you do not act in 10 minutes.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Waiting (2)' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('takes a request and opens its case by its id alone: nothing about the case is carried in the address', async () => {
    render(<QueueList />);
    await queueShown();
    await userEvent.click(within(screen.getAllByRole('article')[0] as HTMLElement).getByRole('button', { name: 'Take it' }));
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(push).toHaveBeenCalledWith('/clinical/requests/req-4821');
    expect(seenClinical.some((c) => c.path === '/api/bff/clinical/requests/req-4821/take')).toBe(true);
  });

  it('says someone else has taken the request when the take is refused, and refreshes the queue', async () => {
    render(<QueueList />);
    await queueShown();
    await userEvent.click(within(screen.getByRole('article', { name: /Within 15 min/ })).getByRole('button', { name: 'Take it' }));
    expect(await screen.findByText('Someone else has taken this request.')).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it('does not offer Take it on a request whose case could not be read, and says so', async () => {
    server.use(http.get('/api/bff/clinical/requests', () => HttpResponse.json({ items: [{ ...QUEUE_ITEMS[0], glance: null }] })));
    render(<QueueList />);
    const card = await screen.findByRole('article');
    expect(within(card).getByText('The case could not be read, so this request cannot be answered here.')).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Take it' })).not.toBeInTheDocument();
  });

  it('says when the queue could not be read, and never says the queue is empty then', async () => {
    server.use(http.get('/api/bff/clinical/requests', () => HttpResponse.json({ code: 'exception' }, { status: 503 })));
    render(<QueueList />);
    expect(await screen.findByRole('alert')).toHaveTextContent('The queue could not be read. Try again shortly.');
    expect(screen.queryByText('No requests are waiting.')).not.toBeInTheDocument();
  });

  it('refreshes the queue every 15 seconds', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let calls = 0;
    server.use(http.get('/api/bff/clinical/requests', () => {
      calls += 1;
      return HttpResponse.json({ items: [] });
    }));
    render(<QueueList />);
    await waitFor(() => expect(calls).toBe(1));
    await act(async () => {
      vi.advanceTimersByTime(15_000);
    });
    await waitFor(() => expect(calls).toBe(2));
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<QueueList />);
    await queueShown();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('QueueList, Mine and Done', () => {
  it('lists Mine from the back end, each with a link back into its case and when it returns to the queue', async () => {
    render(<QueueList />);
    await queueShown();
    await userEvent.click(screen.getByRole('button', { name: 'Mine' }));
    const card = await screen.findByRole('article', { name: /Other/ });
    expect(within(card).getByRole('link', { name: 'Open' })).toHaveAttribute('href', '/clinical/requests/req-5001');
    expect(within(card).queryByRole('button', { name: 'Take it' })).not.toBeInTheDocument();
    expect(within(card).getByText(/Returns to the queue at 14:29/)).toBeInTheDocument();
    expect(seenClinical.some((c) => c.path === '/api/bff/clinical/requests')).toBe(true);
  });

  it('lists Done with the advice given, and no note', async () => {
    render(<QueueList />);
    await queueShown();
    await userEvent.click(screen.getByRole('button', { name: 'Done' }));
    const card = await screen.findByRole('article', { name: /Within 15 min/ });
    expect(within(card).getByText('Advice given: Use another service')).toBeInTheDocument();
    expect(within(card).getByText('80+ · Frailty, Fall · NEWS2 4 · Within 2 hrs')).toBeInTheDocument();
  });

  it('has no accessibility violations on Mine', async () => {
    const { container } = render(<QueueList />);
    await queueShown();
    await userEvent.click(screen.getByRole('button', { name: 'Mine' }));
    await screen.findByRole('link', { name: 'Open' });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
