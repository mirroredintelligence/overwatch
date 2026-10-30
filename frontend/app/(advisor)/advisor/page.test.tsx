import { byEl } from '@/test/el';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { runAxe } from '@/test/a11y';
import { CASE_ID, CSRF_TOKEN, resetSeenAdvisorRequests, seenCaseCreates } from '@/test/msw/handlers/advisor';
import { server } from '@/test/msw/server';
import AdvisorHomePage from './page';

const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

beforeEach(() => {
  push.mockReset();
  resetCsrfCache();
  resetSeenAdvisorRequests();
});

describe('advisor home (W10)', () => {
  it('shows "Ready for calls" and the five board counts from the sample board', async () => {
    render(<AdvisorHomePage />);

    expect(screen.getByRole('heading', { name: 'Ready for calls' })).toBeInTheDocument();
    expect(screen.getByText('Advisor home')).toBeInTheDocument();
    await waitFor(() => expect(byEl('ADV-HOME-COUNT-ACCEPTING')).toHaveTextContent('4'));
    expect(byEl('ADV-HOME-COUNT-LIMITED')).toHaveTextContent('2');
    expect(byEl('ADV-HOME-COUNT-NOT-ACCEPTING')).toHaveTextContent('1');
    expect(byEl('ADV-HOME-COUNT-OVER-CAPACITY')).toHaveTextContent('1');
    expect(byEl('ADV-HOME-COUNT-NOT-UPDATED')).toHaveTextContent('1');
  });

  it('"Start a new call" posts once with the CSRF header and an Idempotency-Key, then opens the case', async () => {
    const user = userEvent.setup();
    render(<AdvisorHomePage />);

    await user.click(screen.getByRole('button', { name: 'Start a new call' }));

    await waitFor(() => expect(push).toHaveBeenCalledWith(`/advisor/case/${CASE_ID}`));
    expect(seenCaseCreates).toHaveLength(1);
    const sent = seenCaseCreates[0];
    expect(sent.headers.get('x-csrf-token')).toBe(CSRF_TOKEN);
    expect(sent.headers.get('idempotency-key')).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
  });

  it('a double click posts only once', async () => {
    const user = userEvent.setup();
    render(<AdvisorHomePage />);

    const button = screen.getByRole('button', { name: 'Start a new call' });
    await user.dblClick(button);

    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(seenCaseCreates).toHaveLength(1);
  });

  it('the start button is busy while the case is being created', async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.post('/api/bff/cases', async () => {
        await gate;
        return HttpResponse.json({ id: CASE_ID }, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    render(<AdvisorHomePage />);

    await user.click(screen.getByRole('button', { name: 'Start a new call' }));
    expect(screen.getByRole('button', { name: 'Start a new call' })).toHaveAttribute('aria-busy', 'true');
    await act(async () => release());
    await waitFor(() => expect(push).toHaveBeenCalled());
  });

  it('links to the wall board view and says nothing from earlier calls is shown', async () => {
    render(<AdvisorHomePage />);

    expect(screen.getByRole('link', { name: 'Open the wall board view' })).toHaveAttribute('href', '/advisor/board');
    expect(screen.getByText('No open cases. Nothing from earlier calls is shown here.')).toBeInTheDocument();
  });

  it('has no axe violations once the counts have loaded', async () => {
    const { container } = render(<AdvisorHomePage />);
    await waitFor(() => expect(byEl('ADV-HOME-COUNT-ACCEPTING')).toHaveTextContent('4'));
    const counts = within(container);
    expect(counts.getByRole('heading', { name: 'Board right now' })).toBeInTheDocument();
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
