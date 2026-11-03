import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { DisclosureRow } from './DisclosureRow';

// A closed row at the foot of the overview (the board's "Criteria to review" and "Declined despite showing
// capacity"): a line that says its answer, and one panel that opens on request.

function Harness({ onToggle }: { onToggle?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <DisclosureRow
      open={open}
      onToggle={() => {
        onToggle?.();
        setOpen((value) => !value);
      }}
      title="Criteria to review"
      hint="2 services, the soonest in 7 days"
    >
      <button type="button">Open the criteria</button>
    </DisclosureRow>
  );
}

describe('DisclosureRow', () => {
  it('says its title and its answer in one line, closed', () => {
    render(<Harness />);
    const button = screen.getByRole('button', { name: /Criteria to review/ });
    expect(button).toHaveTextContent('2 services, the soonest in 7 days');
    expect(button).toHaveAttribute('aria-expanded', 'false');
  });

  it('keeps the panel out of the tab order and the reading order while closed', () => {
    render(<Harness />);
    expect(screen.getByText('Open the criteria').closest('[inert]')).not.toBeNull();
  });

  it('opens the panel on a click, and closes it on the next', async () => {
    const onToggle = vi.fn();
    render(<Harness onToggle={onToggle} />);
    const button = screen.getByRole('button', { name: /Criteria to review/ });
    await userEvent.click(button);
    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(button).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('button', { name: 'Open the criteria' })).toBeInTheDocument();
    expect(screen.getByText('Open the criteria').closest('[inert]')).toBeNull();
    await userEvent.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'false');
  });

  it('opens from the keyboard', async () => {
    render(<Harness />);
    await userEvent.tab();
    expect(screen.getByRole('button', { name: /Criteria to review/ })).toHaveFocus();
    await userEvent.keyboard('{Enter}');
    expect(screen.getByRole('button', { name: 'Open the criteria' })).toBeInTheDocument();
  });

  it('has no axe violations, closed or open', async () => {
    const { container } = render(<Harness />);
    expect(await runAxe(container)).toHaveNoViolations();
    await userEvent.click(screen.getByRole('button', { name: /Criteria to review/ }));
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
