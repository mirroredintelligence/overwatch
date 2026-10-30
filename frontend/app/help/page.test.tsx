import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import HelpPage from './page';

afterEach(() => vi.unstubAllEnvs());

describe('Help page', () => {
  it('offers the safety concern and the problem report, and says help is one tap away', () => {
    render(<HelpPage />);
    expect(screen.getByRole('heading', { level: 1, name: 'Help' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Report a safety concern' })).toHaveAttribute('href', '/help/safety');
    expect(screen.getByRole('link', { name: 'Something is wrong with the tool' })).toHaveAttribute('href', '/help/problem');
    expect(screen.getByText('Help is one tap away on every screen.')).toBeInTheDocument();
  });

  it('always links to "Share my session with support", whatever the old flag says (W56)', () => {
    vi.stubEnv('NEXT_PUBLIC_SUPPORT_SHARING', 'off');
    render(<HelpPage />);
    expect(screen.getByRole('link', { name: 'Share my session with support' })).toHaveAttribute('href', '/help/share');
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<HelpPage />);
    expect(screen.getByRole('link', { name: 'Report a safety concern' })).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
