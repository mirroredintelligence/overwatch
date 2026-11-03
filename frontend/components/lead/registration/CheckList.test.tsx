import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { OVERVIEW } from '@/test/fixtures/registration';
import { CheckList, firstProblem } from './CheckList';

describe('CheckList', () => {
  it('lists every check with a shape and a word, and the action only on a check that needs attention', async () => {
    const { container } = render(<CheckList checks={OVERVIEW.automaticChecks} />);
    expect(screen.getByRole('heading', { level: 2, name: 'Checks the system did' })).toBeInTheDocument();
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(3);

    const passed = within(items[0]!);
    expect(passed.getByText('ODS code found, active, NHS trust')).toBeInTheDocument();
    expect(passed.getByText('Passed:')).toBeInTheDocument();
    expect(items[0]).toHaveAttribute('data-ok', 'true');

    const problem = within(items[2]!);
    expect(problem.getByText('Criteria owner email is not an organisation address')).toBeInTheDocument();
    expect(problem.getByText('Needs attention:')).toBeInTheDocument();
    expect(problem.getByText('Ask for an organisation address').tagName).toBe('STRONG');
    expect(items[2]).toHaveAttribute('data-ok', 'false');
    // The shape is decoration: the word carries the meaning.
    expect(container.querySelectorAll('[aria-hidden="true"]').length).toBeGreaterThanOrEqual(3);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows the address check that passes with no area set as a pass', () => {
    render(<CheckList checks={[{ key: 'address', label: 'No area limit is set', ok: true }]} />);
    const item = screen.getByRole('listitem');
    expect(within(item).getByText('Passed:')).toBeInTheDocument();
    expect(within(item).getByText('No area limit is set')).toBeInTheDocument();
  });

  it('says so when there are no checks yet', () => {
    render(<CheckList checks={[]} />);
    expect(screen.getByText('No checks were run.')).toBeInTheDocument();
  });
});

describe('firstProblem', () => {
  it('is the first check that is not ok, in the order the back end gave', () => {
    const checks = [
      { key: 'a', label: 'A', ok: true },
      { key: 'b', label: 'B', ok: false },
      { key: 'c', label: 'C', ok: false },
    ];
    expect(firstProblem(checks)?.key).toBe('b');
  });

  it('is undefined when every check passed', () => {
    expect(firstProblem([{ key: 'a', label: 'A', ok: true }])).toBeUndefined();
  });
});
