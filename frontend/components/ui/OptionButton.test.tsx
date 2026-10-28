import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { OptionButton } from './OptionButton';

describe('OptionButton', () => {
  it('selected has aria-pressed true and unselected false', () => {
    const { rerender } = render(<OptionButton selected onSelect={() => {}}>Ward 4</OptionButton>);
    expect(screen.getByRole('button', { name: 'Ward 4' })).toHaveAttribute('aria-pressed', 'true');
    rerender(<OptionButton selected={false} onSelect={() => {}}>Ward 4</OptionButton>);
    expect(screen.getByRole('button', { name: 'Ward 4' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('hides the icon from the accessibility tree, selected or not', () => {
    const { container, rerender } = render(<OptionButton selected onSelect={() => {}}>Ward 4</OptionButton>);
    const icon = container.querySelector('svg');
    expect(icon).not.toBeNull();
    expect(icon).toHaveAttribute('aria-hidden', 'true');
    rerender(<OptionButton selected={false} onSelect={() => {}}>Ward 4</OptionButton>);
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
  });

  it('shows the hint under the label and includes it in the name', () => {
    render(<OptionButton selected={false} hint="Open until 20:00" onSelect={() => {}}>Ward 4</OptionButton>);
    expect(screen.getByText('Open until 20:00')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Ward 4/ })).toBeInTheDocument();
  });

  it('click calls onSelect', async () => {
    const fn = vi.fn();
    render(<OptionButton selected={false} onSelect={fn}>Ward 4</OptionButton>);
    await userEvent.click(screen.getByRole('button', { name: 'Ward 4' }));
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('renders data-el and has no axe violations', async () => {
    const { container } = render(
      <main>
        <OptionButton selected hint="h" onSelect={() => {}} dataEl="OPT-1">Ward 4</OptionButton>
        <OptionButton selected={false} onSelect={() => {}}>Ward 5</OptionButton>
      </main>,
    );
    expect(container.querySelector('[data-el="OPT-1"]')).not.toBeNull();
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
