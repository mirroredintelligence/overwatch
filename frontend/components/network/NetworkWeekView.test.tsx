import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { WEEK_BODY } from '@/test/fixtures/network';
import { networkBffHandlers, resetNetworkBff, seenNetworkBff } from '@/test/msw/handlers/networkBff';
import { server } from '@/test/msw/server';
import { parseWeek } from '@/lib/network/parse';
import { NetworkWeekView } from './NetworkWeekView';

// TEN-082: the network week page. It reads the last complete week (a Monday to a Sunday) and lets the viewer
// go to an earlier week, and back, but never past the last complete one.

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2026-10-28T10:00:00Z'));
  resetNetworkBff();
});
afterEach(() => vi.useRealTimers());

const weekQueries = () => seenNetworkBff.filter((c) => c.path === '/api/bff/network/week').map((c) => c.query);

describe('NetworkWeekView', () => {
  it('reads the last complete week, by its Monday, for the network it was offered', async () => {
    server.use(...networkBffHandlers);
    render(<NetworkWeekView ownHref="/planning/week" />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Sample Network this week' })).toBeInTheDocument();
    expect(weekQueries()).toEqual(['networkId=net-sample&weekStart=2026-10-19']);
    expect(screen.getByRole('region', { name: 'Which board you are viewing' })).toHaveTextContent('Showing: Network, Sample Network');
  });

  it('goes to the week before, and back, and not past the last complete week', async () => {
    server.use(...networkBffHandlers);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<NetworkWeekView ownHref="/planning/week" />);
    await screen.findByRole('heading', { level: 1 });
    expect(screen.getByRole('button', { name: 'Later week' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Earlier week' }));
    await waitFor(() => expect(weekQueries()).toContain('networkId=net-sample&weekStart=2026-10-12'));
    await user.click(screen.getByRole('button', { name: 'Later week' }));
    await waitFor(() => expect(weekQueries().at(-1)).toBe('networkId=net-sample&weekStart=2026-10-19'));
  });

  it('is "not available" when refused (a role that does not read the week is refused), with no figure', async () => {
    server.use(http.get('/api/bff/network/week', () => HttpResponse.json({ code: 'forbidden' }, { status: 403 })), ...networkBffHandlers);
    render(<NetworkWeekView ownHref="/planning/week" />);
    expect(await screen.findByText('Network view not available')).toBeInTheDocument();
  });

  it('says it could not read the week when the read fails, and offers to try again', async () => {
    server.use(http.get('/api/bff/network/week', () => HttpResponse.json({ code: 'exception' }, { status: 503 })), ...networkBffHandlers);
    render(<NetworkWeekView ownHref="/planning/week" />);
    expect(await screen.findByText('This week could not be read. Try again shortly.')).toBeInTheDocument();
    server.use(http.get('/api/bff/network/week', () => HttpResponse.json(parseWeek(WEEK_BODY, 'backend'))));
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('134 hours sampled')).toBeInTheDocument();
  });
});
