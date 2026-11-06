import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { ServicesBrowse } from './ServicesBrowse';

// The services by state, from the sample board (DEC-1343).

async function loaded(initial: Parameters<typeof ServicesBrowse>[0]['initial'] = []) {
  const view = render(<ServicesBrowse initial={initial} />);
  await waitFor(() => byEl('ADV-SERVICES-LIST'));
  return view;
}

describe('ServicesBrowse', () => {
  it('lists the services by name, not by status', async () => {
    await loaded();
    const names = within(byEl('ADV-SERVICES-LIST'))
      .getAllByRole('heading', { level: 2 })
      .map((heading) => heading.textContent ?? '');
    expect(names).toEqual([...names].sort((a, b) => a.localeCompare(b)));
    expect(screen.getByRole('status')).toHaveTextContent('Listed by name, not ranked.');
  });

  it('shows each state with its count as a toggle, and only the chosen state when one is chosen', async () => {
    await loaded(['limited']);
    const chip = byEl('ADV-SERVICES-FILTER-LIMITED');
    expect(chip).toHaveAttribute('aria-pressed', 'true');
    expect(chip).toHaveTextContent('Limited (2)');
    expect(within(byEl('ADV-SERVICES-LIST')).getAllByRole('heading', { level: 2 })).toHaveLength(2);
  });

  it('toggles a state on and off', async () => {
    await loaded();
    const chip = byEl('ADV-SERVICES-FILTER-NOT-ACCEPTING');
    expect(chip).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(chip);
    expect(chip).toHaveAttribute('aria-pressed', 'true');
    expect(within(byEl('ADV-SERVICES-LIST')).getAllByRole('heading', { level: 2 })).toHaveLength(1);
    await userEvent.click(chip);
    expect(chip).toHaveAttribute('aria-pressed', 'false');
  });

  it('says "Current capacity unavailable", not a number, for a service that is not updated', async () => {
    await loaded(['not-updated']);
    expect(within(byEl('ADV-SERVICES-LIST')).getAllByText('Current capacity unavailable').length).toBeGreaterThan(0);
  });

  it('has no axe violations', async () => {
    const { container } = await loaded();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
