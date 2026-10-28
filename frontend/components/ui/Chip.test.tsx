import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { Chip } from './Chip';

describe('Chip', () => {
  it('click calls onPressedChange with the next value', async () => {
    const fn = vi.fn();
    const { rerender } = render(<Chip pressed={false} onPressedChange={fn}>Adult</Chip>);
    await userEvent.click(screen.getByRole('button', { name: 'Adult' }));
    expect(fn).toHaveBeenLastCalledWith(true);
    rerender(<Chip pressed onPressedChange={fn}>Adult</Chip>);
    await userEvent.click(screen.getByRole('button', { name: 'Adult' }));
    expect(fn).toHaveBeenLastCalledWith(false);
  });

  it('aria-pressed reflects the prop and it is a plain button', () => {
    const { rerender } = render(<Chip pressed={false} onPressedChange={() => {}}>Adult</Chip>);
    const el = screen.getByRole('button', { name: 'Adult' });
    expect(el).toHaveAttribute('type', 'button');
    expect(el).toHaveAttribute('aria-pressed', 'false');
    rerender(<Chip pressed onPressedChange={() => {}}>Adult</Chip>);
    expect(screen.getByRole('button', { name: 'Adult' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('Space and Enter toggle it', async () => {
    const fn = vi.fn();
    render(<Chip pressed={false} onPressedChange={fn}>Adult</Chip>);
    screen.getByRole('button', { name: 'Adult' }).focus();
    await userEvent.keyboard(' ');
    await userEvent.keyboard('{Enter}');
    expect(fn).toHaveBeenCalledTimes(2);
    expect(fn).toHaveBeenNthCalledWith(1, true);
    expect(fn).toHaveBeenNthCalledWith(2, true);
  });

  it('renders data-el and has no axe violations', async () => {
    const { container } = render(
      <main>
        <Chip pressed onPressedChange={() => {}} dataEl="CHIP-1">Adult</Chip>
      </main>,
    );
    expect(container.querySelector('[data-el="CHIP-1"]')).not.toBeNull();
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
