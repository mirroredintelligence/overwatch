import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetLeadPosts, seenLeadPosts } from '@/test/msw/handlers/lead';
import { server } from '@/test/msw/server';
import { SuspendService } from './SuspendService';

// Suspend, resume (W42, DEC-657; redesign board "Suspend and resume a service"). The page reads the service's
// name; it cannot read whether the service is suspended, so the suspended view comes from the suspend answer
// on this page. Four states in one stage: Suspend, Suspended, Resume, Resumed. A pinned card carries the
// service and a state chip that changes shape and word.

beforeEach(() => {
  resetLeadPosts();
  document.cookie = 'overwatch_csrf=test-csrf-token';
});

async function toSuspended(user: ReturnType<typeof userEvent.setup>) {
  render(<SuspendService serviceId="s-ucr-east" />);
  await screen.findByRole('heading', { name: 'Suspend UCR East' });
  await user.click(screen.getByRole('radio', { name: 'Closed unexpectedly' }));
  await user.click(screen.getByRole('button', { name: 'Suspend UCR East' }));
  await screen.findByRole('heading', { name: 'UCR East is suspended' });
}

describe('SuspendService', () => {
  it('asks why before it suspends: no reason shows "Choose why" and posts nothing', async () => {
    const user = userEvent.setup();
    render(<SuspendService serviceId="s-ucr-east" />);
    expect(await screen.findByRole('heading', { name: 'Suspend UCR East' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Suspend UCR East' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose why');
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('offers the four reasons as a radio group named "Why?"', async () => {
    render(<SuspendService serviceId="s-ucr-east" />);
    const group = await screen.findByRole('radiogroup', { name: 'Why?' });
    expect(within(group).getAllByRole('radio').map((r) => (r as HTMLInputElement).value)).toEqual([
      'suspected-false-reports',
      'closed-unexpectedly',
      'contact-unreachable',
      'other',
    ]);
  });

  it('does not put focus on the confirm button when the page opens', async () => {
    render(<SuspendService serviceId="s-ucr-east" />);
    const confirm = await screen.findByRole('button', { name: 'Suspend UCR East' });
    expect(confirm).not.toHaveFocus();
    expect(document.body.contains(document.activeElement)).toBe(true);
    expect(document.activeElement).not.toBe(confirm);
  });

  it('pins a card with the service and a "Reporting" chip shaped as a circle', async () => {
    render(<SuspendService serviceId="s-ucr-east" />);
    await screen.findByRole('heading', { name: 'Suspend UCR East' });
    const card = screen.getByRole('region', { name: 'The service' });
    expect(within(card).getByText('UCR East')).toBeInTheDocument();
    const chip = within(card).getByText('Reporting');
    expect(chip.closest('[data-shape]')).toHaveAttribute('data-shape', 'circle');
    expect(within(card).getByText('In the options and reporting as usual.')).toBeInTheDocument();
  });

  it('suspends with the reason chosen, says how many open requests expired and turns the chip to a square "Suspended"', async () => {
    const user = userEvent.setup();
    await toSuspended(user);
    expect(seenLeadPosts).toHaveLength(1);
    expect(seenLeadPosts[0]).toMatchObject({
      path: '/api/bff/lead/services/s-ucr-east/suspend',
      csrf: 'test-csrf-token',
      body: { reason: 'closed-unexpectedly' },
    });
    expect(screen.getByText('2 expired')).toBeInTheDocument();
    expect(screen.getByText('Told by text')).toBeInTheDocument();
    expect(screen.getByText(/Resuming needs a call-back/)).toBeInTheDocument();
    const card = screen.getByRole('region', { name: 'The service' });
    const chip = within(card).getByText('Suspended');
    expect(chip.closest('[data-shape]')).toHaveAttribute('data-shape', 'square');
    expect(within(card).queryByText('Reporting')).not.toBeInTheDocument();
    expect(within(card).getByText('Out of the options. The board shows Not updated, phone to confirm.')).toBeInTheDocument();
  });

  it('says so when the service could not be told by text', async () => {
    server.use(
      http.post('/api/bff/lead/services/:id/suspend', () =>
        HttpResponse.json({ since: '2026-10-30T14:20:00Z', expiredRequests: 0, notified: false }),
      ),
    );
    const user = userEvent.setup();
    await toSuspended(user);
    expect(screen.getByText('None expired')).toBeInTheDocument();
    expect(screen.getByText('Not told by text')).toBeInTheDocument();
  });

  it('keeps Resume disabled until both confirmations are ticked, then posts both as true', async () => {
    const user = userEvent.setup();
    await toSuspended(user);
    await user.click(screen.getByRole('button', { name: 'Resume the service' }));
    expect(await screen.findByRole('heading', { name: 'Before you resume UCR East' })).toBeInTheDocument();

    const resume = screen.getByRole('button', { name: 'Resume the service' });
    expect(resume).toBeDisabled();
    await user.click(screen.getByRole('checkbox', { name: 'I phoned the service on the register number' }));
    expect(resume).toBeDisabled();
    expect(screen.getByText('Both are needed')).toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: 'The reason is resolved' }));
    expect(resume).toBeEnabled();
    await user.click(resume);

    await waitFor(() => expect(seenLeadPosts).toHaveLength(2));
    expect(seenLeadPosts[1]).toMatchObject({
      path: '/api/bff/lead/services/s-ucr-east/resume',
      body: { phonedRegisterNumber: true, reasonResolved: true },
    });
    expect(await screen.findByRole('heading', { name: 'UCR East is back' })).toBeInTheDocument();
  });

  it('announces "UCR East is back" in a status region once resumed, and the chip is a circle again', async () => {
    const user = userEvent.setup();
    await toSuspended(user);
    await user.click(screen.getByRole('button', { name: 'Resume the service' }));
    await user.click(await screen.findByRole('checkbox', { name: 'I phoned the service on the register number' }));
    await user.click(screen.getByRole('checkbox', { name: 'The reason is resolved' }));
    await user.click(screen.getByRole('button', { name: 'Resume the service' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('UCR East is back'));
    const card = screen.getByRole('region', { name: 'The service' });
    expect(within(card).getByText('Reporting').closest('[data-shape]')).toHaveAttribute('data-shape', 'circle');
    expect(screen.getByRole('link', { name: 'Back to the shift' })).toHaveAttribute('href', '/lead');
    expect(screen.getByText(/Next report due/)).toBeInTheDocument();
  });

  it('shows only the current state to the keyboard and to a screen reader', async () => {
    const user = userEvent.setup();
    await toSuspended(user);
    expect(screen.queryByRole('heading', { name: 'Suspend UCR East' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Suspend UCR East' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Phone the service' })).toBeInTheDocument();
  });

  it('goes back from the two checks to the suspended state with Cancel, and "Start again" returns to the first', async () => {
    const user = userEvent.setup();
    await toSuspended(user);
    await user.click(screen.getByRole('button', { name: 'Resume the service' }));
    await user.click(await screen.findByRole('button', { name: 'Cancel' }));
    expect(await screen.findByRole('heading', { name: 'UCR East is suspended' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Resume the service' }));
    await user.click(await screen.findByRole('checkbox', { name: 'I phoned the service on the register number' }));
    await user.click(screen.getByRole('checkbox', { name: 'The reason is resolved' }));
    await user.click(screen.getByRole('button', { name: 'Resume the service' }));
    await user.click(await screen.findByRole('button', { name: 'Start again' }));
    expect(await screen.findByRole('heading', { name: 'Suspend UCR East' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Closed unexpectedly' })).not.toBeChecked();
  });

  it('opens the phoned sheet from "Phone the service"', async () => {
    const user = userEvent.setup();
    await toSuspended(user);
    await user.click(screen.getByRole('button', { name: 'Phone the service' }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });

  it('says what suspending does at once, before the reason is chosen', async () => {
    render(<SuspendService serviceId="s-ucr-east" />);
    const list = await screen.findByRole('list', { name: 'What happens at once' });
    const items = within(list).getAllByRole('listitem').map((item) => item.textContent);
    expect(items).toEqual([
      'The board shows Not updated, phone to confirm.',
      'The service leaves the options.',
      'Prompts stop.',
      'Open requests expire.',
    ]);
  });

  it('answers a 403 on suspend with the words for a person who may not do this', async () => {
    server.use(
      http.post('/api/bff/lead/services/:id/suspend', () =>
        HttpResponse.json({ code: 'forbidden' }, { status: 403 }),
      ),
    );
    const user = userEvent.setup();
    render(<SuspendService serviceId="s-ucr-east" />);
    await screen.findByRole('heading', { name: 'Suspend UCR East' });
    await user.click(screen.getByRole('radio', { name: 'Other' }));
    await user.click(screen.getByRole('button', { name: 'Suspend UCR East' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('You cannot do this. Ask a shift lead.');
  });

  it('says the service could not be resumed when the resume fails, and stays on the two checks', async () => {
    server.use(
      http.post('/api/bff/lead/services/:id/resume', () => HttpResponse.json({ code: 'error' }, { status: 500 })),
    );
    const user = userEvent.setup();
    await toSuspended(user);
    await user.click(screen.getByRole('button', { name: 'Resume the service' }));
    await user.click(await screen.findByRole('checkbox', { name: 'I phoned the service on the register number' }));
    await user.click(screen.getByRole('checkbox', { name: 'The reason is resolved' }));
    await user.click(screen.getByRole('button', { name: 'Resume the service' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The service could not be resumed. Try again.');
    expect(screen.getByRole('heading', { name: 'Before you resume UCR East' })).toBeInTheDocument();
  });

  it('has no axe violations on the suspend form', async () => {
    const { container } = render(<SuspendService serviceId="s-ucr-east" />);
    await screen.findByRole('heading', { name: 'Suspend UCR East' });
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('has no axe violations on the suspended state', async () => {
    const user = userEvent.setup();
    const { container } = render(<SuspendService serviceId="s-ucr-east" />);
    await screen.findByRole('heading', { name: 'Suspend UCR East' });
    await user.click(screen.getByRole('radio', { name: 'Other' }));
    await user.click(screen.getByRole('button', { name: 'Suspend UCR East' }));
    await screen.findByRole('heading', { name: 'UCR East is suspended' });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
