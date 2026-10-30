import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { InsightTabs } from './InsightTabs';

const requested: string[] = [];

function answerEveryTab() {
  server.use(
    http.get('/api/bff/console/insight/:tab', ({ request, params }) => {
      requested.push(`${String(params.tab)}?${new URL(request.url).searchParams.toString()}`);
      return HttpResponse.json({ funnels: [], rows: [], vitals: [], compare: null, pipeline: [] });
    }),
  );
}

vi.mock('next/navigation', () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }) }));

describe('InsightTabs', () => {
  it('asks for the new tab with the range that is chosen', async () => {
    answerEveryTab();
    render(<InsightTabs initialTab="funnels" />);

    await userEvent.click(screen.getByRole('button', { name: 'Last 7 days' }));
    await userEvent.click(screen.getByRole('tab', { name: 'Performance' }));

    await waitFor(() => expect(requested).toContain('performance?range=7d'));
  });

  it('has the five tabs, and the selected one is marked', () => {
    answerEveryTab();
    render(<InsightTabs initialTab="friction" />);

    for (const name of ['Funnels', 'Paths', 'Friction', 'Performance', 'Releases']) {
      expect(screen.getByRole('tab', { name })).toBeInTheDocument();
    }
    expect(screen.getByRole('tab', { name: 'Friction' })).toHaveAttribute('aria-selected', 'true');
  });

  it('passes vitest-axe on the page', async () => {
    answerEveryTab();
    const { container } = render(<InsightTabs initialTab="funnels" />);

    await screen.findByRole('tabpanel');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
