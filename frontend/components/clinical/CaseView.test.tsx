import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { clinicalBffHandlers, DONE_ITEMS, MINE_ITEMS, QUEUE_ITEMS, resetClinicalBff, seenBff } from '@/test/msw/handlers/clinical';
import { server } from '@/test/msw/server';
import type { ClinicalRequest } from '@/lib/clinical/task';
import { CaseView } from './CaseView';

const { push, refresh } = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, refresh, replace: vi.fn() }) }));

const held = MINE_ITEMS[0] as ClinicalRequest;
const advised = () => seenBff.filter((c) => c.path.endsWith('/advice'));

afterEach(() => vi.useRealTimers());

describe('CaseView with the case read', () => {
  it('shows the case number and the case as the advisor recorded it: age band, needs, urgency and NEWS2', () => {
    resetClinicalBff();
    render(<CaseView requestId="req-5001" request={held} />);
    expect(screen.getByRole('heading', { name: 'Case 5001' })).toBeInTheDocument();
    expect(screen.getByText('80+ · Frailty, Fall · NEWS2 3 · Within 2 hrs')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Why the advisor asked' })).toBeInTheDocument();
    expect(screen.getByText('Other')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send advice' })).toBeInTheDocument();
  });

  it('says in a live region when the request returns to the queue, in whole minutes', () => {
    vi.useFakeTimers({ now: new Date('2026-10-23T13:20:00Z'), shouldAdvanceTime: false });
    render(<CaseView requestId="req-5001" request={held} />);
    const live = screen.getByRole('status');
    expect(live).toHaveTextContent('Returns to the queue in 9 min');
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(live).toHaveTextContent('Returns to the queue in 8 min');
  });

  it('asks for an advice choice before sending, and sends nothing', async () => {
    resetClinicalBff();
    server.use(...clinicalBffHandlers);
    render(<CaseView requestId="req-5001" request={held} />);
    await userEvent.click(screen.getByRole('button', { name: 'Send advice' }));
    expect(screen.getByText('Choose what you advise.')).toBeInTheDocument();
    expect(advised()).toHaveLength(0);
  });

  it('blocks a note of 281 characters with its message, and sends nothing', async () => {
    resetClinicalBff();
    server.use(...clinicalBffHandlers);
    render(<CaseView requestId="req-5001" request={held} />);
    await userEvent.click(screen.getByRole('button', { name: 'Go ahead with the service' }));
    fireEvent.change(screen.getByLabelText('Note (optional)'), { target: { value: 'x'.repeat(281) } });
    await userEvent.click(screen.getByRole('button', { name: 'Send advice' }));
    expect(screen.getByText('Keep the note to 280 characters')).toBeInTheDocument();
    expect(advised()).toHaveLength(0);
  });

  it('posts a valid advice and then shows the confirmation', async () => {
    resetClinicalBff();
    server.use(...clinicalBffHandlers);
    render(<CaseView requestId="req-5001" request={held} />);
    await userEvent.click(screen.getByRole('button', { name: 'Go ahead with the service' }));
    await userEvent.click(screen.getByRole('button', { name: 'Within criteria on my judgement' }));
    await userEvent.click(screen.getByRole('button', { name: 'Send advice' }));
    await waitFor(() => expect(advised()).toHaveLength(1));
    expect(advised()[0]?.path).toBe('/api/bff/clinical/requests/req-5001/advice');
    expect(advised()[0]?.body).toEqual(expect.objectContaining({ advice: 'go-ahead', reason: 'within-criteria-on-judgement' }));
    expect(await screen.findByRole('heading', { name: 'Advice sent' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Next request' })).toHaveAttribute('href', '/clinical/requests');
    expect(screen.getByRole('button', { name: 'Go off duty' })).toBeInTheDocument();
  });

  it('says the request is no longer theirs when the back end refuses the advice as taken or returned', async () => {
    server.use(http.post('/api/bff/clinical/requests/:id/advice', () => HttpResponse.json({ code: 'conflict' }, { status: 409 })));
    render(<CaseView requestId="req-5001" request={held} />);
    await userEvent.click(screen.getByRole('button', { name: 'Go ahead with the service' }));
    await userEvent.click(screen.getByRole('button', { name: 'Send advice' }));
    expect(await screen.findByText('This request is no longer yours. It may have returned to the queue.')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Advice sent' })).not.toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<CaseView requestId="req-5001" request={held} />);
    expect(screen.getByRole('button', { name: 'Send advice' })).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

// DEC-855: the advice form is offered only when the case read loaded.
describe('CaseView without the case read (DEC-855)', () => {
  it('offers no advice form when the request could not be read, and says so', async () => {
    const { container } = render(<CaseView requestId="req-5001" request={null} />);
    expect(screen.getByRole('alert')).toHaveTextContent('This request could not be read, so it cannot be answered from here.');
    expect(screen.queryByRole('button', { name: 'Send advice' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Go ahead with the service' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to the queue' })).toHaveAttribute('href', '/clinical/requests');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('offers no advice form when the request has no case details, and says the case could not be read', () => {
    render(<CaseView requestId="req-5003" request={{ ...held, id: 'req-5003', glance: null }} />);
    expect(screen.getByRole('alert')).toHaveTextContent('The case could not be read, so no advice can be given from here.');
    expect(screen.queryByRole('button', { name: 'Send advice' })).not.toBeInTheDocument();
  });

  it('offers no advice form for a request that is back in the queue, and says to take it again', () => {
    render(<CaseView requestId="req-4821" request={QUEUE_ITEMS[0] as ClinicalRequest} />);
    expect(screen.getByText('This request is back in the queue. Take it again from the queue to answer it.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send advice' })).not.toBeInTheDocument();
  });

  it('shows the advice already given on a completed request, and offers no second one', () => {
    render(<CaseView requestId="req-5002" request={DONE_ITEMS[0] as ClinicalRequest} />);
    expect(screen.getByText('Advice given: Use another service')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send advice' })).not.toBeInTheDocument();
  });
});
