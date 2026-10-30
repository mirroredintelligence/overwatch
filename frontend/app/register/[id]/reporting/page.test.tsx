import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import ReportingPage from './page';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

describe('reporting step page', () => {
  it('shows the step label and heading, and no axe violations', async () => {
    const { container } = render(await ReportingPage({ params: Promise.resolve({ id: 'REG-SAMPLE-1' }) }));
    expect(screen.getByText('Step 4 of 5 · Capacity reporting')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'How will you report capacity?' })).toBeInTheDocument();
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
