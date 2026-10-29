import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { BoardUnavailable } from './BoardUnavailable';

describe('BoardUnavailable', () => {
  it('says no figure can be shown and what to do, as an alert', () => {
    render(<BoardUnavailable />);

    expect(screen.getByRole('alert')).toHaveTextContent('Board unavailable');
    expect(screen.getByRole('alert')).toHaveTextContent(
      'No figures can be shown. Use the whiteboard and phone process.',
    );
    expect(screen.getByText('No patient information on this screen')).toBeInTheDocument();
  });

  it('shows no tile and no number', () => {
    const { container } = render(<BoardUnavailable />);

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(container.querySelector('[data-el="WALL-TILE"]')).toBeNull();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<BoardUnavailable />);

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
