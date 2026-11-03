import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { NumberStepper } from './NumberStepper';

// Artboards B1 (controls open), B2 (empty: dashed box with an en dash) and D1 (laptop).

function Harness({ start, max }: { start: number | null; max?: number }) {
  const [value, setValue] = useState<number | null>(start);
  return <NumberStepper label="Number of referrals" title="New number of referrals" unit="referrals" usualMin={0} usualMax={8} max={max} value={value} onChange={setValue} dataEl="STEP" />;
}

describe('NumberStepper (reporter)', () => {
  it('has a minus, a number box and a plus, with the unit and usual range under them', () => {
    render(<Harness start={4} />);
    expect(screen.getByRole('button', { name: 'Decrease by one' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Increase by one' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Number of referrals' })).toHaveValue('4');
    expect(screen.getByText('referrals, usual range 0 to 8')).toBeInTheDocument();
    expect(screen.getByText('New number of referrals')).toBeInTheDocument();
  });

  it('describes the number box by the usual range', () => {
    render(<Harness start={4} />);
    const box = screen.getByRole('textbox', { name: 'Number of referrals' });
    expect(box).toHaveAccessibleDescription('referrals, usual range 0 to 8');
  });

  it('steps up and down by one with the buttons', async () => {
    const user = userEvent.setup();
    render(<Harness start={4} />);
    await user.click(screen.getByRole('button', { name: 'Increase by one' }));
    expect(screen.getByRole('textbox')).toHaveValue('5');
    await user.click(screen.getByRole('button', { name: 'Decrease by one' }));
    await user.click(screen.getByRole('button', { name: 'Decrease by one' }));
    expect(screen.getByRole('textbox')).toHaveValue('3');
  });

  it('never goes below zero', async () => {
    const user = userEvent.setup();
    render(<Harness start={0} />);
    await user.click(screen.getByRole('button', { name: 'Decrease by one' }));
    expect(screen.getByRole('textbox')).toHaveValue('0');
  });

  it('allows a figure far above the usual range (the page asks once), up to the hard maximum', async () => {
    const user = userEvent.setup();
    render(<Harness start={null} max={99} />);
    const box = screen.getByRole('textbox');
    await user.type(box, '40');
    expect(box).toHaveValue('40');
    await user.clear(box);
    await user.type(box, '500');
    expect(box).toHaveValue('99');
  });

  it('steps with the arrow keys in the number box', async () => {
    const user = userEvent.setup();
    render(<Harness start={4} />);
    screen.getByRole('textbox').focus();
    await user.keyboard('{ArrowUp}{ArrowUp}');
    expect(screen.getByRole('textbox')).toHaveValue('6');
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('textbox')).toHaveValue('5');
  });

  it('is empty at first: a dashed box with an en dash, flagged for the style and not read as a number', () => {
    render(<Harness start={null} />);
    const box = screen.getByRole('textbox', { name: 'Number of referrals' });
    expect(box).toHaveValue('');
    expect(box).toHaveAttribute('placeholder', '–');
    expect(box).toHaveAttribute('data-empty', 'true');
  });

  it('lands on the lowest number from empty with either button, and is no longer empty', async () => {
    const user = userEvent.setup();
    render(<Harness start={null} />);
    await user.click(screen.getByRole('button', { name: 'Increase by one' }));
    const box = screen.getByRole('textbox');
    expect(box).toHaveValue('0');
    expect(box).not.toHaveAttribute('data-empty');
  });

  it('goes back to empty when the box is cleared, and ignores letters', async () => {
    const user = userEvent.setup();
    render(<Harness start={4} />);
    const box = screen.getByRole('textbox');
    await user.type(box, 'ab');
    expect(box).toHaveValue('4');
    await user.clear(box);
    expect(box).toHaveValue('');
    expect(box).toHaveAttribute('data-empty', 'true');
  });

  it('makes the controls 76px', () => {
    const css = readFileSync(join(__dirname, 'NumberStepper.module.css'), 'utf8');
    expect(css).toMatch(/width:\s*76px/);
    expect(css).toMatch(/height:\s*76px/);
    expect(css).toMatch(/dashed/);
  });

  it('has no accessibility violations, empty or not', async () => {
    const filled = render(<Harness start={4} />);
    expect(await runAxe(filled.container)).toHaveNoViolations();
    filled.unmount();
    const empty = render(<Harness start={null} />);
    expect(await runAxe(empty.container)).toHaveNoViolations();
  });
});
