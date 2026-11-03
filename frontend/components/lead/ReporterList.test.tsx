import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { ReporterList, reporterStatus } from './ReporterList';
import type { Invitation } from './SetupTracker';

// The list of invited reporters: a ul of buttons, one per invitation, with the status as shape plus word, a
// seven-segment bar and filter chips (All, Stuck, In progress, Complete) that work on the loaded list.

const NOW = Date.parse('2026-10-30T09:40:00Z');
const DONE = { invited: true, numberChecked: true, channelChosen: true, installed: true, notificationsOn: true, pinSet: true, firstReport: true };

function invitation(id: string, name: string, role: string, done: number, lastSeen: string, firstReportAt: string | null = null): Invitation {
  const keys = Object.keys(DONE) as (keyof typeof DONE)[];
  const steps = { ...DONE };
  keys.forEach((key, index) => {
    steps[key] = index < done;
  });
  return { id, serviceId: `s-${id}`, serviceName: name, role, steps, invitedAt: '2026-10-30T09:00:00Z', lastSeen, firstReportAt };
}

const STUCK = invitation('inv-1', 'UCR East', 'Duty manager', 4, '2026-10-30T08:00:00Z');
const PROGRESS = invitation('inv-2', 'Community hospital Ward A', 'Ward manager', 5, '2026-10-30T09:30:00Z');
const INVITED = invitation('inv-3', 'SDEC Site 1', 'Clinical coordinator', 1, '2026-10-30T09:35:00Z');
const COMPLETE = invitation('inv-4', 'Reablement', 'Team lead', 7, '2026-10-30T09:12:00Z', '2026-10-30T09:12:00Z');
const ALL = [STUCK, PROGRESS, INVITED, COMPLETE];

function show(currentId: string | null = null, onOpen: (id: string) => void = () => undefined, items: readonly Invitation[] = ALL) {
  return render(<ReporterList items={items} now={NOW} currentId={currentId} onOpen={onOpen} />);
}

describe('reporterStatus', () => {
  it('calls a set-up complete when every step is done', () => {
    expect(reporterStatus(COMPLETE, NOW)).toBe('complete');
  });

  it('calls a set-up stuck when it is not complete and nothing has been seen for half an hour', () => {
    expect(reporterStatus(STUCK, NOW)).toBe('stuck');
  });

  it('calls a recent set-up in progress, or invited when only the invitation is done', () => {
    expect(reporterStatus(PROGRESS, NOW)).toBe('progress');
    expect(reporterStatus(INVITED, NOW)).toBe('invited');
  });
});

describe('ReporterList', () => {
  it('is a section with the heading Set-up progress, an Invite link and a list of buttons', () => {
    show();
    const section = screen.getByRole('region', { name: 'Set-up progress' });
    expect(within(section).getByRole('heading', { level: 2, name: 'Set-up progress' })).toBeInTheDocument();
    expect(within(section).getByRole('link', { name: 'Invite' })).toHaveAttribute('href', '/lead/reporters/invite');
    const list = within(section).getByRole('list');
    expect(within(list).getAllByRole('listitem')).toHaveLength(4);
    expect(within(list).getAllByRole('button')).toHaveLength(4);
  });

  it('shows each reporter with the service, the role and the status in words', () => {
    show();
    const rows = within(screen.getByRole('list')).getAllByRole('button');
    expect(rows[0]).toHaveTextContent('UCR East');
    expect(rows[0]).toHaveTextContent('Duty manager');
    expect(rows[0]).toHaveTextContent('Stuck');
    expect(rows[1]).toHaveTextContent('In progress');
    expect(rows[2]).toHaveTextContent('Invited');
    expect(rows[3]).toHaveTextContent('Complete');
  });

  it('says where a set-up that is not complete is waiting', () => {
    show();
    const rows = within(screen.getByRole('list')).getAllByRole('button');
    expect(rows[0]).toHaveTextContent('Waiting at: Notifications on');
    expect(rows[1]).toHaveTextContent('Waiting at: PIN set');
    expect(rows[3]).not.toHaveTextContent('Waiting at');
  });

  it('draws a bar of seven segments and says how many steps are done', () => {
    show();
    const bar = within(screen.getByRole('button', { name: /UCR East/ })).getByRole('img', { name: '4 of 7 steps done' });
    expect(bar.children).toHaveLength(7);
  });

  it('marks the open row with aria-current and no other', () => {
    show('inv-2');
    const rows = within(screen.getByRole('list')).getAllByRole('button');
    expect(rows.map((row) => row.getAttribute('aria-current'))).toEqual([null, 'true', null, null]);
  });

  it('opens a reporter by id when its row is chosen, by mouse or by keyboard', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    show(null, onOpen);
    await user.click(screen.getByRole('button', { name: /Reablement/ }));
    expect(onOpen).toHaveBeenLastCalledWith('inv-4');
    screen.getByRole('button', { name: /SDEC Site 1/ }).focus();
    await user.keyboard('{Enter}');
    expect(onOpen).toHaveBeenLastCalledWith('inv-3');
  });

  it('has the filter chips All, Stuck, In progress and Complete, with All pressed first', () => {
    show();
    const group = screen.getByRole('group', { name: 'Show' });
    const chips = within(group).getAllByRole('button');
    expect(chips.map((chip) => chip.textContent)).toEqual(['All', 'Stuck', 'In progress', 'Complete']);
    expect(chips.map((chip) => chip.getAttribute('aria-pressed'))).toEqual(['true', 'false', 'false', 'false']);
  });

  it('filters the list on the chips: Stuck, In progress (which includes invited), Complete and back to All', async () => {
    const user = userEvent.setup();
    show();
    const names = () => within(screen.getByRole('list')).getAllByRole('button').map((row) => row.textContent);
    await user.click(screen.getByRole('button', { name: 'Stuck' }));
    expect(names()).toHaveLength(1);
    expect(names()[0]).toContain('UCR East');
    expect(screen.getByRole('button', { name: 'Stuck' })).toHaveAttribute('aria-pressed', 'true');
    await user.click(screen.getByRole('button', { name: 'In progress' }));
    expect(names()).toHaveLength(2);
    expect(names()[0]).toContain('Community hospital Ward A');
    expect(names()[1]).toContain('SDEC Site 1');
    await user.click(screen.getByRole('button', { name: 'Complete' }));
    expect(names()).toHaveLength(1);
    expect(names()[0]).toContain('Reablement');
    await user.click(screen.getByRole('button', { name: 'All' }));
    expect(names()).toHaveLength(4);
  });

  it('says when no reporter matches a chip, in words', async () => {
    const user = userEvent.setup();
    show(null, () => undefined, [COMPLETE]);
    await user.click(screen.getByRole('button', { name: 'Stuck' }));
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
    expect(screen.getByText('No set-up is stuck.')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = show('inv-1');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
