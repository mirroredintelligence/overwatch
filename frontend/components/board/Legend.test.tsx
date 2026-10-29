import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { Legend } from './Legend';

describe('Legend', () => {
  it('lists the five meanings in the artboard wording, in order', () => {
    render(<Legend />);
    const items = within(screen.getByRole('list', { name: 'Status key' })).getAllByRole('listitem');

    expect(items.map((li) => li.textContent)).toEqual([
      'Accepting',
      'Limited: phone to confirm',
      'Not accepting',
      'Over capacity',
      'Not updated: treat as unknown, phone',
    ]);
  });

  it('gives each meaning a shape as well as colour', () => {
    const { container } = render(<Legend />);

    expect(container.querySelectorAll('[data-shape]')).toHaveLength(5);
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<Legend />);

    expect(container.querySelectorAll('li')).toHaveLength(5);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
