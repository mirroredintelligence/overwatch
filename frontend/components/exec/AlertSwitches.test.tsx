import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { DEFAULT_ALERT_PREFERENCES, type AlertPreferences } from '@/lib/exec/alertPrefs';
import { runAxe } from '@/test/a11y';
import { AlertSwitches } from './AlertSwitches';

function Harness({ initial = DEFAULT_ALERT_PREFERENCES as AlertPreferences }: { initial?: AlertPreferences }) {
  const [prefs, setPrefs] = useState(initial);
  return (
    <AlertSwitches
      prefs={prefs}
      onChange={(next) => setPrefs((current) => ({ ...current, ...next }))}
    />
  );
}

describe('AlertSwitches', () => {
  it('shows the defaults as labelled switches, with the weekly summary off', () => {
    render(<Harness />);
    expect(screen.getByRole('switch', { name: /A service closes unexpectedly/ })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('switch', { name: /A service goes over capacity/ })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('switch', { name: /System pressure rises/ })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('switch', { name: /Weekly summary/ })).toHaveAttribute('aria-checked', 'false');
    expect(screen.getByRole('switch', { name: /Daily summary/ })).toHaveAttribute('aria-checked', 'true');
  });

  it('toggles a switch with the Space key', async () => {
    render(<Harness />);
    const weekly = screen.getByRole('switch', { name: /Weekly summary/ });
    weekly.focus();
    await userEvent.keyboard(' ');
    expect(weekly).toHaveAttribute('aria-checked', 'true');
    expect(weekly).toHaveAttribute('data-el', 'EXEC-ALERT-WEEKLY-SWITCH');
  });

  it('says On or Off in words beside each switch, and the word follows the switch', async () => {
    render(<Harness />);
    const weekly = screen.getByRole('switch', { name: /Weekly summary/ });
    expect(within(weekly).getByText('Off')).toBeInTheDocument();
    expect(within(screen.getByRole('switch', { name: /Daily summary/ })).getByText('On')).toBeInTheDocument();
    await userEvent.click(weekly);
    expect(within(weekly).getByText('On')).toBeInTheDocument();
  });

  it('reveals the After 2 hrs or After 4 hrs choice under not-updated when it is on, and hides it when off', async () => {
    render(<Harness />);
    expect(screen.getByRole('button', { name: 'After 2 hrs' })).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(screen.getByRole('switch', { name: /A service has not updated/ }));
    expect(screen.queryByRole('button', { name: 'After 2 hrs' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('switch', { name: /A service has not updated/ }));
    expect(screen.getByRole('button', { name: 'After 4 hrs' })).toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<Harness />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
