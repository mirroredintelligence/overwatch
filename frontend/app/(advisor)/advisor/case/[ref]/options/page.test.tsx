import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

import OptionsPage from './page';

describe('options page (W13)', () => {
  it('marks the Options step current, and shows the options list for the case', async () => {
    render(await OptionsPage({ params: Promise.resolve({ ref: '4821' }) }));

    expect(document.querySelector('[data-step="options"]')).toHaveAttribute('aria-current', 'step');
    expect(document.querySelector('[data-step="needs"]')).toHaveAttribute('data-state', 'done');
    expect(screen.getByText('Loading the options.')).toBeInTheDocument();
  });
});
