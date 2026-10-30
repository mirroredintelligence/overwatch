import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import StatusRoute from './page';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

describe('status page', () => {
  it('has no axe violations on its first render', async () => {
    const { container } = render(await StatusRoute({ params: Promise.resolve({ id: 'REG-SAMPLE-1' }) }));
    expect(container.querySelector('main')).not.toBeNull();
    expect(screen.getByRole('main')).toBeInTheDocument();
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
