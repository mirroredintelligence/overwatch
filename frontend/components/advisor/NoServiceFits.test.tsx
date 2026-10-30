import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { BLANK_CASE, CASE_ETAG, resetSeenAdvisorRequests, seenCasePuts } from '@/test/msw/handlers/advisor';
import { server } from '@/test/msw/server';
import { NoServiceFits } from './NoServiceFits';

const FULL_CASE = {
  ...BLANK_CASE,
  referrerType: 'ambulance-crew',
  ageBand: '80+',
  postcode: 'DT4 8XX',
  needs: ['fall-no-injury', 'frailty'],
  urgency: 'within-2-hrs',
  etag: CASE_ETAG,
};

function caseAs(urgency: string | null) {
  server.use(http.get('/api/bff/cases/:ref', () => HttpResponse.json({ ...FULL_CASE, urgency })));
}

beforeEach(() => {
  resetCsrfCache();
  resetSeenAdvisorRequests();
});

describe('NoServiceFits (W16)', () => {
  it('shows the heading, the sub line and the note that a next step is always offered', () => {
    caseAs('within-2-hrs');
    render(<NoServiceFits caseId="4821" onWidened={vi.fn()} onAskClinical={vi.fn()} />);

    expect(screen.getByRole('heading', { name: 'No service fits right now' })).toBeInTheDocument();
    expect(
      screen.getByText('Every service is either not accepting, outside the criteria, or not updated.'),
    ).toBeInTheDocument();
    expect(screen.getByText('What instead')).toBeInTheDocument();
    expect(screen.getByText('Never end the call on a refusal. Always offer a next step.')).toBeInTheDocument();
  });

  it('with urgency "within 2 hrs", "Widen the time" saves urgency today with If-Match and asks for the options again', async () => {
    caseAs('within-2-hrs');
    const user = userEvent.setup();
    const onWidened = vi.fn();
    render(<NoServiceFits caseId="4821" onWidened={onWidened} onAskClinical={vi.fn()} />);

    const widen = await screen.findByRole('button', { name: 'Widen the time: today instead of within 2 hrs' });
    expect(byEl('ADV-NOFIT-WIDEN-BTN')).toBe(widen);
    await user.click(widen);

    await waitFor(() => expect(onWidened).toHaveBeenCalledTimes(1));
    expect(seenCasePuts).toHaveLength(1);
    expect(seenCasePuts[0].ifMatch).toBe(CASE_ETAG);
    expect(seenCasePuts[0].body).toMatchObject({
      referrerType: 'ambulance-crew',
      ageBand: '80+',
      postcode: 'DT4 8XX',
      needs: ['fall-no-injury', 'frailty'],
      urgency: 'today',
    });
  });

  it('with urgency today, "Widen the time" is not shown', async () => {
    caseAs('today');
    render(<NoServiceFits caseId="4821" onWidened={vi.fn()} onAskClinical={vi.fn()} />);

    await screen.findByRole('heading', { name: 'No service fits right now' });
    expect(screen.queryByRole('button', { name: 'Widen the time: today instead of within 2 hrs' })).toBeNull();
    expect(document.querySelector('[data-el="ADV-NOFIT-WIDEN-BTN"]')).toBeNull();
  });

  it('a widen that is refused says so and does not reload the options', async () => {
    caseAs('within-2-hrs');
    server.use(http.put('/api/bff/cases/:ref', () => HttpResponse.json({ code: 'conflict' }, { status: 412 })));
    const user = userEvent.setup();
    const onWidened = vi.fn();
    render(<NoServiceFits caseId="4821" onWidened={onWidened} onAskClinical={vi.fn()} />);

    await user.click(await screen.findByRole('button', { name: 'Widen the time: today instead of within 2 hrs' }));

    expect(await screen.findByText('The time could not be changed. Try again.')).toBeInTheDocument();
    expect(onWidened).not.toHaveBeenCalled();
  });

  it('"Phone a service you know has space" goes to the wall board view', async () => {
    caseAs('within-2-hrs');
    render(<NoServiceFits caseId="4821" onWidened={vi.fn()} onAskClinical={vi.fn()} />);

    expect(byEl('ADV-NOFIT-PHONE-LINK')).toHaveAttribute('href', '/advisor/board');
  });

  it('"Other routes under local protocol" records the outcome as no service fits', () => {
    caseAs('within-2-hrs');
    render(<NoServiceFits caseId="4821" onWidened={vi.fn()} onAskClinical={vi.fn()} />);

    expect(byEl('ADV-NOFIT-OTHER-BTN')).toHaveAttribute('href', '/advisor/case/4821/finish?outcome=no-service-fits');
  });

  it('"Ask a clinical advisor" calls its handler; "Back to needs" goes back to the case', async () => {
    caseAs('within-2-hrs');
    const user = userEvent.setup();
    const onAskClinical = vi.fn();
    render(<NoServiceFits caseId="4821" onWidened={vi.fn()} onAskClinical={onAskClinical} />);

    await user.click(byEl('ADV-NOFIT-CLINICAL-BTN'));

    expect(onAskClinical).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('link', { name: 'Back to needs' })).toHaveAttribute('href', '/advisor/case/4821');
  });

  it('the primary action is the last thing in the screen, for the phone layout', () => {
    caseAs('within-2-hrs');
    const { container } = render(<NoServiceFits caseId="4821" onWidened={vi.fn()} onAskClinical={vi.fn()} />);
    const actions = container.querySelectorAll('button, a');
    const last = actions[actions.length - 1];

    expect(last).toHaveAttribute('data-el', 'ADV-NOFIT-CLINICAL-BTN');
  });

  it('has no axe violations', async () => {
    caseAs('within-2-hrs');
    const { container } = render(<main><NoServiceFits caseId="4821" onWidened={vi.fn()} onAskClinical={vi.fn()} /></main>);
    await screen.findByRole('button', { name: 'Widen the time: today instead of within 2 hrs' });
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
