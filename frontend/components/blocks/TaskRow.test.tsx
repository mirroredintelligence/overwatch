import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { TaskRow } from './TaskRow';

describe('TaskRow', () => {
  it('shows the status word with its shape, the title, one line and one action', () => {
    const { container } = render(
      <TaskRow status="waiting" statusWord="Waiting for you" title="A request" line="Approve or refuse." action={{ label: 'Review request', onClick: () => {} }} urgent />,
    );
    expect(screen.getByText('Waiting for you')).toBeInTheDocument();
    expect(container.querySelector('[data-variant="waiting"] svg')).toHaveAttribute('aria-hidden', 'true');
    expect(screen.getByText('A request')).toBeInTheDocument();
    expect(screen.getByText('Approve or refuse.')).toBeInTheDocument();
    expect(screen.getAllByRole('button')).toHaveLength(1);
    expect(container.firstElementChild).toHaveAttribute('data-urgent', 'true');
  });

  it('calls onClick for a button action', () => {
    const onClick = vi.fn();
    render(<TaskRow status="todo" statusWord="To do" title="t" line="l" action={{ label: 'Add phone', onClick }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Add phone' }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('renders a link action when it has an href', () => {
    render(<TaskRow status="todo" statusWord="To do" title="t" line="l" action={{ label: 'Open version', href: '/admin/versions/3' }} />);
    expect(screen.getByRole('link', { name: 'Open version' })).toHaveAttribute('href', '/admin/versions/3');
  });

  it('marks the action as primary only when asked', () => {
    render(<TaskRow status="waiting" statusWord="w" title="t" line="l" action={{ label: 'Go', onClick: () => {}, primary: true }} />);
    expect(screen.getByRole('button', { name: 'Go' })).toHaveAttribute('data-primary', 'true');
  });

  it('has no axe violations', async () => {
    const { container } = render(<TaskRow status="todo" statusWord="To do" title="t" line="l" action={{ label: 'Go', onClick: () => {} }} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
