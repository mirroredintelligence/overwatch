'use client';

import { useState, type ReactNode } from 'react';
import { Disclose } from '@/components/admin/Disclose';
import styles from './ChartTable.module.css';

// The table every chart carries: the same rows as the marks, behind a "Show as a table" disclosure.

export type ChartTableData = {
  caption?: string;
  columns: readonly string[];
  rows: readonly (readonly (string | number)[])[];
};

export function ChartTable({ table }: { table: ChartTableData }) {
  const [open, setOpen] = useState(false);
  return (
    <Disclose open={open} onToggle={() => setOpen((v) => !v)} title="Show as a table">
      <table className={styles.table}>
        {table.caption ? <caption className={styles.caption}>{table.caption}</caption> : null}
        <thead>
          <tr>
            {table.columns.map((c) => (
              <th key={c} scope="col">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j): ReactNode =>
                j === 0 ? (
                  <th key={j} scope="row">
                    {cell}
                  </th>
                ) : (
                  <td key={j}>{cell}</td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </Disclose>
  );
}
