import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

import FinishPage from './page';

describe('finish page (W15)', () => {
  it('marks the Outcome step current and shows the finish screen', async () => {
    render(await FinishPage({ params: Promise.resolve({ ref: '4821' }), searchParams: Promise.resolve({}) }));

    expect(document.querySelector('[data-step="outcome"]')).toHaveAttribute('aria-current', 'step');
    expect(screen.getByRole('heading', { name: 'Record outcome' })).toBeInTheDocument();
  });

  it('passes a known outcome from the address to the form, and ignores an unknown one', async () => {
    render(await FinishPage({ params: Promise.resolve({ ref: '4821' }), searchParams: Promise.resolve({ outcome: 'no-service-fits' }) }));
    expect(await screen.findByText('No service fits')).toBeInTheDocument();
  });
});
