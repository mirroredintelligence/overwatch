import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

// The advisor v2 layout (DEC-1376, WS-SHL): the route group wraps its pages in the workspace shell, not in the staff shell.

vi.mock('@/app/WorkspaceShell', async () => {
  const React = await import('react');
  return {
    WorkspaceShell: ({ children }: { children: ReactNode }) =>
      React.createElement('section', { 'data-testid': 'workspace-shell' }, children),
  };
});

vi.mock('@/app/StaffShell', async () => {
  const React = await import('react');
  return {
    StaffShell: ({ children }: { children: ReactNode }) =>
      React.createElement('section', { 'data-testid': 'staff-shell' }, children),
  };
});

import Layout from './layout';

describe('advisor v2 layout', () => {
  it('WS-SHL-T06 renders WorkspaceShell around its children and no longer renders StaffShell', () => {
    render(
      <Layout>
        <p>Child page</p>
      </Layout>,
    );

    const shell = screen.getByTestId('workspace-shell');
    expect(shell).toContainElement(screen.getByText('Child page'));
    expect(screen.queryByTestId('staff-shell')).toBeNull();
  });
});
