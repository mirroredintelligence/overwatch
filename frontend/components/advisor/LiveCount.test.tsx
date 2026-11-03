import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { LiveCount } from './LiveCount';

// The side card of the Needs step (Call board, step 2; P1 "Matching so far"): how many services meet the
// criteria so far. The figure is never animated; it is replaced. With no count to give it says so.

describe('LiveCount', () => {
  it('shows the count and says what it counts', () => {
    render(<LiveCount count={3} />);

    expect(screen.getByText('As you fill this in')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('services meet the criteria so far')).toBeInTheDocument();
    expect(screen.getByText('The count follows every choice. Nothing is offered until you press the button.')).toBeInTheDocument();
  });

  it('says it in the singular for one service', () => {
    render(<LiveCount count={1} />);

    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.getByText('service meets the criteria so far')).toBeInTheDocument();
  });

  it('says it in words for none, not only with a zero', () => {
    render(<LiveCount count={0} />);

    expect(screen.getByText('0')).toBeInTheDocument();
    expect(screen.getByText('No service meets the criteria so far')).toBeInTheDocument();
  });

  it('says there is no count yet when it has none, and shows no figure', () => {
    render(<LiveCount count={null} />);

    expect(screen.getByText('No count yet')).toBeInTheDocument();
    expect(screen.getByText('Nothing is offered until you press See options.')).toBeInTheDocument();
    expect(screen.queryByText(/meet the criteria so far/)).toBeNull();
  });

  it('is a polite status, so a changed figure is spoken once and not on every render', () => {
    render(<LiveCount count={3} />);

    expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite');
    expect(screen.getByRole('status')).toHaveTextContent('3 services meet the criteria so far');
  });

  it('has no axe violations in any of its states', async () => {
    const { container } = render(
      <main>
        <LiveCount count={3} />
        <LiveCount count={null} />
      </main>,
    );
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
