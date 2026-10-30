import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import MyServicesPage from './page';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

describe('my services page', () => {
  it('shows the heading and no axe violations', async () => {
    const { container } = render(await MyServicesPage());
    expect(screen.getByRole('heading', { level: 1, name: 'My services' })).toBeInTheDocument();
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
