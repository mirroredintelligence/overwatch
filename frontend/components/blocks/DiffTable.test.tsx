import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { DiffTable } from './DiffTable';

const rows = [
  { id: 'age', what: 'Youngest age', was: '65', now: '60' },
  { id: 'review', what: 'Review date', was: '30 Oct', now: '23 Jan' },
];

describe('DiffTable', () => {
  it('is a table with What, Was and Now columns', () => {
    render(<DiffTable label="What changed" rows={rows} />);
    const table = screen.getByRole('table', { name: 'What changed' });
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['What', 'Was', 'Now']);
  });

  it('shows each row as what, was, now', () => {
    render(<DiffTable label="What changed" rows={rows} />);
    const row = screen.getByRole('row', { name: /Youngest age/ });
    expect(within(row).getByRole('rowheader')).toHaveTextContent('Youngest age');
    const cells = within(row).getAllByRole('cell');
    expect(cells.map((c) => c.textContent)).toEqual(['65', '60']);
  });

  it('uses the column labels it is given', () => {
    render(<DiffTable label="What changed" rows={rows} wasLabel="Was (version 2)" nowLabel="Now (version 3)" />);
    expect(screen.getByRole('columnheader', { name: 'Was (version 2)' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Now (version 3)' })).toBeInTheDocument();
  });

  it('says everything else is the same, in the words it is given', () => {
    render(<DiffTable label="What changed" rows={rows} same="Needs accepted and districts are the same." />);
    const row = screen.getByRole('row', { name: /Everything else/ });
    expect(within(row).getByRole('rowheader')).toHaveTextContent('Everything else');
    expect(within(row).getByRole('cell')).toHaveTextContent('Needs accepted and districts are the same.');
  });

  it('draws no everything-else row without a sentence', () => {
    render(<DiffTable label="What changed" rows={rows} />);
    expect(screen.queryByText('Everything else')).not.toBeInTheDocument();
  });

  it('says so when nothing changed', () => {
    render(<DiffTable label="What changed" rows={[]} same="Nothing is different." />);
    expect(screen.getByRole('row', { name: /Everything else/ })).toHaveTextContent('Nothing is different.');
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<DiffTable label="What changed" rows={rows} same="The rest is the same." />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
