import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { BLANK_CASE, resetSeenAdvisorRequests, seenCasePuts } from '@/test/msw/handlers/advisor';
import { server } from '@/test/msw/server';
import { NeedsForm } from './NeedsForm';

// The needs form against what the back end holds for a case (W8A): the open time, a closed case, the
// stored district, scores that cannot change, and the key a save must carry.

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock('./CallBar', () => ({
  CallBar: (props: { openedAt: string; referrer: string }) => (
    <div data-testid="call-bar" data-opened={props.openedAt}>
      {props.referrer}
    </div>
  ),
}));

const RECORDED = {
  ...BLANK_CASE,
  referrerType: 'ambulance-crew',
  ageBand: '80+',
  postcode: 'DT4',
  needs: ['fall-no-injury', 'frailty'],
  urgency: 'within-2-hrs',
  scores: [{ method: 'news2', value: 2 }],
  openedAt: '2026-10-30T09:50:00Z',
};

beforeEach(() => {
  resetCsrfCache();
  resetSeenAdvisorRequests();
});

function caseIs(view: Record<string, unknown>) {
  server.use(http.get('/api/bff/cases/:ref', () => HttpResponse.json(view)));
}

describe('the call bar (W10)', () => {
  it('counts from the time the back end opened the case, not from the time the page was drawn', async () => {
    caseIs(RECORDED);
    render(<NeedsForm caseId="case-1" />);

    expect((await screen.findByTestId('call-bar')).getAttribute('data-opened')).toBe('2026-10-30T09:50:00Z');
  });
});

describe('a closed case (W15, D18)', () => {
  it('says the call is closed and offers no form: a closed case cannot change', async () => {
    caseIs({ ...BLANK_CASE, closed: true, closedAt: '2026-10-30T10:09:00Z', outcome: 'declined' });
    render(<NeedsForm caseId="case-1" />);

    expect(await screen.findByText('This call is closed.')).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Who is calling?' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'See options' })).toBeNull();
    expect(screen.getByRole('link', { name: 'Start a new call' })).toHaveAttribute('href', '/advisor');
  });
});

describe('the postcode the back end keeps as its district (DEC-398)', () => {
  it('says which district is on record, lets the advisor go on without typing the postcode again, and sends none', async () => {
    caseIs(RECORDED);
    const user = userEvent.setup();
    render(<NeedsForm caseId="case-1" />);
    await screen.findByRole('group', { name: 'Who is calling?' });

    expect(screen.getByText('On record: postcode district DT4. Type the full postcode only to change it.')).toBeInTheDocument();
    expect(screen.getByLabelText('Where is the patient? Postcode')).toHaveValue('');
    expect(byEl('ADV-NEEDS-CONTINUE-BTN')).toBeEnabled();

    await user.click(byEl('ADV-NEEDS-CONTINUE-BTN'));

    await waitFor(() => expect(seenCasePuts).toHaveLength(1));
    expect(Object.keys(seenCasePuts[0]?.body as object)).not.toContain('postcode');
  });

  it('sends the new postcode when one is typed', async () => {
    caseIs(RECORDED);
    const user = userEvent.setup();
    render(<NeedsForm caseId="case-1" />);
    await screen.findByRole('group', { name: 'Who is calling?' });

    await user.type(screen.getByLabelText('Where is the patient? Postcode'), 'DT1 1AA');
    await user.click(byEl('ADV-NEEDS-CONTINUE-BTN'));

    await waitFor(() => expect(seenCasePuts).toHaveLength(1));
    expect((seenCasePuts[0]?.body as { postcode: string }).postcode).toBe('DT1 1AA');
  });

  it('needs the postcode when the case has no district yet', async () => {
    caseIs({ ...RECORDED, postcode: null });
    render(<NeedsForm caseId="case-1" />);
    await screen.findByRole('group', { name: 'Who is calling?' });

    expect(byEl('ADV-NEEDS-CONTINUE-BTN')).toBeDisabled();
  });
});

describe('recorded scores are changed only as a correction with a reason (Q7, KI-815)', () => {
  const REASON_LABELS = ['I entered it wrongly', 'The referrer gave a corrected score', 'The patient was scored again'];

  it('shows the recorded scores as text, offers a way to correct them, and saves them as they are with no reason', async () => {
    caseIs(RECORDED);
    const user = userEvent.setup();
    render(<NeedsForm caseId="case-1" />);
    await screen.findByRole('group', { name: 'Who is calling?' });

    expect(screen.getByText('Recorded as the referrer gave them: NEWS2 2.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Correct a score' })).toBeInTheDocument();
    expect(document.querySelector('[data-el="ADV-SCORE-NEWS2-CHIP"]')).toBeNull();

    await user.click(byEl('ADV-NEEDS-CONTINUE-BTN'));

    await waitFor(() => expect(seenCasePuts).toHaveLength(1));
    const body = seenCasePuts[0]?.body as Record<string, unknown>;
    expect(body.scores).toEqual([{ method: 'news2', value: 2 }]);
    expect(Object.keys(body)).not.toContain('scoreCorrectionReason');
  });

  it('shows the pickers with the recorded scores when the advisor corrects, and asks why', async () => {
    caseIs(RECORDED);
    const user = userEvent.setup();
    render(<NeedsForm caseId="case-1" />);
    await screen.findByRole('group', { name: 'Who is calling?' });

    await user.click(screen.getByRole('button', { name: 'Correct a score' }));

    expect(byEl('ADV-SCORE-NEWS2-CHIP')).toHaveAttribute('aria-pressed', 'true');
    expect(byEl('ADV-SCORE-NEWS2-INPUT')).toHaveValue('2');
    const reasons = screen.getByRole('group', { name: 'Why is the score being corrected?' });
    for (const label of REASON_LABELS) expect(within(reasons).getByRole('radio', { name: label })).toBeInTheDocument();
  });

  it('will not save a changed score until a reason is chosen, then sends the new score with the reason', async () => {
    caseIs(RECORDED);
    const user = userEvent.setup();
    render(<NeedsForm caseId="case-1" />);
    await screen.findByRole('group', { name: 'Who is calling?' });
    await user.click(screen.getByRole('button', { name: 'Correct a score' }));

    await user.clear(byEl('ADV-SCORE-NEWS2-INPUT'));
    await user.type(byEl('ADV-SCORE-NEWS2-INPUT'), '5');

    expect(byEl('ADV-NEEDS-CONTINUE-BTN')).toBeDisabled();
    await user.click(screen.getByRole('radio', { name: 'I entered it wrongly' }));
    expect(byEl('ADV-NEEDS-CONTINUE-BTN')).toBeEnabled();
    await user.click(byEl('ADV-NEEDS-CONTINUE-BTN'));

    await waitFor(() => expect(seenCasePuts).toHaveLength(1));
    const body = seenCasePuts[0]?.body as Record<string, unknown>;
    expect(body.scores).toEqual([{ method: 'news2', value: 5 }]);
    expect(body.scoreCorrectionReason).toBe('typing-error');
  });

  it('sends no reason when the scores were opened for correction and left as they were', async () => {
    caseIs(RECORDED);
    const user = userEvent.setup();
    render(<NeedsForm caseId="case-1" />);
    await screen.findByRole('group', { name: 'Who is calling?' });
    await user.click(screen.getByRole('button', { name: 'Correct a score' }));
    await user.click(screen.getByRole('radio', { name: 'The patient was scored again' }));

    await user.click(byEl('ADV-NEEDS-CONTINUE-BTN'));

    await waitFor(() => expect(seenCasePuts).toHaveLength(1));
    expect(Object.keys(seenCasePuts[0]?.body as object)).not.toContain('scoreCorrectionReason');
  });

  it('can add a score of another method to a recorded one with no reason', async () => {
    caseIs(RECORDED);
    const user = userEvent.setup();
    render(<NeedsForm caseId="case-1" />);
    await screen.findByRole('group', { name: 'Who is calling?' });
    await user.click(screen.getByRole('button', { name: 'Correct a score' }));
    await user.click(byEl('ADV-SCORE-CFS-CHIP'));
    await user.click(byEl('ADV-SCORE-CFS-4'));

    expect(byEl('ADV-NEEDS-CONTINUE-BTN')).toBeEnabled();
    await user.click(byEl('ADV-NEEDS-CONTINUE-BTN'));

    await waitFor(() => expect(seenCasePuts).toHaveLength(1));
    const body = seenCasePuts[0]?.body as { scores: unknown; scoreCorrectionReason?: unknown };
    expect(body.scores).toEqual([
      { method: 'news2', value: 2 },
      { method: 'cfs', value: 4 },
    ]);
    expect(body.scoreCorrectionReason).toBeUndefined();
  });

  it('says how many times the scores were corrected and that the first is kept', async () => {
    caseIs({ ...RECORDED, scoreCorrections: 1 });
    render(<NeedsForm caseId="case-1" />);

    expect(await screen.findByText('Corrected 1 time. The score first recorded is kept in the record.')).toBeInTheDocument();
  });

  it('says it in the plural for more than one', async () => {
    caseIs({ ...RECORDED, scoreCorrections: 2 });
    render(<NeedsForm caseId="case-1" />);

    expect(await screen.findByText('Corrected 2 times. The score first recorded is kept in the record.')).toBeInTheDocument();
  });

  it('has no axe violations while a score is being corrected, with the reasons shown and one chosen', async () => {
    caseIs({ ...RECORDED, scoreCorrections: 1 });
    const user = userEvent.setup();
    const { container } = render(<NeedsForm caseId="case-1" />);
    await screen.findByRole('group', { name: 'Who is calling?' });
    await user.click(screen.getByRole('button', { name: 'Correct a score' }));
    await user.click(screen.getByRole('radio', { name: 'I entered it wrongly' }));

    expect((await runAxe(container)).violations).toEqual([]);
  });

  it('keeps a recorded method pressed and not clearable, and offers no "Not given", while correcting', async () => {
    caseIs(RECORDED);
    const user = userEvent.setup();
    render(<NeedsForm caseId="case-1" />);
    await screen.findByRole('group', { name: 'Who is calling?' });
    await user.click(screen.getByRole('button', { name: 'Correct a score' }));

    expect(byEl('ADV-SCORE-NEWS2-CHIP')).toBeDisabled();
    expect(byEl('ADV-SCORE-NEWS2-CHIP')).toHaveAttribute('aria-pressed', 'true');
    expect(document.querySelector('[data-el="ADV-SCORE-NONE-CHIP"]')).toBeNull();
  });

  it('will not save while a recorded score is left as an invalid entry: it is not sent as the old value', async () => {
    caseIs(RECORDED);
    const user = userEvent.setup();
    render(<NeedsForm caseId="case-1" />);
    await screen.findByRole('group', { name: 'Who is calling?' });
    await user.click(screen.getByRole('button', { name: 'Correct a score' }));

    await user.clear(byEl('ADV-SCORE-NEWS2-INPUT'));

    expect(byEl('ADV-NEEDS-CONTINUE-BTN')).toBeDisabled();
  });

  it('says nothing about a correction for a case never corrected', async () => {
    caseIs(RECORDED);
    render(<NeedsForm caseId="case-1" />);
    await screen.findByRole('group', { name: 'Who is calling?' });

    expect(screen.queryByText(/Corrected \d/)).toBeNull();
  });

  it('still offers the score pickers while no score is recorded', async () => {
    caseIs({ ...RECORDED, scores: [] });
    render(<NeedsForm caseId="case-1" />);
    await screen.findByRole('group', { name: 'Who is calling?' });

    expect(byEl('ADV-SCORE-NEWS2-CHIP')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Correct a score' })).toBeNull();
  });
});

describe('a case changed by someone else (H-192)', () => {
  it('says so, and reading the case again shows the latest and clears the message', async () => {
    let reads = 0;
    server.use(
      http.get('/api/bff/cases/:ref', () => {
        reads += 1;
        return HttpResponse.json(reads === 1 ? RECORDED : { ...RECORDED, urgency: 'today', etag: 'W/"4"' });
      }),
      http.put('/api/bff/cases/:ref', () => HttpResponse.json({ code: 'conflict' }, { status: 412 })),
    );
    const user = userEvent.setup();
    render(<NeedsForm caseId="case-1" />);
    await screen.findByRole('group', { name: 'Who is calling?' });

    await user.click(byEl('ADV-NEEDS-CONTINUE-BTN'));
    expect(await screen.findByText('Someone changed this case since you opened it. Nothing of yours was saved.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Read the case again' }));

    await waitFor(() => expect(reads).toBe(2));
    await waitFor(() => expect(screen.queryByText(/Someone changed this case/)).toBeNull());
    expect(screen.getByRole('button', { name: /Today/ })).toHaveAttribute('aria-pressed', 'true');
  });

  it('sends the version it read as If-Match, and the new version after a save is the next one it sends', async () => {
    caseIs({ ...RECORDED, etag: 'W/"7"' });
    const user = userEvent.setup();
    render(<NeedsForm caseId="case-1" />);
    await screen.findByRole('group', { name: 'Who is calling?' });

    await user.click(byEl('ADV-NEEDS-CONTINUE-BTN'));

    await waitFor(() => expect(seenCasePuts).toHaveLength(1));
    expect(seenCasePuts[0]?.ifMatch).toBe('W/"7"');
  });
});

describe('the key of a save (the back end requires an Idempotency-Key)', () => {
  it('sends a key, and a new one for each press', async () => {
    caseIs(RECORDED);
    let calls = 0;
    server.use(
      http.put('/api/bff/cases/:ref', async ({ request }) => {
        calls += 1;
        seenCasePuts.push({ url: request.url, ifMatch: request.headers.get('if-match'), key: request.headers.get('idempotency-key'), body: await request.json() });
        return calls === 1 ? HttpResponse.json({ code: 'exception' }, { status: 500 }) : HttpResponse.json(RECORDED);
      }),
    );
    const user = userEvent.setup();
    render(<NeedsForm caseId="case-1" />);
    await screen.findByRole('group', { name: 'Who is calling?' });

    await user.click(byEl('ADV-NEEDS-CONTINUE-BTN'));
    await screen.findByText('The case could not be saved. Try again.');
    await user.click(byEl('ADV-NEEDS-CONTINUE-BTN'));

    await waitFor(() => expect(seenCasePuts).toHaveLength(2));
    const [first, second] = seenCasePuts.map((put) => put.key);
    expect(first).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
    expect(second).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
    expect(first).not.toBe(second);
  });
});
