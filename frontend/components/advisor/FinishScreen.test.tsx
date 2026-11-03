import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { http, HttpResponse } from 'msw';
import { resetSeenAdvisorRequests, SUMMARY_VIEW } from '@/test/msw/handlers/advisor';
import { server } from '@/test/msw/server';
import { FinishScreen } from './FinishScreen';

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace }) }));

beforeEach(() => {
  resetCsrfCache();
  resetSeenAdvisorRequests();
  replace.mockReset();
});

describe('FinishScreen (W15)', () => {
  it('after "Save outcome" shows "Call closed", what was kept and what was cleared, and the postcode is gone', async () => {
    const user = userEvent.setup();
    render(<FinishScreen caseId="4821" preselect={null} />);

    expect(await screen.findByText('DT4 8XX')).toBeInTheDocument();
    await user.click(byEl('ADV-FIN-OUTCOME-DECLINED'));
    await user.click(byEl('ADV-FIN-SAVE-BTN'));

    expect(await screen.findByRole('heading', { name: 'Call closed' })).toBeInTheDocument();
    expect(screen.getByText('Reference 4821 is saved. The postcode has been cleared from this screen.')).toBeInTheDocument();
    expect(screen.getByText('Kept for audit')).toBeInTheDocument();
    for (const item of ['Need category, age band, urgency and scores', 'Destination, outcome and times', 'What the board showed']) {
      expect(screen.getByText(item)).toBeInTheDocument();
    }
    expect(screen.getByText('Cleared')).toBeInTheDocument();
    for (const item of ['Postcode', 'Anything free-typed on the call']) {
      expect(screen.getByText(item)).toBeInTheDocument();
    }
    expect(screen.getByText('Retention periods are set by information governance.')).toBeInTheDocument();
    expect(document.body.textContent).not.toContain('DT4 8XX');
    expect(screen.queryByRole('button', { name: 'Copy summary' })).toBeNull();
  });

  it('names the case by the four-digit number the back end holds, not by the id in the address (DEC-631)', async () => {
    const user = userEvent.setup();
    render(<FinishScreen caseId="case-1" preselect={null} />);

    expect(await screen.findByText('Reference 4821')).toBeInTheDocument();
    await user.click(byEl('ADV-FIN-OUTCOME-DECLINED'));
    await user.click(byEl('ADV-FIN-SAVE-BTN'));

    expect(await screen.findByText('Reference 4821 is saved. The postcode has been cleared from this screen.')).toBeInTheDocument();
    expect(document.body.textContent).not.toContain('case-1');
  });

  it('the line under the heading names the reference and, once the service is chosen, the destination', async () => {
    const user = userEvent.setup();
    render(<FinishScreen caseId="4821" preselect={null} />);

    await user.click(byEl('ADV-FIN-OUTCOME-ACCEPTED'));
    await user.click(await screen.findByRole('button', { name: 'UCR West' }));

    expect(await screen.findByText('Reference 4821 · UCR West')).toBeInTheDocument();
  });

  it('has the outcome and the summary for SystmOne as two regions, side by side on a wide screen', async () => {
    render(<FinishScreen caseId="4821" preselect={null} />);

    expect(await screen.findByText('DT4 8XX')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Outcome' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Summary for SystmOne' })).toBeInTheDocument();
  });

  it('says the call is closed, and offers no outcome, when the case was closed already', async () => {
    server.use(http.get('/api/bff/cases/:ref/summary', () => HttpResponse.json({ code: 'closed' }, { status: 409 })));
    render(<FinishScreen caseId="case-1" preselect={null} />);

    expect(await screen.findByRole('heading', { name: 'Call closed' })).toBeInTheDocument();
    expect(document.querySelector('[data-el="ADV-FIN-SAVE-BTN"]')).toBeNull();
  });

  it('after saving, the address is replaced with ?closed=1, not pushed, so Back does not return to the form', async () => {
    const user = userEvent.setup();
    render(<FinishScreen caseId="4821" preselect={null} />);

    await user.click(byEl('ADV-FIN-OUTCOME-DECLINED'));
    await user.click(byEl('ADV-FIN-SAVE-BTN'));

    expect(await screen.findByRole('heading', { name: 'Call closed' })).toBeInTheDocument();
    expect(replace).toHaveBeenCalledWith('/advisor/case/4821/finish?closed=1');
  });

  it('opened at the closed address shows "Call closed" with no reference, and reads no summary', async () => {
    const reads = vi.fn();
    server.use(
      http.get('/api/bff/cases/:ref/summary', () => {
        reads();
        return HttpResponse.json(SUMMARY_VIEW);
      }),
    );
    render(<FinishScreen caseId="4821" preselect={null} closed />);

    expect(await screen.findByRole('heading', { name: 'Call closed' })).toBeInTheDocument();
    expect(screen.getByText('The case is saved. The postcode has been cleared from this screen.')).toBeInTheDocument();
    expect(reads).not.toHaveBeenCalled();
  });

  it('reads the summary again with the service chosen as the destination, so the copied referral names it (H-322)', async () => {
    const asked: (string | null)[] = [];
    server.use(
      http.get('/api/bff/cases/:ref/summary', ({ request }) => {
        const destination = new URL(request.url).searchParams.get('destination');
        asked.push(destination);
        return HttpResponse.json({ ...SUMMARY_VIEW, destination: destination === null ? 'No destination chosen yet' : 'UCR West' });
      }),
    );
    const user = userEvent.setup();
    render(<FinishScreen caseId="4821" preselect={null} />);
    expect(await screen.findByText('No destination chosen yet')).toBeInTheDocument();

    await user.click(byEl('ADV-FIN-OUTCOME-ACCEPTED'));
    await user.click(await screen.findByRole('button', { name: 'UCR West' }));

    await waitFor(() => expect(asked).toEqual([null, 'svc-ucr-west']));
    expect(await screen.findAllByText('UCR West')).not.toHaveLength(0);
  });

  it('does not leave a summary without the destination on screen when reading it again fails', async () => {
    server.use(
      http.get('/api/bff/cases/:ref/summary', ({ request }) =>
        new URL(request.url).searchParams.get('destination') === null
          ? HttpResponse.json(SUMMARY_VIEW)
          : HttpResponse.json({ code: 'exception' }, { status: 502 }),
      ),
    );
    const user = userEvent.setup();
    render(<FinishScreen caseId="4821" preselect={null} />);
    await screen.findByText('DT4 8XX');

    await user.click(byEl('ADV-FIN-OUTCOME-ACCEPTED'));
    await user.click(await screen.findByRole('button', { name: 'UCR West' }));

    expect(await screen.findByText('The summary could not be read.')).toBeInTheDocument();
    expect(screen.queryByText('DT4 8XX')).toBeNull();
  });

  it('"Start next call" goes to the advisor home, and the closed state offers "Back to the board"', async () => {
    const user = userEvent.setup();
    render(<FinishScreen caseId="4821" preselect={null} />);
    await user.click(byEl('ADV-FIN-OUTCOME-DECLINED'));
    await user.click(byEl('ADV-FIN-SAVE-BTN'));

    expect(await screen.findByRole('link', { name: 'Start next call' })).toHaveAttribute('href', '/advisor');
    expect(screen.getByRole('link', { name: 'Back to the board' })).toHaveAttribute('href', '/advisor/board');
  });

  it('has no axe violations in the form state and the closed state', async () => {
    const user = userEvent.setup();
    const { container } = render(<FinishScreen caseId="4821" preselect={null} />);
    await screen.findByText('DT4 8XX');
    expect((await runAxe(container)).violations).toEqual([]);

    await user.click(byEl('ADV-FIN-OUTCOME-DECLINED'));
    await user.click(byEl('ADV-FIN-SAVE-BTN'));
    await screen.findByRole('heading', { name: 'Call closed' });
    expect((await runAxe(container)).violations).toEqual([]);
  }, 30_000);
});
