import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetLeadPosts, seenLeadPosts } from '@/test/msw/handlers/lead';
import { beforeEach } from 'vitest';
import { SetupTracker } from './SetupTracker';

// Track set-up (W43): each invitation's steps, where it is stuck, and what the lead can do about it.

beforeEach(() => {
  resetLeadPosts();
  document.cookie = 'diucs_csrf=test-csrf-token';
});

describe('SetupTracker', () => {
  it('says where an invitation is stuck, with the times it was invited and last seen', async () => {
    render(<SetupTracker />);
    expect(await screen.findByText('Stuck at: Notifications on. Invited 09:00, last seen 09:21.')).toBeInTheDocument();
  });

  it('says a complete set-up is complete, with its first report time', async () => {
    render(<SetupTracker />);
    expect(await screen.findByText('Complete. First report 10:12.')).toBeInTheDocument();
  });

  it('lists the seven steps, each done or not done in words', async () => {
    render(<SetupTracker />);
    const list = (await screen.findAllByRole('list', { name: 'Set-up steps' }))[0];
    const items = within(list).getAllByRole('listitem').map((item) => item.textContent);
    expect(items).toEqual([
      'Invited. Done.',
      'Number checked. Done.',
      'Channel chosen. Done.',
      'Installed. Done.',
      'Notifications on. Not done.',
      'PIN set. Not done.',
      'First report. Not done.',
    ]);
  });

  it('resends the invitation through the resend route', async () => {
    const user = userEvent.setup();
    render(<SetupTracker />);
    const card = (await screen.findByText('Stuck at: Notifications on. Invited 09:00, last seen 09:21.')).closest('section') as HTMLElement;
    await user.click(within(card).getByRole('button', { name: 'Resend invitation' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Invitation sent again.');
    expect(seenLeadPosts[0]).toMatchObject({ path: '/api/bff/lead/invitations/inv-1/resend' });
  });

  it('switches a reporter to text, and offers to phone them', async () => {
    const user = userEvent.setup();
    render(<SetupTracker />);
    const card = (await screen.findByText('Stuck at: Notifications on. Invited 09:00, last seen 09:21.')).closest('section') as HTMLElement;
    await user.click(within(card).getByRole('button', { name: 'Switch them to text' }));
    expect(seenLeadPosts[0]).toMatchObject({ path: '/api/bff/lead/invitations/inv-1/switch-to-text' });
    expect(within(card).getByRole('button', { name: 'Phone them' })).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(<SetupTracker />);
    await screen.findByText('Complete. First report 10:12.');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
