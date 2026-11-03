import type { ReactNode } from 'react';
import styles from './DataTable.module.css';

// One table for every list of rows (planning, network, administration and console). The caption names the table for a
// screen reader and the scroll region is focusable, so a keyboard user can scroll a long table.

export interface DataTableColumn<T> {
  key: string;
  header: string;
  cell: (row: T) => ReactNode;
  align?: 'start' | 'end';
}

export interface DataTableProps<T> {
  caption: string;
  columns: readonly DataTableColumn<T>[];
  rows: readonly T[];
  getRowKey: (row: T) => string;
  // Shown in one row across the columns when there are no rows: the empty state says why, and what to do.
  empty?: ReactNode;
}

export function DataTable<T>({ caption, columns, rows, getRowKey, empty }: DataTableProps<T>) {
  return (
    <div className={styles.region} role="region" aria-label={caption} tabIndex={0}>
      <table className={styles.table}>
        <caption className={styles.caption}>{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} scope="col" data-align={column.align ?? 'start'}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && empty !== undefined ? (
            <tr>
              <td className={styles.empty} colSpan={columns.length}>
                {empty}
              </td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr key={getRowKey(row)}>
                {columns.map((column) => (
                  <td key={column.key} data-align={column.align ?? 'start'}>
                    {column.cell(row)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
