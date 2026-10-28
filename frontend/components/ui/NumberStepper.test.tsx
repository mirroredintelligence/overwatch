import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { NumberStepper } from './NumberStepper';

function setup(value: number | null, max = 8, min = 0) {
  const onChange = vi.fn();
  render(
    <NumberStepper
      label="Referrals"
      value={value}
      min={min}
      max={max}
      hint="referrals · usual range 0 to 8"
      onChange={onChange}
    />,
  );
  return onChange;
}

describe('NumberStepper', () => {
  it('increase from 3 calls onChange(4)', async () => {
    const onChange = setup(3);
    await userEvent.click(screen.getByRole('button', { name: 'Increase by one' }));
    expect(onChange).toHaveBeenCalledWith(4);
  });

  it('increase at max stays at max', async () => {
    const onChange = setup(8);
    await userEvent.click(screen.getByRole('button', { name: 'Increase by one' }));
    expect(onChange).toHaveBeenCalledWith(8);
  });

  it('decrease from 3 calls onChange(2) and at min stays at min', async () => {
    const a = setup(3);
    await userEvent.click(screen.getByRole('button', { name: 'Decrease by one' }));
    expect(a).toHaveBeenCalledWith(2);
  });

  it('decrease at min stays at min', async () => {
    const onChange = setup(0);
    await userEvent.click(screen.getByRole('button', { name: 'Decrease by one' }));
    expect(onChange).toHaveBeenCalledWith(0);
  });

  it('decrease from null gives min', async () => {
    const onChange = setup(null, 8, 1);
    await userEvent.click(screen.getByRole('button', { name: 'Decrease by one' }));
    expect(onChange).toHaveBeenCalledWith(1);
  });

  it('increase from null gives min', async () => {
    const onChange = setup(null, 8, 1);
    await userEvent.click(screen.getByRole('button', { name: 'Increase by one' }));
    expect(onChange).toHaveBeenCalledWith(1);
  });

  it('typing 12 with max 8 gives 8', async () => {
    const onChange = vi.fn();
    function Harness() {
      const [v, setV] = useState<number | null>(null);
      return (
        <NumberStepper label="Referrals" value={v} min={0} max={8} onChange={(n) => { onChange(n); setV(n); }} />
      );
    }
    render(<Harness />);
    await userEvent.type(screen.getByRole('textbox', { name: 'Referrals' }), '12');
    expect(onChange).toHaveBeenLastCalledWith(8);
  });

  it('typing a letter is ignored', async () => {
    const onChange = setup(null);
    await userEvent.type(screen.getByRole('textbox', { name: 'Referrals' }), 'a');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('clearing the input reports null', async () => {
    const onChange = setup(3);
    await userEvent.clear(screen.getByRole('textbox', { name: 'Referrals' }));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it('input is numeric, named by the label, shows value, placeholder and hint', () => {
    setup(null);
    const input = screen.getByRole('textbox', { name: 'Referrals' });
    expect(input).toHaveAttribute('inputmode', 'numeric');
    expect(input).toHaveAttribute('placeholder', '–');
    expect(screen.getByText('referrals · usual range 0 to 8')).toBeInTheDocument();
  });

  it('shows the value', () => {
    setup(3);
    expect(screen.getByRole('textbox', { name: 'Referrals' })).toHaveValue('3');
  });

  it('renders data-el and has no axe violations', async () => {
    const { container } = render(
      <main>
        <NumberStepper label="Referrals" value={3} min={0} max={8} onChange={() => {}} dataEl="STEP-1" />
      </main>,
    );
    expect(container.querySelector('[data-el="STEP-1"]')).not.toBeNull();
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
