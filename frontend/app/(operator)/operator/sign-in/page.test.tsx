import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';

import SignInPage from './page';

// The platform console's sign-in on board O1: a split page. The dark half holds the brand, the console name, the
// headline and the footnote; the light half holds the sign-in card. The page's own tests (operator/pages.test.tsx)
// keep the console name as the only level-1 heading.

describe('/operator/sign-in board O1', () => {
  it('shows the brand half with the console name, the headline and the footnote', async () => {
    render(await SignInPage({ searchParams: Promise.resolve({}) }));
    const brand = screen.getByRole('region', { name: 'Overwatch' });
    expect(within(brand).getByRole('heading', { level: 1, name: 'Platform console' })).toBeInTheDocument();
    expect(within(brand).getByText(/Set up organisations and keep them running/)).toBeInTheDocument();
    expect(within(brand).getByText(/recorded in a chain that cannot be changed afterwards/)).toBeInTheDocument();
    expect(within(brand).getByText('Staff of an organisation sign in at their own address, not here.')).toBeInTheDocument();
  });

  it('puts the sign-in card with its help line in the light half', async () => {
    render(await SignInPage({ searchParams: Promise.resolve({}) }));
    const card = screen.getByRole('region', { name: 'Sign in' });
    expect(within(card).getByRole('heading', { level: 2, name: 'Sign in' })).toBeInTheDocument();
    expect(within(card).getByText('This is for the people who run the platform. Use your platform account.')).toBeInTheDocument();
    expect(within(card).getByText('There is no new password.')).toBeInTheDocument();
    expect(within(card).getByText('Having trouble? Ask the person who runs the platform to check your access.')).toBeInTheDocument();
    expect(within(card).getByRole('button', { name: 'Sign in with your platform account' })).toBeInTheDocument();
  });

  it('shows the failure banner inside the light half, above the card, when the sign-in failed', async () => {
    render(await SignInPage({ searchParams: Promise.resolve({ error: 'failed' }) }));
    const card = screen.getByRole('region', { name: 'Sign in' });
    expect(within(card).getByRole('alert')).toHaveTextContent('We could not sign you in. Try again.');
    expect(within(card).getByRole('button', { name: 'Sign in with your platform account' })).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(await SignInPage({ searchParams: Promise.resolve({ error: 'no-access' }) }));
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
