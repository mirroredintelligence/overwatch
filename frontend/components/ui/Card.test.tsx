import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { Card } from './Card';

describe('Card', () => {
  it('is a section named by its heading, level 2 by default', () => {
    render(<Card heading="Options">Body</Card>);
    expect(screen.getByRole('heading', { level: 2, name: 'Options' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Options' })).toHaveTextContent('Body');
  });

  it('honours the heading level', () => {
    render(<Card heading="Options" headingLevel={3}>Body</Card>);
    expect(screen.getByRole('heading', { level: 3, name: 'Options' })).toBeInTheDocument();
  });

  it('works without a heading', () => {
    const { container } = render(<Card>Body</Card>);
    expect(container.querySelector('section')).toHaveTextContent('Body');
    expect(screen.queryByRole('heading')).toBeNull();
  });

  it('renders data-el and has no axe violations', async () => {
    const { container } = render(
      <main>
        <Card heading="Options" dataEl="CARD-1">Body</Card>
      </main>,
    );
    expect(container.querySelector('[data-el="CARD-1"]')).not.toBeNull();
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
