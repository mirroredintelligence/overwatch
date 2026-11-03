import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import LocationPage from './page';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

// Step 2 of registration: the page is the register frame (Reg board) with the form in it.

describe('location step page', () => {
  it('shows the step label and heading in the register frame, and no axe violations', async () => {
    const { container } = render(await LocationPage({ params: Promise.resolve({ id: 'REG-SAMPLE-1' }) }));
    expect(screen.getByText('Step 2 of 5 · Location')).toBeInTheDocument();
    const stage = screen.getByRole('region', { name: 'Current step' });
    expect(within(stage).getByRole('heading', { level: 1, name: 'Where is the service?' })).toBeInTheDocument();
    expect(screen.getAllByRole('main')).toHaveLength(1);
    expect(within(screen.getByRole('banner')).getByRole('link', { name: 'Save and come back later' })).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Your registration' });
    expect(within(nav).getByRole('link', { name: /^Location/ })).toHaveAttribute('aria-current', 'step');
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
