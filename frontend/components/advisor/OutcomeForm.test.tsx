import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { CSRF_TOKEN, resetSeenAdvisorRequests, seenOutcomePosts } from '@/test/msw/handlers/advisor';
import { OutcomeForm } from './OutcomeForm';

beforeEach(() => {
  resetCsrfCache();
  resetSeenAdvisorRequests();
});

describe('OutcomeForm (W15)', () => {
  it('"Save outcome" is disabled until an outcome is chosen', async () => {
    const user = userEvent.setup();
    render(<OutcomeForm caseId="4821" preselect={null} onClosed={vi.fn()} />);

    expect(byEl('ADV-FIN-SAVE-BTN')).toBeDisabled();
    await user.click(byEl('ADV-FIN-OUTCOME-DECLINED'));
    expect(byEl('ADV-FIN-SAVE-BTN')).toBeEnabled();
  });

  it('choosing "Accepted and booked" and "Data too old" posts both, with CSRF and a key, then reports the close', async () => {
    const user = userEvent.setup();
    const onClosed = vi.fn();
    render(<OutcomeForm caseId="4821" preselect={null} onClosed={onClosed} />);

    await user.click(screen.getByRole('button', { name: 'Accepted and booked' }));
    await user.click(await screen.findByRole('button', { name: 'UCR West' }));
    await user.click(screen.getByRole('button', { name: 'Data too old' }));
    await user.click(byEl('ADV-FIN-SAVE-BTN'));

    await waitFor(() => expect(onClosed).toHaveBeenCalledWith('2026-10-30T14:21:00.000Z'));
    expect(seenOutcomePosts).toHaveLength(1);
    expect(seenOutcomePosts[0].body).toEqual({
      outcome: 'accepted-and-booked',
      bestFitNotUsed: 'data-too-old',
      destinationServiceId: 'svc-ucr-west',
    });
    expect(seenOutcomePosts[0].csrf).toBe(CSRF_TOKEN);
    expect(seenOutcomePosts[0].key).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
  });

  it('"Cancel" goes back to the options', () => {
    render(<OutcomeForm caseId="4821" preselect={null} onClosed={vi.fn()} />);
    expect(screen.getByRole('link', { name: 'Cancel' })).toHaveAttribute('href', '/advisor/case/4821/options');
  });

  it('?outcome=no-service-fits preselects it and shows it as text, not as a chip', () => {
    render(<OutcomeForm caseId="4821" preselect="no-service-fits" onClosed={vi.fn()} />);

    expect(screen.getByText('No service fits')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'No service fits' })).toBeNull();
    expect(byEl('ADV-FIN-SAVE-BTN')).toBeEnabled();
  });

  it('a failed save says so and does not report a close', async () => {
    const { server } = await import('@/test/msw/server');
    const { http, HttpResponse } = await import('msw');
    server.use(http.post('/api/bff/cases/:ref/outcome', () => HttpResponse.json({ code: 'conflict' }, { status: 412 })));
    const user = userEvent.setup();
    const onClosed = vi.fn();
    render(<OutcomeForm caseId="4821" preselect={null} onClosed={onClosed} />);
    await user.click(byEl('ADV-FIN-OUTCOME-DECLINED'));

    await user.click(byEl('ADV-FIN-SAVE-BTN'));

    expect(await screen.findByText('The outcome could not be saved. Try again.')).toBeInTheDocument();
    expect(onClosed).not.toHaveBeenCalled();
  });

  it('has no axe violations', async () => {
    render(
      <main>
        <OutcomeForm caseId="4821" preselect={null} onClosed={vi.fn()} />
      </main>,
    );
    expect((await runAxe(document.body)).violations).toEqual([]);
  });
});
