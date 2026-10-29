import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import ForbiddenPage from './page';

describe('forbidden page', () => {
  it('says the person has no access to this page', () => {
    render(<ForbiddenPage />);
    expect(screen.getByRole('heading', { level: 1, name: 'You do not have access to this page.' })).toBeInTheDocument();
    expect(screen.getByText('Ask your shift lead to check your access.')).toBeInTheDocument();
  });

  it('says nothing about the page, the role or the organisation', () => {
    const { container } = render(<ForbiddenPage />);
    expect(container.textContent).not.toMatch(/lead only|advisor|clinical|trust|tenant|organisation/i);
  });

  it('has no axe violations and one main landmark', async () => {
    const { container } = render(<ForbiddenPage />);
    expect(screen.getAllByRole('main')).toHaveLength(1);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
