import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import OrganisationPage from './page';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

// Step 1 of registration: the page shell (W54). The form loads the invitation through the BFF.

describe('organisation step page', () => {
  it('shows the step label and the heading, and no axe violations', async () => {
    const { container } = render(await OrganisationPage({ params: Promise.resolve({ id: 'REG-SAMPLE-1' }) }));
    expect(screen.getByText('Step 1 of 5 · Organisation')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Your organisation' })).toBeInTheDocument();
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
