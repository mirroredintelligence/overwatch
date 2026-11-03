import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import HelpPage from './page';

// The three ways in (safety concern, problem, share) are the hub column of app/help/layout.tsx; this page is
// what sits beside it: the heading, the one line about who it is for, and the "Need a hand?" ways.

describe('Help page', () => {
  it('says help works signed in or out and asks for no patient details, and that help is one tap away', () => {
    render(<HelpPage />);
    expect(screen.getByRole('heading', { level: 1, name: 'Help' })).toBeInTheDocument();
    expect(screen.getByText('Works signed in or out. Nothing here asks for patient details.')).toBeInTheDocument();
    expect(screen.getByText('Help is one tap away on every screen.')).toBeInTheDocument();
  });

  it('offers the four ways to get help of the training artboard', () => {
    render(<HelpPage />);
    expect(screen.getByRole('heading', { level: 2, name: 'Need a hand?' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Read the one-page guide' })).toBeInTheDocument();
    expect(screen.getByText('Ask your champion')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Report a problem' })).toHaveAttribute('href', '/help/problem');
  });

  it('marks itself as the hub page, so a phone shows the hub first', () => {
    render(<HelpPage />);
    expect(screen.getByRole('main')).toHaveAttribute('data-help-hub');
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<HelpPage />);
    expect(screen.getByRole('heading', { level: 1, name: 'Help' })).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
