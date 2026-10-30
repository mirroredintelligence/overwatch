import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import ServicePage from './page';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

describe('service step page', () => {
  it('shows the step label and heading, and no axe violations', async () => {
    const { container } = render(await ServicePage({ params: Promise.resolve({ id: 'REG-SAMPLE-1' }) }));
    expect(screen.getByText('Step 3 of 5 · Service')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Describe the service' })).toBeInTheDocument();
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
