import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { Legend } from './Legend';

describe('Legend', () => {
  it('lists the six meanings in the artboard wording, in order', () => {
    render(<Legend />);
    const items = within(screen.getByRole('list', { name: 'Status key' })).getAllByRole('listitem');

    expect(items.map((li) => li.textContent)).toEqual([
      'Accepting',
      'Limited: phone to confirm',
      'Not accepting',
      'Over capacity',
      'Not updated: treat as unknown, phone',
      'Out of hours: closed, not counted',
    ]);
  });

  it('draws each meaning with its own shape as well as colour: circle, half circle, square, triangle, dashed ring, crescent', () => {
    const { container } = render(<Legend />);
    const shapes = Array.from(container.querySelectorAll('[data-shape]')).map((el) => el.getAttribute('data-shape'));

    expect(shapes).toEqual(['circle', 'half-circle', 'square', 'triangle', 'dashed-ring', 'crescent']);
  });

  it('is the same chip the tiles use, so the key and the tile never disagree', () => {
    const { container } = render(<Legend />);
    const statuses = Array.from(container.querySelectorAll('[data-status]')).map((el) => el.getAttribute('data-status'));

    expect(statuses).toEqual(['accepting', 'limited', 'not-accepting', 'over-capacity', 'not-updated', 'out-of-hours']);
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<Legend />);

    expect(container.querySelectorAll('li')).toHaveLength(6);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
