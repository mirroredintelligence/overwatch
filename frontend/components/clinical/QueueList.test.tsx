import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { clinicalBffHandlers, QUEUE_ITEMS as QUEUE_TASKS, resetClinicalBff, seenBff as seenClinical } from '@/test/msw/handlers/clinical';
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
  await waitFor(() => expect(screen.getAllByRole('article')).toHaveLength(QUEUE_TASKS.length));
}

describe('QueueList', () => {
  it('shows each request with its urgency, its reason and the note on taking one', async () => {
    render(<QueueList />);
    await queueShown();
    const now = screen.getByRole('article', { name: /Now/ });
    expect(within(now).getByText('Now')).toBeInTheDocument();
    expect(within(now).getByText('Borderline criteria')).toBeInTheDocument();
    expect(screen.getByRole('article', { name: /Within 15 min/ })).toBeInTheDocument();
    expect(screen.getByText('Once you take a request, no one else can. It returns to the queue if you do not act in 10 minutes.')).toBeInTheDocument();
  });

  it('takes a request and opens its case, carrying only the queue context the page needs', async () => {
    render(<QueueList />);
    await queueShown();
    await userEvent.click(within(screen.getAllByRole('article')[0] as HTMLElement).getByRole('button', { name: 'Take it' }));
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    const target = new URL(String(push.mock.calls[0]?.[0]), 'https://clinical.test');
    expect(target.pathname).toBe('/clinical/requests/req-4821');
    expect(target.searchParams.get('urgency')).toBe('now');
    expect(target.searchParams.get('why')).toBe('borderline-criteria');
    expect(seenClinical.some((c) => c.path === '/api/bff/clinical/requests/req-4821/take')).toBe(true);
  });

  it('says someone else has taken the request when the take is refused, and refreshes the queue', async () => {
    render(<QueueList />);
    await queueShown();
    await userEvent.click(within(screen.getByRole('article', { name: /Within 15 min/ })).getByRole('button', { name: 'Take it' }));
    expect(await screen.findByText('Someone else has taken this request.')).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
    expect(refresh).toHaveBeenCalled();
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
