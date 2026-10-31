import { act, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { AskClinicalDialog } from './AskClinicalDialog';

const SUMMARY = { ageBand: '80+', district: 'DT4 8XX', needs: ['Fall', 'Frailty'], within: 'Within 2 hrs', news2: 2, frailtyScale: 6 };
const PARTIAL = { ageBand: null, district: null, needs: [], within: null, news2: null, frailtyScale: null };
const CASE = 'case-4821';

type Call = { method: string; path: string; body?: unknown };
let calls: Call[] = [];
let available = 2;
let polls: string[] = [];

function handlers(states: string[] = ['waiting']) {
  let poll = 0;
  return [
    http.get('/api/bff/clinical/summary', () => {
      calls.push({ method: 'GET', path: '/api/bff/clinical/summary' });
      return HttpResponse.json({ available });
    }),
    http.post(`/api/bff/cases/${CASE}/clinical-requests`, async ({ request }) => {
      calls.push({ method: 'POST', path: `/api/bff/cases/${CASE}/clinical-requests`, body: await request.json() });
      return HttpResponse.json({ requestId: 'req-9001' }, { status: 201 });
    }),
    http.get(`/api/bff/cases/${CASE}/clinical-requests/req-9001`, () => {
      const state = states[Math.min(poll, states.length - 1)] ?? 'waiting';
      poll += 1;
      polls.push(state);
      calls.push({ method: 'GET', path: `/api/bff/cases/${CASE}/clinical-requests/req-9001` });
      if (state === 'failed') return HttpResponse.json({ code: 'exception' }, { status: 503 });
      if (state === 'taken') return HttpResponse.json({ state, returnsAt: '2026-10-23T13:29:30Z' });
      if (state === 'advised') {
        return HttpResponse.json({ state, advice: 'go-ahead', reason: 'within-criteria-on-judgement', note: 'Phone the family first.', advisedAt: '2026-10-23T13:15:00Z' });
      }
      return HttpResponse.json({ state: 'waiting' });
    }),
  ];
}

function Harness({ onClose = () => undefined, optionsShown = 3 }: { onClose?: () => void; optionsShown?: number }) {
  return <AskClinicalDialog caseRef={CASE} summary={SUMMARY} optionsShown={optionsShown} onClose={onClose} />;
}

// The opener stays on the page while the dialog opens and closes, as it does in the case screen.
function ToggleHarness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Ask a clinical advisor</button>
      {open ? <AskClinicalDialog caseRef={CASE} summary={SUMMARY} optionsShown={3} onClose={() => setOpen(false)} /> : null}
    </>
  );
}

beforeEach(() => {
  calls = [];
  polls = [];
  available = 2;
  server.use(...handlers());
});

afterEach(() => {
  vi.useRealTimers();
});

describe('AskClinicalDialog before sending', () => {
  it('shows the case summary as it was passed in, and the availability', async () => {
    render(<Harness />);
    expect(screen.getByRole('dialog', { name: 'Ask a clinical advisor' })).toBeInTheDocument();
    expect(screen.getByText('Escalate')).toBeInTheDocument();
    expect(screen.getByText('80+ · DT4 8XX · Fall, Frailty · Within 2 hrs')).toBeInTheDocument();
    expect(screen.getByText('NEWS2 2 · Frailty scale 6 · Options shown: 3')).toBeInTheDocument();
    expect(await screen.findByText('2 clinical advisors available')).toBeInTheDocument();
    expect(screen.getByText('The case summary goes with the call. No name is sent.')).toBeInTheDocument();
  });

  it('disables the call and says what to do when no advisor is available', async () => {
    available = 0;
    server.use(...handlers());
    render(<Harness />);
    expect(await screen.findByText('No clinical advisor is available now. Use the escalation route under local protocol.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Call clinical advisor' })).toBeDisabled();
  });

  it('posts the urgency and the reason, and then shows that it is waiting for an advisor', async () => {
    render(<Harness />);
    await screen.findByText('2 clinical advisors available');
    await userEvent.click(screen.getByRole('button', { name: 'Borderline criteria' }));
    await userEvent.click(screen.getByRole('button', { name: 'Call clinical advisor' }));
    expect(await screen.findByText('Waiting for a clinical advisor')).toBeInTheDocument();
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ urgency: 'now', why: 'borderline-criteria' });
  });

  it('defaults to Now, and offers Within 15 min', async () => {
    render(<Harness />);
    expect(screen.getByRole('button', { name: 'Now' })).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(screen.getByRole('button', { name: 'Within 15 min' }));
    expect(screen.getByRole('button', { name: 'Within 15 min' })).toHaveAttribute('aria-pressed', 'true');
  });
});

describe('AskClinicalDialog summary', () => {
  it('shows only what the case holds: nothing is made up for a part that is not recorded', () => {
    render(<AskClinicalDialog caseRef={CASE} summary={PARTIAL} optionsShown={0} onClose={() => undefined} />);
    expect(screen.getByRole('region', { name: 'Case summary' })).toHaveTextContent('Options shown: 0');
    expect(screen.queryByText(/NEWS2/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Frailty scale/)).not.toBeInTheDocument();
  });

  it('says the summary could not be read, and still lets the advisor ask', async () => {
    render(<AskClinicalDialog caseRef={CASE} summary={null} optionsShown={0} onClose={() => undefined} />);
    expect(screen.getByText('The case summary could not be read.')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Call clinical advisor' })).toBeEnabled());
  });
});

describe('AskClinicalDialog while waiting', () => {
  it('polls every 5 seconds: waiting, taken, then advised, and then stops', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    server.use(...handlers(['waiting', 'taken', 'advised']));
    render(<Harness />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Call clinical advisor' })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: 'Borderline criteria' }));
    await userEvent.click(screen.getByRole('button', { name: 'Call clinical advisor' }));
    await act(async () => { vi.advanceTimersByTime(5_000); });
    await waitFor(() => expect(polls).toEqual(['waiting']));
    await act(async () => { vi.advanceTimersByTime(5_000); });
    await waitFor(() => expect(screen.getByText('A clinical advisor has taken your request. It returns to the queue at 14:29 if they do not act.')).toBeInTheDocument());
    await act(async () => { vi.advanceTimersByTime(5_000); });
    await waitFor(() => expect(screen.getByText('Advice: Go ahead with the service. Reason: within criteria on my judgement.')).toBeInTheDocument());
    expect(screen.getByText('Note from the clinical advisor: Phone the family first.')).toBeInTheDocument();
    expect(screen.queryByText('Waiting for a clinical advisor')).not.toBeInTheDocument();
    const seen = polls.length;
    await act(async () => { vi.advanceTimersByTime(20_000); });
    expect(polls.length).toBe(seen);
  });

  it('says it could not read the answer when the read fails, and never goes on saying it is waiting for one it cannot see (DEC-855)', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    server.use(...handlers(['failed']));
    render(<Harness />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Call clinical advisor' })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: 'Borderline criteria' }));
    await userEvent.click(screen.getByRole('button', { name: 'Call clinical advisor' }));
    await act(async () => { vi.advanceTimersByTime(5_000); });
    expect(await screen.findByRole('alert')).toHaveTextContent('The answer could not be read. Check again, or use the escalation route under local protocol.');
    expect(screen.queryByText('Waiting for a clinical advisor')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Check again' })).toBeInTheDocument();
  });

  it('reads again on Check again, and shows the advice once the read works', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    server.use(...handlers(['failed', 'advised']));
    render(<Harness />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Call clinical advisor' })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: 'Borderline criteria' }));
    await userEvent.click(screen.getByRole('button', { name: 'Call clinical advisor' }));
    await act(async () => { vi.advanceTimersByTime(5_000); });
    await userEvent.click(await screen.findByRole('button', { name: 'Check again' }));
    expect(await screen.findByText('Advice: Go ahead with the service. Reason: within criteria on my judgement.')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('says the request went back to the queue when a taken request reads as waiting again, and goes on waiting', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    server.use(...handlers(['taken', 'waiting']));
    render(<Harness />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Call clinical advisor' })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: 'Borderline criteria' }));
    await userEvent.click(screen.getByRole('button', { name: 'Call clinical advisor' }));
    await act(async () => { vi.advanceTimersByTime(5_000); });
    await screen.findByText(/has taken your request/);
    await act(async () => { vi.advanceTimersByTime(5_000); });
    expect(await screen.findByText('The clinical advisor did not act in time. Your request is back in the queue.')).toBeInTheDocument();
  });

  it('tells the advisor to keep the dialog open until the advice arrives', async () => {
    render(<Harness />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Call clinical advisor' })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: 'Borderline criteria' }));
    await userEvent.click(screen.getByRole('button', { name: 'Call clinical advisor' }));
    expect(await screen.findByText('Keep this open until the advice arrives. It is not kept if you close it.')).toBeInTheDocument();
  });

  it('closes on Escape, stops polling, and returns focus to the button that opened it', async () => {
    render(<ToggleHarness />);
    await userEvent.click(screen.getByRole('button', { name: 'Ask a clinical advisor' }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ask a clinical advisor' })).toHaveFocus();
  });

  it('moves focus to the heading when it opens, and keeps Tab inside the dialog', async () => {
    render(<Harness />);
    expect(screen.getByRole('heading', { name: 'Ask a clinical advisor' })).toHaveFocus();
    const dialog = screen.getByRole('dialog');
    for (let i = 0; i < 12; i += 1) {
      await userEvent.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
  });

  it('has no accessibility violations in the first state and the waiting state', async () => {
    const { container } = render(<Harness />);
    await screen.findByText('2 clinical advisors available');
    expect(within(container).getByRole('button', { name: 'Call clinical advisor' })).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('the service under consideration (KI-768)', () => {
  const SERVICE = { id: 'svc-ucr-west', name: 'UCR West' };

  it('names the service the advisor is asking about, and sends its id with the request', async () => {
    calls = [];
    server.use(...handlers());
    const user = userEvent.setup();
    render(<AskClinicalDialog caseRef={CASE} summary={SUMMARY} optionsShown={3} service={SERVICE} onClose={vi.fn()} />);

    expect(screen.getByText('About: UCR West')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Other' }));
    await user.click(screen.getByRole('button', { name: 'Call clinical advisor' }));

    await waitFor(() => expect(calls.find((call) => call.method === 'POST')?.body).toEqual({ urgency: 'now', why: 'other', service: 'svc-ucr-west' }));
  });

  it('with no service it says nothing of one and sends none', async () => {
    calls = [];
    server.use(...handlers());
    const user = userEvent.setup();
    render(<AskClinicalDialog caseRef={CASE} summary={SUMMARY} optionsShown={3} onClose={vi.fn()} />);

    expect(screen.queryByText(/^About:/)).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Other' }));
    await user.click(screen.getByRole('button', { name: 'Call clinical advisor' }));

    await waitFor(() => expect(calls.find((call) => call.method === 'POST')?.body).toEqual({ urgency: 'now', why: 'other' }));
  });

  it('shows "Go ahead with" the service by name, from the request the back end reads, not the general label', async () => {
    server.use(
      http.get('/api/bff/clinical/summary', () => HttpResponse.json({ available: 2 })),
      http.post(`/api/bff/cases/${CASE}/clinical-requests`, () => HttpResponse.json({ requestId: 'req-9001' }, { status: 201 })),
      http.get(`/api/bff/cases/${CASE}/clinical-requests/req-9001`, () =>
        HttpResponse.json({ state: 'advised', advice: 'go-ahead', service: 'UCR West', advisedAt: '2026-10-23T13:15:00Z' }),
      ),
    );
    const user = userEvent.setup();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      render(<AskClinicalDialog caseRef={CASE} summary={SUMMARY} optionsShown={3} service={SERVICE} onClose={vi.fn()} />);
      await user.click(screen.getByRole('button', { name: 'Other' }));
      await user.click(screen.getByRole('button', { name: 'Call clinical advisor' }));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
      });

      expect(await screen.findByText('Advice: Go ahead with UCR West.')).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});
