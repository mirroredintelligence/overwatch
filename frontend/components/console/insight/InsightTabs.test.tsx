import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import {
  INSIGHT_FRICTION,
  INSIGHT_FUNNELS,
  INSIGHT_PATHS,
  INSIGHT_PERFORMANCE,
  INSIGHT_RELEASES,
  INSIGHT_RELEASES_ALONE,
} from '@/test/fixtures/insight-shapes';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { InsightTabs } from './InsightTabs';

// The answers are the ones the back end's own mappers produce (test/fixtures/insight-shapes.gen.py).
const ANSWERS: Record<string, unknown> = {
  funnels: INSIGHT_FUNNELS,
  paths: INSIGHT_PATHS,
  friction: INSIGHT_FRICTION,
  performance: INSIGHT_PERFORMANCE,
  releases: INSIGHT_RELEASES,
};

let requested: string[];

function answerEveryTab(overrides: Record<string, unknown> = {}) {
  requested = [];
  server.use(
    http.get('/api/bff/console/insight/:tab', ({ request, params }) => {
      requested.push(`${String(params.tab)}?${new URL(request.url).searchParams.toString()}`);
      return HttpResponse.json({ ...ANSWERS, ...overrides }[String(params.tab)] ?? {});
    }),
  );
}

vi.mock('next/navigation', () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }) }));

async function open(tab: string) {
  await userEvent.click(screen.getByRole('tab', { name: tab }));
}

describe('InsightTabs: the requests', () => {
  it('asks for the new tab with the range and device that are chosen', async () => {
    answerEveryTab();
    render(<InsightTabs initialTab="funnels" />);

    await userEvent.click(screen.getByRole('button', { name: 'Last 30 days' }));
    await userEvent.click(screen.getByRole('button', { name: 'Phone' }));
    await open('Performance');

    await waitFor(() => expect(requested).toContain('performance?range=30d&device=phone'));
  });

  it('asks with no device until one is chosen, and again with none when All devices is chosen', async () => {
    answerEveryTab();
    render(<InsightTabs initialTab="friction" />);

    await waitFor(() => expect(requested).toContain('friction?range=7d'));
    await userEvent.click(screen.getByRole('button', { name: 'Tablet' }));
    await waitFor(() => expect(requested).toContain('friction?range=7d&device=tablet'));
    await userEvent.click(screen.getByRole('button', { name: 'All devices' }));
    await waitFor(() => expect(requested.at(-1)).toBe('friction?range=7d'));
  });

  it('does not offer a device on the release comparison, which has none', async () => {
    answerEveryTab();
    render(<InsightTabs initialTab="funnels" />);

    await open('Releases');

    expect(screen.queryByRole('group', { name: 'Device' })).not.toBeInTheDocument();
    await waitFor(() => expect(requested).toContain('releases?range=7d'));
  });

  it('has the five tabs, and the selected one is marked', () => {
    answerEveryTab();
    render(<InsightTabs initialTab="friction" />);

    for (const name of ['Funnels', 'Paths', 'Friction', 'Performance', 'Releases']) {
      expect(screen.getByRole('tab', { name })).toBeInTheDocument();
    }
    expect(screen.getByRole('tab', { name: 'Friction' })).toHaveAttribute('aria-selected', 'true');
  });
});

describe('InsightTabs: what the back end answers', () => {
  it('shows the funnels with their steps, a hidden step as fewer than 10, and a chooser for the funnel', async () => {
    answerEveryTab();
    render(<InsightTabs initialTab="funnels" />);

    const steps = await screen.findByRole('list', { name: /funnel steps/i });
    expect(within(steps).getByText('Home-screen guide viewed').closest('li')).toHaveTextContent('94%');
    expect(within(steps).getByText('Set-up finished').closest('li')).toHaveTextContent('fewer than 10');
    expect(screen.getByRole('button', { name: 'Advisor call' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Advisor call' }));
    expect(await screen.findByRole('heading', { name: 'Advisor call' })).toBeInTheDocument();
  });

  it('says there is no funnel data when the back end answers with no funnel', async () => {
    answerEveryTab({ funnels: { ...INSIGHT_FUNNELS, funnels: [] } });
    render(<InsightTabs initialTab="funnels" />);

    expect(await screen.findByText('No funnel data for this range.')).toBeInTheDocument();
  });

  it('marks the elements the back end flags for review, not the ones at exactly 5%', async () => {
    answerEveryTab();
    render(<InsightTabs initialTab="friction" />);

    const table = await screen.findByRole('table', { name: /friction by element/i });
    expect(within(table).getByRole('row', { name: /ADV-OPT-REQUEST-BTN/ })).toHaveTextContent('Review');
    expect(within(table).getByRole('row', { name: /ADV-REF-INPUT/ })).not.toHaveTextContent('Review');
    expect(within(table).getByRole('row', { name: /ADV-SEARCH-BTN/ })).not.toHaveTextContent('Review');
  });

  it('shows friction of the page itself with its route and no rate, and says how many groups are hidden', async () => {
    answerEveryTab();
    render(<InsightTabs initialTab="friction" />);

    const table = await screen.findByRole('table', { name: /friction by element/i });
    const page = within(table).getByRole('row', { name: /PAGE/ });
    expect(page).toHaveTextContent('/advisor/board');
    expect(page).toHaveTextContent('u-turn');
    expect(screen.getByText('1 element or page with fewer than 10 sessions is not shown.')).toBeInTheDocument();
  });

  it('lists the common routes, hides a small one, and says the unused controls are not measured', async () => {
    answerEveryTab();
    render(<InsightTabs initialTab="paths" />);

    const routes = await screen.findByRole('table', { name: /most common routes/i });
    expect(within(routes).getByRole('row', { name: /\/advisor\/board/ })).toHaveTextContent('120');
    expect(within(routes).getByRole('row', { name: /\/help/ })).toHaveTextContent('fewer than 10');
    expect(screen.getByText('Not measured yet: this needs the list of every control.')).toBeInTheDocument();
    expect(screen.queryByText('Never used this week')).toBeInTheDocument();
  });

  it('shows each vital by device against its budget as a word, and a hidden one as fewer than 10', async () => {
    answerEveryTab();
    render(<InsightTabs initialTab="performance" />);

    const table = await screen.findByRole('table', { name: /web vitals/i });
    const desktop = within(table).getByRole('row', { name: /Largest contentful paint.*desktop/i });
    expect(desktop).toHaveTextContent('2500 ms');
    expect(desktop).toHaveTextContent('Within budget');
    const phone = within(table).getByRole('row', { name: /Largest contentful paint.*phone/i });
    expect(phone).toHaveTextContent('4000 ms');
    expect(phone).toHaveTextContent('Over budget');
    expect(within(table).getByRole('row', { name: /Cumulative layout shift/i })).toHaveTextContent('fewer than 10');
  });

  it('lists the slowest routes and queries, and says prompt to board is not measured', async () => {
    answerEveryTab();
    render(<InsightTabs initialTab="performance" />);

    expect(await screen.findByText(/\/advisor\/case\/\[ref\]: p95 6000 ms/)).toBeInTheDocument();
    expect(screen.getByText(/Q-OPTIONS: p95 190 ms/)).toBeInTheDocument();
    expect(screen.getByText('Prompt to board: not measured yet.')).toBeInTheDocument();
  });

  it('compares two releases, holds a slowdown for review in words, and shows the pipeline', async () => {
    answerEveryTab();
    render(<InsightTabs initialTab="releases" />);

    expect(await screen.findByText('Comparing 1.4.3 with 1.4.2')).toBeInTheDocument();
    const measures = screen.getByRole('table', { name: /release comparison/i });
    const lcp = within(measures).getByRole('row', { name: /Largest contentful paint/ });
    expect(lcp).toHaveTextContent('Slower');
    expect(lcp).toHaveTextContent('Held for review');
    expect(within(measures).getByRole('row', { name: /Interaction to next paint/ })).toHaveTextContent('No change');
    const pipeline = screen.getByRole('table', { name: /pipeline health/i });
    expect(within(pipeline).getByRole('row', { name: /messages\.outbound/ })).toHaveTextContent('95 s');
  });

  it('says why there is no comparison when only one release has enough sessions, and still shows the pipeline', async () => {
    answerEveryTab({ releases: INSIGHT_RELEASES_ALONE });
    render(<InsightTabs initialTab="releases" />);

    expect(await screen.findByText('Two releases with at least 10 sessions each are needed to compare.')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: /pipeline health/i })).toBeInTheDocument();
    expect(screen.queryByRole('table', { name: /release comparison/i })).not.toBeInTheDocument();
  });
});

describe('InsightTabs: when it cannot be read', () => {
  it.each([404, 500, 502, 503])('says the view could not be loaded on a %i, never that insight is not available', async (status) => {
    server.use(http.get('/api/bff/console/insight/:tab', () => HttpResponse.json({ code: 'x' }, { status })));
    render(<InsightTabs initialTab="funnels" />);

    expect(await screen.findByRole('alert')).toHaveTextContent('This view could not be loaded. Try again.');
    expect(screen.queryByText(/not available yet/i)).not.toBeInTheDocument();
    expect(screen.queryByText('No funnel data for this range.')).not.toBeInTheDocument();
  });

  it('passes vitest-axe on the page', async () => {
    answerEveryTab();
    const { container } = render(<InsightTabs initialTab="funnels" />);

    await screen.findByRole('list', { name: /funnel steps/i });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
