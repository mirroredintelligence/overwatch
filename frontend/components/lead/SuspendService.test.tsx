import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetLeadPosts, seenLeadPosts } from '@/test/msw/handlers/lead';
import { server } from '@/test/msw/server';
import { SuspendService } from './SuspendService';

// Suspend, resume (W42, DEC-657). The page reads the service's name; it cannot read whether the service is
// suspended, so the suspended view comes from the suspend answer on this page.

beforeEach(() => {
  resetLeadPosts();
  document.cookie = 'diucs_csrf=test-csrf-token';
});

describe('SuspendService', () => {
  it('asks why before it suspends: no reason shows "Choose why" and posts nothing', async () => {
    const user = userEvent.setup();
    render(<SuspendService serviceId="s-ucr-east" />);
    expect(await screen.findByRole('heading', { name: 'Suspend UCR East' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Suspend service' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose why');
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('suspends with the reason chosen and says how many open requests expired', async () => {
    const user = userEvent.setup();
    render(<SuspendService serviceId="s-ucr-east" />);
    await screen.findByRole('heading', { name: 'Suspend UCR East' });
    await user.click(screen.getByRole('radio', { name: 'Closed unexpectedly' }));
    await user.click(screen.getByRole('button', { name: 'Suspend service' }));
    expect(await screen.findByText('2 open requests expired.')).toBeInTheDocument();
    expect(seenLeadPosts).toHaveLength(1);
    expect(seenLeadPosts[0]).toMatchObject({
      path: '/api/bff/lead/services/s-ucr-east/suspend',
      csrf: 'test-csrf-token',
      body: { reason: 'closed-unexpectedly' },
    });
    expect(screen.getByRole('heading', { name: 'UCR East is suspended' })).toBeInTheDocument();
    expect(screen.getByText('The service was told by text. Resuming needs a call-back.')).toBeInTheDocument();
  });

  it('keeps Resume disabled until both confirmations are ticked, then posts both as true', async () => {
    const user = userEvent.setup();
    render(<SuspendService serviceId="s-ucr-east" />);
    await screen.findByRole('heading', { name: 'Suspend UCR East' });
    await user.click(screen.getByRole('radio', { name: 'Closed unexpectedly' }));
    await user.click(screen.getByRole('button', { name: 'Suspend service' }));
    await screen.findByRole('heading', { name: 'UCR East is suspended' });
    await user.click(screen.getByRole('button', { name: 'Resume service' }));

    const resume = screen.getByRole('button', { name: 'Resume service' });
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
    expect(await screen.findByRole('status')).toHaveTextContent('Resumed');
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

  it('answers a 403 with the words for a person who may not do this', async () => {
    server.use(
      http.post('/api/bff/lead/services/:id/suspend', () =>
        HttpResponse.json({ code: 'forbidden' }, { status: 403 }),
      ),
    );
    const user = userEvent.setup();
    render(<SuspendService serviceId="s-ucr-east" />);
    await screen.findByRole('heading', { name: 'Suspend UCR East' });
    await user.click(screen.getByRole('radio', { name: 'Other' }));
    await user.click(screen.getByRole('button', { name: 'Suspend service' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('You cannot do this. Ask a shift lead.');
  });

  it('has no axe violations on the suspend form', async () => {
    const { container } = render(<SuspendService serviceId="s-ucr-east" />);
    await screen.findByRole('heading', { name: 'Suspend UCR East' });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
