import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { FigureStrip } from './FigureStrip';

// The last five figures of a service (LDR-09). It draws nothing when there are no figures.

const FIGURES = [
  { value: 4, time: '13:04' },
  { value: 0, time: '13:12' },
  { value: 5, time: '13:21' },
  { value: 1, time: '13:33' },
  { value: 4, time: '13:52' },
  { value: 2, time: '14:05' },
];

describe('FigureStrip', () => {
  it('renders nothing when there are no figures', () => {
    const { container } = render(<FigureStrip figures={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the last five figures with their times, oldest first', () => {
    render(<FigureStrip figures={FIGURES} />);
    expect(screen.getByText('The last reports')).toBeInTheDocument();
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(5);
    expect(items[0]).toHaveTextContent('0');
    expect(items[0]).toHaveTextContent('13:12');
    expect(items[4]).toHaveTextContent('2');
    expect(items[4]).toHaveTextContent('14:05');
  });

  it('shows the note beside the figures when there is one', () => {
    render(<FigureStrip figures={FIGURES} note="Usual range 2 to 5." />);
    expect(screen.getByText('Usual range 2 to 5.')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(<FigureStrip figures={FIGURES} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
