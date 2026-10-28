import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { Banner } from './Banner';

describe('Banner', () => {
  it('offline and warning use role alert', () => {
    const { rerender } = render(<Banner tone="offline" title="You are offline">Body</Banner>);
    expect(screen.getByRole('alert')).toHaveTextContent('You are offline');
    rerender(<Banner tone="warning" title="Careful">Body</Banner>);
    expect(screen.getByRole('alert')).toHaveTextContent('Careful');
  });

  it('info uses role status', () => {
    render(<Banner tone="info" title="Note">Body text</Banner>);
    expect(screen.getByRole('status')).toHaveTextContent('Body text');
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('renders data-el and has no axe violations', async () => {
    const { container } = render(
      <main>
        <Banner tone="info" title="Note" dataEl="BAN-1">Body</Banner>
        <Banner tone="offline" title="Offline">Body</Banner>
      </main>,
    );
    expect(container.querySelector('[data-el="BAN-1"]')).not.toBeNull();
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
