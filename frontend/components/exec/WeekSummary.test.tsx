import { render, screen, waitFor } from '@testing-library/react';
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
    expect(screen.getByText('640 referrals')).toBeInTheDocument();
    expect(screen.getByText('18% best fit not available')).toBeInTheDocument();
    expect(screen.getByText('92% capacity updates on time')).toBeInTheDocument();
    expect(screen.getByText('4 min median time to a confirmed booking')).toBeInTheDocument();
    expect(screen.getByText('Counts under 10 are hidden. Outcomes are not shown yet.')).toBeInTheDocument();
  });

  it('keeps the minutes placeholder and says the estimate is not yet measured', () => {
    render(<WeekSummaryView summary={summary} prefs={prefs} />);
    expect(screen.getByText(/about one phone call of \[x\] minutes/)).toBeInTheDocument();
    expect(screen.getByText('Estimate until we measure the baseline.')).toBeInTheDocument();
    expect(screen.getByText('Estimate')).toBeInTheDocument();
  });

  it('shows the sum behind the estimate once the minutes are set', () => {
    render(<WeekSummaryView summary={{ ...summary, minutesPerCall: 4 }} prefs={prefs} />);
    expect(screen.getByText('about 1,648 minutes (412 × 4)')).toBeInTheDocument();
  });

  it('shows "fewer than 10" for a withheld figure, and no percentage', () => {
    render(<WeekSummaryView summary={{ ...summary, bestFitUnavailablePct: { value: null, suppressed: true } }} prefs={prefs} />);
    expect(screen.getByText('fewer than 10 best fit not available')).toBeInTheDocument();
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
