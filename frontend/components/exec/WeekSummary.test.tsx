import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { DEFAULT_ALERT_PREFERENCES, type AlertPreferences } from '@/lib/exec/alertPrefs';
import type { WeekSummary } from '@/lib/exec/weekSummary';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { WeekSummary as WeekSummaryView } from './WeekSummary';

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const summary: WeekSummary = {
  from: '2026-10-19',
  to: '2026-10-25',
  referrals: { value: 640, suppressed: false },
  bestFitUnavailablePct: { value: 18, suppressed: false },
  onTimePct: { value: 92, suppressed: false },
  medianMinutesToConfirmed: { value: 4, suppressed: false },
  updates: { value: 412, suppressed: false },
  minutesPerCall: null,
  timeBackText: null,
};

const prefs: AlertPreferences = { ...DEFAULT_ALERT_PREFERENCES, deputy: 'pr-0042' };

describe('WeekSummary time back', () => {
  it('shows no placeholder: it says how many updates and that the time saved is not measured yet', () => {
    render(<WeekSummaryView summary={summary} prefs={prefs} />);
    expect(screen.getByText('412 updates by text, app or email.')).toBeInTheDocument();
    expect(screen.getByText(/The time this saved is not measured yet/)).toBeInTheDocument();
    expect(screen.queryByText(/\[x\]/)).not.toBeInTheDocument();
  });

  it('shows the back end\'s own sentence when it sends one', () => {
    render(<WeekSummaryView summary={{ ...summary, timeBackText: 'About 20 hours of phone calls.' }} prefs={prefs} />);
    expect(screen.getByText('About 20 hours of phone calls.')).toBeInTheDocument();
  });
});

describe('WeekSummary', () => {
  it('shows the four figures with their words, and the footnote', () => {
    render(<WeekSummaryView summary={summary} prefs={prefs} />);
    expect(screen.getByRole('heading', { level: 1, name: 'This week' })).toBeInTheDocument();
    const tiles = within(screen.getByRole('list', { name: 'Figures for the week' })).getAllByRole('listitem');
    expect(tiles[0]).toHaveTextContent('640referrals');
    expect(tiles[1]).toHaveTextContent('18%best fit not available');
    expect(tiles[2]).toHaveTextContent('92%capacity updates on time');
    expect(tiles[3]).toHaveTextContent('4 minmedian time to a confirmed booking');
    expect(screen.getByText('Counts under 10 are hidden. Outcomes are not shown yet.')).toBeInTheDocument();
  });

  it('shows the sum behind the estimate once the minutes are set', () => {
    render(<WeekSummaryView summary={{ ...summary, minutesPerCall: 4 }} prefs={prefs} />);
    expect(screen.getByText('about 1,648 minutes (412 × 4)')).toBeInTheDocument();
  });

  it('shows "fewer than 10" for a withheld figure, and no percentage', () => {
    render(<WeekSummaryView summary={{ ...summary, bestFitUnavailablePct: { value: null, suppressed: true } }} prefs={prefs} />);
    expect(screen.getByText('best fit not available').closest('li')).toHaveTextContent('fewer than 10best fit not available');
    expect(screen.queryByText(/%\s*best fit/)).not.toBeInTheDocument();
  });

  it('turns the Monday summary on with the whole preference state, and changes its words', async () => {
    const sent: AlertPreferences[] = [];
    server.use(http.put('/api/bff/exec/alert-preferences', async ({ request }) => {
      const body = (await request.json()) as AlertPreferences;
      sent.push(body);
      return HttpResponse.json(body);
    }));
    render(<WeekSummaryView summary={summary} prefs={prefs} />);
    await userEvent.click(screen.getByRole('button', { name: 'Send me this each Monday' }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toEqual(expect.objectContaining({ weeklySummary: true, deputy: 'pr-0042', ackMinutes: 15 }));
    expect(await screen.findByRole('button', { name: 'You will get this each Monday.' })).toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<WeekSummaryView summary={summary} prefs={prefs} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
