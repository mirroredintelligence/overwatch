import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { runAxe } from '@/test/a11y';
import { DECISION_READY } from '@/test/fixtures/registration';
import { resetRegistrationRequests, seenRegistrationRequests } from '@/test/msw/handlers/registrations';
import { server } from '@/test/msw/server';
import { GoLive } from './GoLive';

beforeEach(() => resetRegistrationRequests());

function decisionWith(decision: unknown) {
  server.use(http.get('/api/bff/registrations/:id/decision', () => HttpResponse.json(decision as Record<string, unknown>)));
}

describe('GoLive', () => {
  it('keeps Set live disabled until the test is answered, then enables it', async () => {
    decisionWith({ ...DECISION_READY, test: { sentAt: '2026-10-30T15:02:00Z' } });
    const { unmount } = render(<GoLive id="r1" />);
    expect(await screen.findByRole('button', { name: 'Set live' })).toBeDisabled();
    expect(screen.getByText('Test notification sent 15:02')).toBeInTheDocument();
    expect(screen.getByText('Test not answered yet.')).toBeInTheDocument();
    expect(screen.getByText('Set live opens when the test is answered from the registered phone.')).toBeInTheDocument();
    unmount();

    decisionWith(DECISION_READY);
    render(<GoLive id="r1" />);
    expect(await screen.findByRole('button', { name: 'Set live' })).toBeEnabled();
    expect(screen.getByText('Test answered 15:03 from the registered phone')).toBeInTheDocument();
    expect(screen.queryByText('Set live opens when the test is answered from the registered phone.')).not.toBeInTheDocument();
  });

  it('shows who approved, the board preview and the record, and is accessible', async () => {
    decisionWith(DECISION_READY);
    const { container } = render(<GoLive id="r1" />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Go live: UCR East' })).toBeInTheDocument();
    expect(screen.getByText('After approval')).toBeInTheDocument();
    expect(screen.getByText('Approved by Service manager and Clinical lead')).toBeInTheDocument();
    expect(screen.getByText('Registration record')).toBeInTheDocument();
    expect(screen.getByText('Submitted by Duty manager')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('lists the three steps with a done or not-yet word each, so state is never colour alone', async () => {
    decisionWith({ ...DECISION_READY, approvedBy: [], test: {} });
    render(<GoLive id="r1" />);
    const list = await screen.findByRole('list', { name: 'Before it goes live' });
    const rows = within(list).getAllByRole('listitem');
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent('Approval not recorded yet.');
    expect(rows[0]).toHaveTextContent('Not yet');
    expect(rows[1]).toHaveTextContent('Test notification not sent yet.');
    expect(rows[2]).toHaveTextContent('Test not answered yet.');
  });

  it('marks the finished steps done', async () => {
    decisionWith(DECISION_READY);
    render(<GoLive id="r1" />);
    const list = await screen.findByRole('list', { name: 'Before it goes live' });
    for (const row of within(list).getAllByRole('listitem')) expect(row).toHaveTextContent('Done');
  });

  it('shows how the service will look on the board: a status, with no figure made up', async () => {
    decisionWith(DECISION_READY);
    render(<GoLive id="r1" />);
    const preview = await screen.findByRole('region', { name: 'How it will look on the board' });
    expect(within(preview).getByText('UCR East')).toBeInTheDocument();
    expect(within(preview).getByText('Accepting')).toBeInTheDocument();
    expect(within(preview).getByText('A status, until they report a number.')).toBeInTheDocument();
  });

  it('sets the service live on that press and says so', async () => {
    decisionWith(DECISION_READY);
    const user = userEvent.setup();
    render(<GoLive id="r1" />);
    await user.click(await screen.findByRole('button', { name: 'Set live' }));
    expect(await screen.findByText('The service is live.')).toBeInTheDocument();
    await waitFor(() =>
      expect(seenRegistrationRequests.some((r) => r.method === 'POST' && r.path === '/api/bff/registrations/r1/go-live')).toBe(true),
    );
    expect(screen.getByRole('button', { name: 'Set live' })).toBeDisabled();
  });

  it('says the service could not be set live, and offers Back to the registration', async () => {
    decisionWith(DECISION_READY);
    server.use(http.post('/api/bff/registrations/:id/go-live', () => HttpResponse.json({}, { status: 500 })));
    const user = userEvent.setup();
    render(<GoLive id="r1" />);
    await user.click(await screen.findByRole('button', { name: 'Set live' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The service could not be set live. Check the test and try again.');
    expect(screen.getByRole('link', { name: 'Back' })).toHaveAttribute('href', '/lead/registrations/r1');
  });

  it('says what is loading while the page loads, in the shared shimmer', () => {
    render(<GoLive id="r1" />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading go live.');
  });
});
