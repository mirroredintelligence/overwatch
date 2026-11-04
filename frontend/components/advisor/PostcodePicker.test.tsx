import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { PostcodePicker } from './PostcodePicker';

// The in-page postcode list (DEC-1332): a combobox the advisor can use by mouse or keyboard, drawn on the page.

const OPTIONS = ['DT4 4GB', 'DT4 4GR'];

function setup(overrides: { options?: string[]; onPick?: (postcode: string) => void } = {}) {
  const onType = vi.fn();
  const onPick = overrides.onPick ?? vi.fn();
  render(
    <PostcodePicker
      id="pc"
      listId="pc-list"
      value="DT4 4G"
      options={overrides.options ?? OPTIONS}
      invalid={false}
      dataEl="TEST-PC"
      onType={onType}
      onPick={onPick}
      onBlur={vi.fn()}
    />,
  );
  return { onType, onPick, input: screen.getByRole('combobox', { name: '' }) as HTMLInputElement };
}

describe('PostcodePicker', () => {
  it('opens its list on typing and picks by mouse', async () => {
    const onPick = vi.fn();
    const { input } = setup({ onPick });
    await userEvent.click(input);
    await userEvent.type(input, 'x');
    expect(input).toHaveAttribute('aria-expanded', 'true');
    await userEvent.click(screen.getByRole('option', { name: 'DT4 4GR' }));
    expect(onPick).toHaveBeenCalledWith('DT4 4GR');
  });

  it('moves with the arrow keys and picks with Enter', async () => {
    const onPick = vi.fn();
    const { input } = setup({ onPick });
    await userEvent.type(input, 'x');
    await userEvent.keyboard('{ArrowDown}{ArrowDown}{Enter}');
    expect(onPick).toHaveBeenCalledWith('DT4 4GR');
  });

  it('closes on Escape and offers nothing with no options', async () => {
    const { input } = setup();
    await userEvent.type(input, 'x');
    await userEvent.keyboard('{Escape}');
    expect(input).toHaveAttribute('aria-expanded', 'false');
  });

  it('shows no list when there are no suggestions', async () => {
    const { input } = setup({ options: [] });
    await userEvent.type(input, 'x');
    expect(input).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('listbox')).toBeNull();
  });
});
