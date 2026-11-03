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

  it('offers a way home and a way to sign in as someone else, both as links', () => {
    render(<ForbiddenPage />);
    const home = screen.getByRole('link', { name: 'Back to my home' });
    expect(home).toHaveAttribute('href', '/');
    const other = screen.getByRole('link', { name: 'Sign in as someone else' });
    expect(other).toHaveAttribute('href', '/sign-in');
  });

  it('draws the lock as decoration, so the words carry the meaning', () => {
    const { container } = render(<ForbiddenPage />);
    const icon = container.querySelector('svg');
    expect(icon).not.toBeNull();
    expect(icon?.parentElement).toHaveAttribute('aria-hidden', 'true');
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
