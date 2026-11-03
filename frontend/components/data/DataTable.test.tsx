import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { DataTable, type DataTableColumn } from './DataTable';

// One table for every list of rows: a sticky header, a scroll region that keeps its own scrolling
// (overscroll-behavior: contain) and a height bounded by the viewport. A screen reader gets the caption and the headers.

type Row = { id: string; service: string; organisation: string; line: string; reported: string };

const COLUMNS: readonly DataTableColumn<Row>[] = [
  { key: 'service', header: 'Service', cell: (r) => <b>{r.service}</b> },
  { key: 'organisation', header: 'Organisation', cell: (r) => r.organisation },
  { key: 'line', header: 'Service line', cell: (r) => r.line },
  { key: 'reported', header: 'Last reported', cell: (r) => r.reported },
];

const ROWS: readonly Row[] = [
  { id: '1', service: 'UCR West', organisation: 'Community Trust', line: '01632 960001', reported: '23 Oct 14:08' },
  { id: '2', service: 'Respite beds', organisation: 'Care Home Group', line: 'Phone to confirm', reported: 'No number shared' },
];

function table(overrides: Partial<Parameters<typeof DataTable<Row>>[0]> = {}) {
  return (
    <DataTable<Row>
      caption="Network phones"
      columns={COLUMNS}
      rows={ROWS}
      getRowKey={(r) => r.id}
      {...overrides}
    />
  );
}

describe('DataTable', () => {
  it('names the table by its caption and gives every column a header', () => {
    render(table());
    const grid = screen.getByRole('table', { name: 'Network phones' });
    const headers = within(grid).getAllByRole('columnheader');
    expect(headers.map((h) => h.textContent)).toEqual(['Service', 'Organisation', 'Service line', 'Last reported']);
    headers.forEach((h) => expect(h).toHaveAttribute('scope', 'col'));
  });

  it('renders one body row per item, with the cell content', () => {
    render(table());
    const rows = within(screen.getByRole('table')).getAllByRole('row');
    // one header row plus two body rows
    expect(rows).toHaveLength(3);
    expect(within(rows[1]).getByText('UCR West')).toBeInTheDocument();
    expect(within(rows[1]).getByText('01632 960001')).toBeInTheDocument();
    expect(within(rows[2]).getByText('Phone to confirm')).toBeInTheDocument();
  });

  it('keeps the table in a focusable, labelled scroll region', () => {
    render(table());
    const region = screen.getByRole('region', { name: 'Network phones' });
    expect(region).toHaveAttribute('tabindex', '0');
    expect(region).toContainElement(screen.getByRole('table'));
  });

  it('shows the empty message in a row that spans the columns when there are no rows', () => {
    render(table({ rows: [], empty: 'No services shared yet. Phone your network lead.' }));
    expect(screen.getByText('No services shared yet. Phone your network lead.')).toBeInTheDocument();
    expect(screen.getByText('No services shared yet. Phone your network lead.').closest('td')).toHaveAttribute('colspan', '4');
  });

  it('right-aligns a column that asks for end alignment', () => {
    const cols: DataTableColumn<Row>[] = [{ key: 'reported', header: 'Last reported', cell: (r) => r.reported, align: 'end' }];
    render(table({ columns: cols }));
    expect(screen.getByRole('columnheader', { name: 'Last reported' })).toHaveAttribute('data-align', 'end');
  });

  it('has no axe violations', async () => {
    const { container } = render(table());
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('keeps a sticky header, contained overscroll and a viewport-aware height in its stylesheet', () => {
    const css = readFileSync(resolve(__dirname, 'DataTable.module.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
    expect(css).toMatch(/overscroll-behavior:\s*contain/);
    expect(css).toMatch(/position:\s*sticky/);
    expect(css).toMatch(/top:\s*0/);
    expect(css).toMatch(/max-height:\s*clamp\([^)]*(dvh|vh)/);
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(css).toMatch(/var\(--c-/);
  });
});
