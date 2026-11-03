import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetLeadPosts, seenLeadPosts } from '@/test/msw/handlers/lead';
import { ReporterDetail } from './ReporterDetail';
import type { Invitation } from './SetupTracker';

// One reporter's set-up: the seven steps as a timeline on the left, what the lead can do on the right. The
// board's per-step times, the chosen channel and the masked number are not in the data: only the invited time
// and the last-seen line are shown.

const NOW = Date.parse('2026-10-30T11:00:00Z');

const STUCK: Invitation = {
  id: 'inv-1',
  serviceId: 's-ucr-west',
  serviceName: 'UCR West',
  role: 'Duty manager',
  steps: { invited: true, numberChecked: true, channelChosen: true, installed: true, notificationsOn: false, pinSet: false, firstReport: false },
  invitedAt: '2026-10-30T09:00:00Z',
  lastSeen: '2026-10-30T09:21:00Z',
  firstReportAt: null,
};

const COMPLETE: Invitation = {
  id: 'inv-2',
  serviceId: 's-reablement',
  serviceName: 'Reablement',
  role: 'Team lead',
  steps: { invited: true, numberChecked: true, channelChosen: true, installed: true, notificationsOn: true, pinSet: true, firstReport: true },
  invitedAt: '2026-10-29T16:00:00Z',
  lastSeen: '2026-10-30T10:12:00Z',
  firstReportAt: '2026-10-30T10:12:00Z',
};

beforeEach(() => {
  resetLeadPosts();
  document.cookie = 'overwatch_csrf=test-csrf-token';
});

function show(item: Invitation = STUCK, extra: { onBack?: () => void; onNotice?: (text: string, failed: boolean) => void; changeNumber?: React.ReactNode } = {}) {
  return render(<ReporterDetail item={item} now={NOW} onBack={extra.onBack ?? (() => undefined)} onNotice={extra.onNotice ?? (() => undefined)} changeNumber={extra.changeNumber} />);
}

describe('ReporterDetail', () => {
  it('is a section named for the service, with its name as a heading and the role and invited time under it', () => {
    show();
    const section = screen.getByRole('region', { name: 'UCR West set-up' });
    expect(within(section).getByRole('heading', { level: 2, name: 'UCR West' })).toBeInTheDocument();
    expect(within(section).getByText('Duty manager · invited 09:00')).toBeInTheDocument();
  });

  it('says where it is stuck, with the times it was invited and last seen', () => {
    show();
    expect(screen.getByText('Stuck at: Notifications on.')).toBeInTheDocument();
    expect(screen.getByText(/Invited 09:00, last seen 09:21\./)).toBeInTheDocument();
  });

  it('says a set-up that is still recent is in progress, not stuck', () => {
    show({ ...STUCK, lastSeen: '2026-10-30T10:50:00Z' });
    expect(screen.getByText('In progress.')).toBeInTheDocument();
    expect(screen.queryByText(/^Stuck at/)).not.toBeInTheDocument();
  });

  it('says a complete set-up is complete, with its first report time, and offers no actions', () => {
    show(COMPLETE);
    expect(screen.getByText('Complete. First report 10:12.')).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'What you can do' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Resend the invitation' })).not.toBeInTheDocument();
  });

  it('lists the seven steps as a timeline, each done, waiting here or not done in words, with the invited time', () => {
    show();
    const list = screen.getByRole('list', { name: 'Set-up steps' });
    expect(within(list).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      'Invited 09:00. Done.',
      'Number checked. Done.',
      'Channel chosen. Done.',
      'Installed. Done.',
      'Notifications on. Waiting here.',
      'PIN set. Not done.',
      'First report. Not done.',
    ]);
  });

  it('marks the step it waits at with the word Waiting here and no step as waiting when complete', () => {
    show(COMPLETE);
    const items = within(screen.getByRole('list', { name: 'Set-up steps' })).getAllByRole('listitem');
    expect(items.every((item) => item.textContent?.endsWith('Done.'))).toBe(true);
  });

  it('has the actions group, with Resend the invitation first, then Switch them to text and Phone them', () => {
    show();
    const aside = screen.getByRole('group', { name: 'What you can do' });
    expect(within(aside).getAllByRole('button').slice(0, 3).map((button) => button.textContent)).toEqual([
      'Resend the invitation',
      'Switch them to text',
      'Phone them',
    ]);
  });

  it('resends the invitation through the resend route and tells the page', async () => {
    const user = userEvent.setup();
    const onNotice = vi.fn();
    show(STUCK, { onNotice });
    await user.click(screen.getByRole('button', { name: 'Resend the invitation' }));
    await vi.waitFor(() => expect(onNotice).toHaveBeenCalledWith('Invitation sent again.', false));
    expect(seenLeadPosts[0]).toMatchObject({ path: '/api/bff/lead/invitations/inv-1/resend' });
  });

  it('switches a reporter to text through the switch-to-text route', async () => {
    const user = userEvent.setup();
    const onNotice = vi.fn();
    show(STUCK, { onNotice });
    await user.click(screen.getByRole('button', { name: 'Switch them to text' }));
    await vi.waitFor(() => expect(onNotice).toHaveBeenCalledWith('They are switched to text.', false));
    expect(seenLeadPosts[0]).toMatchObject({ path: '/api/bff/lead/invitations/inv-1/switch-to-text' });
  });

  it('records what the service said by phone for the invitation\'s own service, with no case', async () => {
    const user = userEvent.setup();
    show();
    await user.click(screen.getByRole('button', { name: 'Phone them' }));
    await user.click(screen.getByRole('button', { name: 'Not accepting' }));
    await user.click(screen.getByRole('button', { name: 'Save position' }));
    await vi.waitFor(() => expect(seenLeadPosts).toHaveLength(1));
    expect(seenLeadPosts[0]).toMatchObject({ path: '/api/bff/lead/services/s-ucr-west/phoned', body: { said: 'not-accepting' } });
  });

  it('offers a way to change their number for this service, as a link, when no form is given', () => {
    show();
    const aside = screen.getByRole('group', { name: 'What you can do' });
    expect(within(aside).getByText('Change their number')).toBeInTheDocument();
    expect(within(aside).getByText('The new number gets a fresh code. The old one stops working.')).toBeInTheDocument();
    expect(within(aside).getByRole('link', { name: 'Change their number' })).toHaveAttribute('href', '/lead/reporters/number?service=s-ucr-west');
  });

  it('shows the number form it is given in place of the link', () => {
    show(STUCK, { changeNumber: <label>New number<input /></label> });
    const aside = screen.getByRole('group', { name: 'What you can do' });
    expect(within(aside).getByLabelText('New number')).toBeInTheDocument();
    expect(within(aside).queryByRole('link', { name: 'Change their number' })).not.toBeInTheDocument();
  });

  it('has a Back to the list button for the phone, which calls onBack', async () => {
    const user = userEvent.setup();
    const onBack = vi.fn();
    show(STUCK, { onBack });
    await user.click(screen.getByRole('button', { name: 'Back to the list' }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('has no axe violations', async () => {
    const { container } = show();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
