import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { StickyAction } from './StickyAction';

describe('StickyAction', () => {
  it('shows one primary button that calls its handler', async () => {
    const onClick = vi.fn();
    render(<StickyAction primary={{ label: 'Start', onClick }} />);
    await userEvent.click(screen.getByRole('button', { name: 'Start' }));
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(screen.getAllByRole('button')).toHaveLength(1);
  });

  it('shows an optional text button', async () => {
    const onClick = vi.fn();
    render(<StickyAction primary={{ label: 'Continue' }} link={{ label: 'Back', onClick }} />);
    await userEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('renders a link when given an href', () => {
    render(<StickyAction primary={{ label: 'Open', href: '/setup' }} link={{ label: 'Help', href: '/help' }} />);
    expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute('href', '/setup');
    expect(screen.getByRole('link', { name: 'Help' })).toHaveAttribute('href', '/help');
  });

  it('disables the primary and does not call it', async () => {
    const onClick = vi.fn();
    render(<StickyAction primary={{ label: 'Send', onClick, disabled: true }} />);
    const button = screen.getByRole('button', { name: 'Send' });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('marks the primary busy without changing its name', () => {
    render(<StickyAction primary={{ label: 'Send', busy: true }} />);
    expect(screen.getByRole('button', { name: 'Send' })).toHaveAttribute('aria-busy', 'true');
  });

  it('has no axe violations', async () => {
    const { container } = render(<StickyAction primary={{ label: 'Continue' }} link={{ label: 'Back', onClick: () => {} }} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
