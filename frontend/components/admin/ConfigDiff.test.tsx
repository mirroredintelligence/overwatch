import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { RAW_SETTINGS } from '@/test/fixtures/tenantAdmin';
import type { SettingSpec } from '@/lib/tenantAdmin/views';
import { ConfigDiff } from './ConfigDiff';

// The difference between two versions of the settings (TEN-076, board A3): one card per key that changed, with
// what it was and what it is in labelled Was and Now groups, a key at its default said as the default, a list
// of codes as chips with the additions marked, and a clinical key marked in a word.

const SPECS = RAW_SETTINGS.settings as SettingSpec[];

describe('ConfigDiff', () => {
  it('has a card for each changed key, with the old and the new value in Was and Now groups', () => {
    render(<ConfigDiff changedKeys={['pressureWatchFrom']} before={{ pressureWatchFrom: 4 }} after={{ pressureWatchFrom: 5 }} specs={SPECS} />);
    expect(screen.getByRole('heading', { level: 2, name: 'What changed · 1 setting' })).toBeInTheDocument();
    const card = screen.getByRole('region', { name: 'Pressure watch from' });
    expect(within(within(card).getByRole('group', { name: 'Was' })).getByText('4')).toBeInTheDocument();
    expect(within(within(card).getByRole('group', { name: 'Now' })).getByText('5')).toBeInTheDocument();
    expect(within(card).getByText('Clinical')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('counts the settings in the heading', () => {
    render(<ConfigDiff changedKeys={['pressureWatchFrom', 'systemName']} before={{}} after={{ pressureWatchFrom: 5, systemName: 'A' }} specs={SPECS} />);
    expect(screen.getByRole('heading', { level: 2, name: 'What changed · 2 settings' })).toBeInTheDocument();
  });

  it('says the default, in words, for a key that is not overridden on either side', () => {
    render(<ConfigDiff changedKeys={['pressureWatchFrom', 'twiceADaySecondTime']} before={{}} after={{ twiceADaySecondTime: '14:30' }} specs={SPECS} />);
    const a = screen.getByRole('region', { name: 'Pressure watch from' });
    expect(within(a).getAllByText('3 (default)')).toHaveLength(2);
    const b = screen.getByRole('region', { name: 'Twice a day second time' });
    expect(within(b).getByText('14:00 (default)')).toBeInTheDocument();
    expect(within(b).getByText('14:30')).toBeInTheDocument();
  });

  it('shows a list of codes as chips, marks the additions, and says in words what was added', () => {
    render(<ConfigDiff changedKeys={['alertDefaultKinds']} before={{ alertDefaultKinds: ['service-closed'] }} after={{ alertDefaultKinds: ['service-closed', 'not-updated', 'over-capacity'] }} specs={SPECS} />);
    const card = screen.getByRole('region', { name: 'Alert default kinds' });
    const was = within(card).getByRole('group', { name: 'Was' });
    expect(within(was).getAllByRole('listitem')).toHaveLength(1);
    const now = within(card).getByRole('group', { name: 'Now' });
    expect(within(now).getAllByRole('listitem')).toHaveLength(3);
    expect(within(now).getByText('not-updated')).toBeInTheDocument();
    expect(within(now).getAllByText('Added')).toHaveLength(2);
    expect(within(card).getByText('In words: added not-updated and over-capacity.')).toBeInTheDocument();
  });

  it('says in words what was removed from a list of codes', () => {
    render(<ConfigDiff changedKeys={['alertDefaultKinds']} before={{ alertDefaultKinds: ['service-closed', 'over-capacity'] }} after={{ alertDefaultKinds: ['over-capacity'] }} specs={SPECS} />);
    expect(screen.getByText('In words: removed service-closed.')).toBeInTheDocument();
  });

  it('marks an operational key as such, and a key the registry does not know as it is', () => {
    render(<ConfigDiff changedKeys={['systemName', 'strangeKey']} before={{ systemName: 'Old name' }} after={{ systemName: 'New name', strangeKey: 7 }} specs={SPECS} />);
    expect(within(screen.getByRole('region', { name: 'System name' })).getByText('Operational')).toBeInTheDocument();
    const strange = screen.getByRole('region', { name: 'Strange key' });
    expect(within(strange).getByText('7')).toBeInTheDocument();
    expect(within(strange).queryByText('Clinical')).not.toBeInTheDocument();
    expect(within(strange).queryByText('Operational')).not.toBeInTheDocument();
  });

  it('says nothing changed when no key did', () => {
    render(<ConfigDiff changedKeys={[]} before={{}} after={{}} specs={SPECS} />);
    expect(screen.getByText('No setting changed.')).toBeInTheDocument();
    expect(screen.queryByRole('region')).not.toBeInTheDocument();
  });

  it('prints text as typed, never as markup', () => {
    render(<ConfigDiff changedKeys={['systemName']} before={{}} after={{ systemName: '<b>bold</b>' }} specs={SPECS} />);
    expect(screen.getByText('<b>bold</b>')).toBeInTheDocument();
    expect(document.querySelector('b')).toBeNull();
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <ConfigDiff
        changedKeys={['pressureWatchFrom', 'alertDefaultKinds']}
        before={{ pressureWatchFrom: 4, alertDefaultKinds: ['service-closed'] }}
        after={{ pressureWatchFrom: 5, alertDefaultKinds: ['service-closed', 'not-updated'] }}
        specs={SPECS}
      />,
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
