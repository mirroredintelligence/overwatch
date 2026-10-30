import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

import CaseNeedsPage from './page';

describe('case needs page (W11)', () => {
  it('marks the Needs step current and renders the needs form', async () => {
    render(await CaseNeedsPage({ params: Promise.resolve({ ref: '4821' }) }));

    expect(document.querySelector('[data-step="needs"]')).toHaveAttribute(
      'aria-current',
      'step',
    );
    expect(screen.getByText('Loading the case.')).toBeInTheDocument();
  });
});
