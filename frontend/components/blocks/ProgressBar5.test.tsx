import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { ProgressBar5 } from './ProgressBar5';

describe('ProgressBar5', () => {
  it('has the accessible name "4 of 5 parts done" and five segments, four filled', () => {
    const { container } = render(<ProgressBar5 done={4} />);
    expect(screen.getByRole('img', { name: '4 of 5 parts done' })).toBeInTheDocument();
    expect(container.querySelectorAll('[data-seg]')).toHaveLength(5);
    expect(container.querySelectorAll('[data-seg="filled"]')).toHaveLength(4);
  });

  it('names 2 of 5', () => {
    render(<ProgressBar5 done={2} />);
    expect(screen.getByRole('img', { name: '2 of 5 parts done' })).toBeInTheDocument();
  });

  it('clamps out-of-range and fractional values', () => {
    const { container, rerender } = render(<ProgressBar5 done={9} />);
    expect(screen.getByRole('img', { name: '5 of 5 parts done' })).toBeInTheDocument();
    rerender(<ProgressBar5 done={-1} />);
    expect(screen.getByRole('img', { name: '0 of 5 parts done' })).toBeInTheDocument();
    rerender(<ProgressBar5 done={2.7} />);
    expect(container.querySelectorAll('[data-seg="filled"]')).toHaveLength(2);
  });

  it('has no axe violations', async () => {
    const { container } = render(<ProgressBar5 done={3} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
