import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { MEASURES, PROMISES } from '@/lib/value/content';
import { ValueCase } from './ValueCase';

describe('ValueCase', () => {
  it('says what is promised, to each of four groups', () => {
    render(<ValueCase />);

    expect(screen.getByRole('heading', { level: 1, name: 'What we promise, and how we prove it' })).toBeInTheDocument();
    for (const pledge of PROMISES) {
      const card = screen.getByRole('region', { name: pledge.group });
      for (const item of pledge.items) expect(within(card).getByText(item)).toBeInTheDocument();
    }
    expect(PROMISES.map((pledge) => pledge.group)).toEqual(['Services', 'Call advisors and shift leads', 'Clinical advisors', 'COOs and ICB']);
  });

  it('lists the six measures with a baseline, a source and a target still to agree', () => {
    render(<ValueCase />);

    const table = screen.getByRole('table', { name: 'What we measure to show the value' });
    expect(within(table).getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual([
      'Measure',
      'Baseline (before)',
      'From the tool (after)',
      'Target',
    ]);
    expect(within(table).getAllByRole('row')).toHaveLength(1 + MEASURES.length);
    expect(within(table).getAllByText('[to agree]')).toHaveLength(MEASURES.length);
  });

  it('states no saving: the rules say no saving is claimed before the baseline is measured', () => {
    render(<ValueCase />);

    expect(screen.getByText(/No saving is claimed before the baseline is measured/)).toBeInTheDocument();
    expect(screen.getByText(/Show a range, not one number/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/\bsaves? \d|\d+ (minutes|hours) saved|£\s?\d/i);
  });

  it('links the launch kit to the tour and the lessons, and uses no deployment name', () => {
    render(<ValueCase />);

    expect(screen.getByRole('link', { name: 'A one-minute product tour by role' })).toHaveAttribute('href', '/tour');
    expect(screen.getByRole('link', { name: 'Two-minute lessons with a practice mode' })).toHaveAttribute('href', '/learn');
    expect(document.body.textContent).not.toMatch(/SPOA|Dorset/);
  });

  it('passes vitest-axe', async () => {
    const { container } = render(<ValueCase />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
