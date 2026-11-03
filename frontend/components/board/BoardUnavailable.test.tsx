import { render, screen, within } from '@testing-library/react';
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

  it('is one alert with the heading inside it and a "!" mark that is not read out, like the offline banner', () => {
    render(<BoardUnavailable />);
    const alert = screen.getByRole('alert');

    expect(within(alert).getByRole('heading', { level: 1, name: 'Board unavailable' })).toBeInTheDocument();
    expect(within(alert).getByText('!')).toHaveAttribute('aria-hidden', 'true');
  });

  it('offers no action: nothing here can be pressed that would suggest a figure is on its way', () => {
    render(<BoardUnavailable />);

    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<BoardUnavailable />);

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
