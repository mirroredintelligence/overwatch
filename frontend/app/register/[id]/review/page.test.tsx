import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import ReviewPage from './page';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

describe('review page', () => {
  it('shows the step label and heading, and no axe violations', async () => {
    const { container } = render(await ReviewPage({ params: Promise.resolve({ id: 'REG-SAMPLE-1' }) }));
    expect(screen.getByText('Step 5 of 5 · Review')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Check your details' })).toBeInTheDocument();
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
