import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { networkBffHandlers } from '@/test/msw/handlers/networkBff';
import { server } from '@/test/msw/server';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

import NetworkOptionsPage from './page';

beforeEach(() => server.use(...networkBffHandlers));

describe('network options page (WB11)', () => {
  it('marks the Options step current, and shows the network’s options for the case', async () => {
    render(await NetworkOptionsPage({ params: Promise.resolve({ ref: '4821' }) }));
    expect(document.querySelector('[data-step="options"]')).toHaveAttribute('aria-current', 'step');
    expect(await screen.findByText('2 services in Sample Network meet this patient’s criteria')).toBeInTheDocument();
  });

  it('names the case by its reference only: no postcode, need or age is in the page', async () => {
    const { container } = render(await NetworkOptionsPage({ params: Promise.resolve({ ref: '4821' }) }));
    await screen.findByText('2 services in Sample Network meet this patient’s criteria');
    expect(container.innerHTML).not.toMatch(/DT4|postcode=|age=/i);
  });
});
