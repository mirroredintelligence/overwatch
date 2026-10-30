import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
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

describe('scores the back end keeps once (U11: recorded scores cannot change)', () => {
  it('shows the recorded scores as text, offers no way to change them, and saves them as they are', async () => {
    caseIs(RECORDED);
    const user = userEvent.setup();
    render(<NeedsForm caseId="case-1" />);
    await screen.findByRole('group', { name: 'Who is calling?' });

    expect(screen.getByText('Recorded as the referrer gave them: NEWS2 2. They cannot be changed.')).toBeInTheDocument();
    expect(document.querySelector('[data-el="ADV-SCORE-NEWS2-CHIP"]')).toBeNull();

    await user.click(byEl('ADV-NEEDS-CONTINUE-BTN'));

    await waitFor(() => expect(seenCasePuts).toHaveLength(1));
    expect((seenCasePuts[0]?.body as { scores: unknown }).scores).toEqual([{ method: 'news2', value: 2 }]);
  });

  it('still offers the score pickers while no score is recorded', async () => {
    caseIs({ ...RECORDED, scores: [] });
    render(<NeedsForm caseId="case-1" />);
    await screen.findByRole('group', { name: 'Who is calling?' });

    expect(byEl('ADV-SCORE-NEWS2-CHIP')).toBeInTheDocument();
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
