import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { byEl } from '@/test/el';
import { networkBffHandlers } from '@/test/msw/handlers/networkBff';
import { server } from '@/test/msw/server';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

import NetworkMapPage from './page';

beforeEach(() => server.use(...networkBffHandlers));

describe('network map page (WB11)', () => {
  it('marks the Options step current, and shows the network’s map with the toggles', async () => {
    render(await NetworkMapPage({ params: Promise.resolve({ ref: '4821' }) }));
    expect(document.querySelector('[data-step="options"]')).toHaveAttribute('aria-current', 'step');
    expect(await screen.findByRole('button', { name: 'Virtual ward frailty' })).toBeInTheDocument();
    expect(byEl('ADV-MAP-TOGGLE-MAP')).toHaveAttribute('aria-pressed', 'true');
    expect(byEl('ADV-MAP-TOGGLE-LIST')).toHaveAttribute('aria-pressed', 'false');
  });
});
