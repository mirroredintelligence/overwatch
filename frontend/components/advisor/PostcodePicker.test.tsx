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

describe('PostcodePicker compact (the assistant thread)', () => {
  const MANY = ['DT4 0AB', 'DT4 0AD', 'DT4 0AE', 'DT4 0AF', 'DT4 0AG', 'DT4 0AH', 'DT4 0AJ'];

  function compact(options: string[], onPick = vi.fn()) {
    render(
      <PostcodePicker
        id="pc"
        listId="pc-list"
        value="DT4"
        options={options}
        invalid={false}
        dataEl="TEST-PC"
        onType={vi.fn()}
        onPick={onPick}
        onBlur={vi.fn()}
        compact
      />,
    );
    return screen.getByRole('combobox') as HTMLInputElement;
  }

  it('shows five rows at most and says how many more, so the list never needs a scrollbar of its own', async () => {
    const input = compact(MANY);
    await userEvent.click(input);
    await userEvent.type(input, ' ');
    expect(screen.getAllByRole('option')).toHaveLength(5);
    expect(screen.getByText('2 more. Keep typing to narrow the list.')).toBeInTheDocument();
  });

  it('shows no note when everything fits, and still picks by mouse and by keyboard', async () => {
    const onPick = vi.fn();
    const input = compact(['DT4 0AB', 'DT4 0AD'], onPick);
    await userEvent.click(input);
    await userEvent.type(input, ' ');
    expect(screen.queryByText(/Keep typing/)).toBeNull();
    await userEvent.keyboard('{ArrowDown}{Enter}');
    expect(onPick).toHaveBeenCalledWith('DT4 0AB');
  });

  it('leaves the default list as it was: every option, no note', async () => {
    render(
      <PostcodePicker id="pc" listId="pc-list" value="DT4" options={MANY} invalid={false} dataEl="TEST-PC" onType={vi.fn()} onPick={vi.fn()} onBlur={vi.fn()} />,
    );
    const input = screen.getByRole('combobox');
    await userEvent.click(input);
    await userEvent.type(input, ' ');
    expect(screen.getAllByRole('option')).toHaveLength(7);
    expect(screen.queryByText(/Keep typing/)).toBeNull();
  });
});

