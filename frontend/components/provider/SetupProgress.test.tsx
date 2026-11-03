import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { SetupProgress } from './SetupProgress';

describe('SetupProgress', () => {
  it('is named by the step it is on', () => {
    render(<SetupProgress step={2} />);
    expect(screen.getByLabelText('Step 2 of 5')).toBeInTheDocument();
  });

  it('draws five segments and fills the ones up to the current step', () => {
    render(<SetupProgress step={3} />);
    const segments = screen.getByLabelText('Step 3 of 5').querySelectorAll('[data-segment]');
    expect(segments).toHaveLength(5);
    expect([...segments].map((s) => s.getAttribute('data-filled'))).toEqual(['true', 'true', 'true', 'false', 'false']);
  });

  it('clamps the step into 1..5', () => {
    const { rerender } = render(<SetupProgress step={0} />);
    expect(screen.getByLabelText('Step 1 of 5')).toBeInTheDocument();
    rerender(<SetupProgress step={9} />);
    expect(screen.getByLabelText('Step 5 of 5')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(<SetupProgress step={4} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
