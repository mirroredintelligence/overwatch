import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { ReasonChips } from './ReasonChips';

// The decline, withdraw and not-reached reasons (artboard B4, board 2): one choice from a short list.

const OPTIONS = [
  { value: 'full', label: 'We are full' },
  { value: 'criteria', label: 'Outside our criteria' },
  { value: 'staffing', label: 'Staffing or transport' },
  { value: 'other', label: 'Other' },
] as const;

function Controlled({ initial = null, onPick }: { initial?: string | null; onPick?: (v: string) => void }) {
  const [value, setValue] = useState<string | null>(initial);
  return (
    <ReasonChips
      label="Why can you not take this patient?"
      options={OPTIONS}
      value={value}
      onChange={(v) => {
        setValue(v);
        onPick?.(v);
      }}
    />
  );
}

describe('ReasonChips', () => {
  it('is a radio group named by its label, with one radio per reason', async () => {
    const { container } = render(<Controlled />);
    const group = screen.getByRole('radiogroup', { name: 'Why can you not take this patient?' });
    expect(group).toBeInTheDocument();
    expect(screen.getAllByRole('radio').map((r) => r.textContent)).toEqual(OPTIONS.map((o) => o.label));
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('checks the chosen reason only', () => {
    render(<Controlled initial="criteria" />);
    expect(screen.getByRole('radio', { name: 'Outside our criteria' })).toBeChecked();
    expect(screen.getByRole('radio', { name: 'We are full' })).not.toBeChecked();
  });

  it('chooses a reason on a click and reports it', async () => {
    const onPick = vi.fn();
    render(<Controlled onPick={onPick} />);
    await userEvent.click(screen.getByRole('radio', { name: 'Other' }));
    expect(onPick).toHaveBeenCalledWith('other');
    expect(screen.getByRole('radio', { name: 'Other' })).toBeChecked();
  });

  it('puts only one chip in the tab order: the chosen one, or the first when nothing is chosen', () => {
    const { unmount } = render(<Controlled />);
    expect(screen.getAllByRole('radio').map((r) => r.tabIndex)).toEqual([0, -1, -1, -1]);
    unmount();
    render(<Controlled initial="staffing" />);
    expect(screen.getAllByRole('radio').map((r) => r.tabIndex)).toEqual([-1, -1, 0, -1]);
  });

  it('moves the choice and the focus with the arrow keys, wrapping at both ends', async () => {
    render(<Controlled initial="full" />);
    screen.getByRole('radio', { name: 'We are full' }).focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(screen.getByRole('radio', { name: 'Outside our criteria' })).toBeChecked();
    expect(screen.getByRole('radio', { name: 'Outside our criteria' })).toHaveFocus();
    await userEvent.keyboard('{ArrowDown}');
    expect(screen.getByRole('radio', { name: 'Staffing or transport' })).toHaveFocus();
    await userEvent.keyboard('{ArrowLeft}{ArrowUp}{ArrowLeft}');
    expect(screen.getByRole('radio', { name: 'Other' })).toBeChecked();
    expect(screen.getByRole('radio', { name: 'Other' })).toHaveFocus();
    await userEvent.keyboard('{ArrowRight}');
    expect(screen.getByRole('radio', { name: 'We are full' })).toBeChecked();
  });

  it('jumps to the first and last reason with Home and End', async () => {
    render(<Controlled initial="criteria" />);
    screen.getByRole('radio', { name: 'Outside our criteria' }).focus();
    await userEvent.keyboard('{End}');
    expect(screen.getByRole('radio', { name: 'Other' })).toBeChecked();
    await userEvent.keyboard('{Home}');
    expect(screen.getByRole('radio', { name: 'We are full' })).toBeChecked();
  });

  it('shows a tick on the chosen chip as well as the colour', () => {
    render(<Controlled initial="full" />);
    expect(screen.getByRole('radio', { name: 'We are full' }).querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
    expect(screen.getByRole('radio', { name: 'Other' }).querySelector('svg')).toBeNull();
  });

  it('can be disabled, and then ignores a click', async () => {
    const onChange = vi.fn();
    render(<ReasonChips label="Why" options={OPTIONS} value={null} onChange={onChange} disabled />);
    await userEvent.click(screen.getByRole('radio', { name: 'Other' }));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole('radio', { name: 'Other' })).toBeDisabled();
  });
});
