import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { CodeEntry } from './CodeEntry';

// The last three digits of the number the code went to: the only part of it the page ever holds (DEC-900).
const ENDING = '456';

function setup(overrides: Partial<Parameters<typeof CodeEntry>[0]> = {}) {
  const onCheck = vi.fn();
  const onResend = vi.fn();
  const view = render(<CodeEntry ending={ENDING} onCheck={onCheck} onResend={onResend} {...overrides} />);
  return { ...view, onCheck, onResend };
}

describe('CodeEntry', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows the wording from the screen and the number masked to its last three digits', () => {
    const { container } = setup();
    expect(screen.getByRole('heading', { level: 2, name: 'Enter your code' })).toBeInTheDocument();
    expect(screen.getByText('We sent a code to 07xxx xxx456.')).toBeInTheDocument();
    expect(screen.getByText('The code works for 10 minutes. After 5 wrong tries you must ask for a new code.')).toBeInTheDocument();
    // The page holds only the ending: no whole number can be on it.
    expect(container.textContent).not.toMatch(/07\d{9}/);
  });

  it('gives the code field the numeric keyboard and one-time-code autofill', () => {
    setup();
    const field = screen.getByLabelText('6-digit code');
    expect(field).toHaveAttribute('inputmode', 'numeric');
    expect(field).toHaveAttribute('autocomplete', 'one-time-code');
  });

  it('counts the resend down from one minute, then offers a new code', () => {
    vi.useFakeTimers();
    setup();
    expect(screen.getByText('Send a new code in 1:00')).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(18_000);
    });
    expect(screen.getByText('Send a new code in 0:42')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send a new code' })).not.toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(42_000);
    });
    expect(screen.queryByText(/Send a new code in/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send a new code' })).toBeInTheDocument();
  });

  it('restarts the countdown and calls onResend when the new code is asked for', () => {
    vi.useFakeTimers();
    const { onResend } = setup();
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send a new code' }));
    expect(onResend).toHaveBeenCalledTimes(1);
    expect(screen.getByText('Send a new code in 1:00')).toBeInTheDocument();
  });

  it('checks the typed code when Check code is pressed', async () => {
    const { onCheck } = setup();
    await userEvent.type(screen.getByLabelText('6-digit code'), '123456');
    await userEvent.click(screen.getByRole('button', { name: 'Check code' }));
    expect(onCheck).toHaveBeenCalledWith('123456');
  });

  it('shows an error inline on the field, linked by aria-describedby, and marks it invalid', () => {
    setup({ error: 'That code is not right. You have 3 tries left.' });
    const field = screen.getByLabelText('6-digit code');
    expect(field).toHaveAttribute('aria-invalid', 'true');
    const described = field.getAttribute('aria-describedby') ?? '';
    expect(described).not.toBe('');
    expect(document.getElementById(described.split(' ')[0] ?? '')?.textContent).toContain(
      'That code is not right. You have 3 tries left.',
    );
  });

  it('has no axe violations with an error shown', async () => {
    const { container } = setup({ error: 'That code is not right.' });
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
