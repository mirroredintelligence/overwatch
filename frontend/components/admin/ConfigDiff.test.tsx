import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { RAW_SETTINGS } from '@/test/fixtures/tenantAdmin';
import type { SettingSpec } from '@/lib/tenantAdmin/views';
import { ConfigDiff } from './ConfigDiff';

// The difference between two versions of the settings (TEN-076): one row per key that changed, what it was
// and what it is, a key at its default said as the default, and a clinical key marked in words.

const SPECS = RAW_SETTINGS.settings as SettingSpec[];

describe('ConfigDiff', () => {
  it('has a row for each changed key, with the old and the new value and the unit', () => {
    render(<ConfigDiff changedKeys={['pressureWatchFrom']} before={{ pressureWatchFrom: 4 }} after={{ pressureWatchFrom: 5 }} specs={SPECS} />);
    const table = screen.getByRole('table', { name: 'What changed' });
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Setting', 'Was', 'Now', 'Kind']);
    const row = within(table).getByRole('row', { name: /Pressure watch from/ });
    expect(within(row).getByText('4')).toBeInTheDocument();
    expect(within(row).getByText('5')).toBeInTheDocument();
    expect(within(row).getByText('Clinical')).toBeInTheDocument();
  });

  it('says the default, in words, for a key that is not overridden on either side', () => {
    render(<ConfigDiff changedKeys={['pressureWatchFrom', 'twiceADaySecondTime']} before={{}} after={{ twiceADaySecondTime: '14:30' }} specs={SPECS} />);
    const a = screen.getByRole('row', { name: /Pressure watch from/ });
    expect(within(a).getAllByText('3 (default)')).toHaveLength(2);
    const b = screen.getByRole('row', { name: /Twice a day second time/ });
    expect(within(b).getByText('14:00 (default)')).toBeInTheDocument();
    expect(within(b).getByText('14:30')).toBeInTheDocument();
  });

  it('marks an operational key as such, and a key the registry does not know as it is', () => {
    render(<ConfigDiff changedKeys={['systemName', 'strangeKey']} before={{ systemName: 'Old name' }} after={{ systemName: 'New name', strangeKey: 7 }} specs={SPECS} />);
    expect(within(screen.getByRole('row', { name: /System name/ })).getByText('Operational')).toBeInTheDocument();
    const strange = screen.getByRole('row', { name: /Strange key/ });
    expect(within(strange).getByText('7')).toBeInTheDocument();
  });

  it('says nothing changed when no key did', () => {
    render(<ConfigDiff changedKeys={[]} before={{}} after={{}} specs={SPECS} />);
    expect(screen.getByText('No setting changed.')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('prints text as typed, never as markup', () => {
    render(<ConfigDiff changedKeys={['systemName']} before={{}} after={{ systemName: '<b>bold</b>' }} specs={SPECS} />);
    expect(screen.getByText('<b>bold</b>')).toBeInTheDocument();
    expect(document.querySelector('b')).toBeNull();
  });

  it('has no axe violations', async () => {
    const { container } = render(<ConfigDiff changedKeys={['pressureWatchFrom']} before={{ pressureWatchFrom: 4 }} after={{ pressureWatchFrom: 5 }} specs={SPECS} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
