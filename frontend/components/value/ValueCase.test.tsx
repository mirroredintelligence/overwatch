import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { LAUNCH_KIT, MEASURES, PROMISES } from '@/lib/value/content';
import { ValueCase } from './ValueCase';

// The board shows three measures and a "3 more measures" disclosure. The data holds six.
const SHOWN_MEASURES = 3;

describe('ValueCase', () => {
  it('shows the product name and the page title in the header', () => {
    render(<ValueCase />);

    expect(screen.getByText('Overwatch')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'What we promise, and how we prove it' })).toBeInTheDocument();
  });

  it('says what is promised, to each of four groups, as a list with a mark on each line', () => {
    render(<ValueCase />);

    for (const pledge of PROMISES) {
      const card = screen.getByRole('region', { name: pledge.group });
      expect(within(card).getByRole('list')).toBeInTheDocument();
      for (const item of pledge.items) expect(within(card).getByText(item)).toBeInTheDocument();
    }
    expect(PROMISES.map((pledge) => pledge.group)).toEqual(['Services', 'Call advisors and shift leads', 'Clinical advisors', 'COOs and ICB']);
  });

  it('shows the first three measures with the board headings and a target still to agree', () => {
    render(<ValueCase />);

    const table = screen.getByRole('table', { name: 'What we measure to show the value' });
    expect(within(table).getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual([
      'Measure',
      'Before go-live',
      'After',
      'Target',
    ]);
    expect(within(table).getAllByRole('row')).toHaveLength(1 + SHOWN_MEASURES);
    expect(within(table).getAllByText('[to agree]')).toHaveLength(SHOWN_MEASURES);
  });

  it('opens the other measures from a disclosure that says how many there are', async () => {
    const user = userEvent.setup();
    render(<ValueCase />);

    const more = screen.getByRole('button', { name: `${MEASURES.length - SHOWN_MEASURES} more measures` });
    expect(more).toHaveAttribute('aria-expanded', 'false');

    await user.click(more);

    expect(more).toHaveAttribute('aria-expanded', 'true');
    const table = screen.getByRole('table', { name: 'What we measure to show the value' });
    expect(within(table).getAllByRole('row')).toHaveLength(1 + MEASURES.length);
    expect(within(table).getAllByText('[to agree]')).toHaveLength(MEASURES.length);
    for (const row of MEASURES) expect(within(table).getByRole('rowheader', { name: row.measure })).toBeInTheDocument();
  });

  it('opens and closes the disclosure from the keyboard', async () => {
    const user = userEvent.setup();
    render(<ValueCase />);

    await user.tab();
    const more = screen.getByRole('button', { name: `${MEASURES.length - SHOWN_MEASURES} more measures` });
    expect(more).toHaveFocus();

    await user.keyboard('{Enter}');
    expect(more).toHaveAttribute('aria-expanded', 'true');

    await user.keyboard(' ');
    expect(more).toHaveAttribute('aria-expanded', 'false');
  });

  it('states no saving: the rules say no saving is claimed before the baseline is measured', () => {
    render(<ValueCase />);

    expect(screen.getByText(/No saving is claimed before the baseline is measured/)).toBeInTheDocument();
    expect(screen.getByText(/Show a range, not one number/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/\bsaves? \d|\d+ (minutes|hours) saved|£\s?\d/i);
  });

  it('lists the launch kit, and links the tour and the lessons, with no deployment name', () => {
    render(<ValueCase />);

    const kit = screen.getByRole('region', { name: 'Launch kit' });
    expect(within(kit).getAllByRole('listitem')).toHaveLength(LAUNCH_KIT.length);
    expect(screen.getByRole('link', { name: 'A one-minute product tour by role' })).toHaveAttribute('href', '/tour');
    expect(screen.getByRole('link', { name: 'Two-minute lessons with a practice mode' })).toHaveAttribute('href', '/learn');
    expect(document.body.textContent).not.toMatch(/SPOA|Dorset/);
  });

  it('passes vitest-axe', async () => {
    const { container } = render(<ValueCase />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
