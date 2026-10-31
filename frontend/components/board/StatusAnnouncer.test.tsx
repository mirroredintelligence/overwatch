import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BOARD_A, entry } from '@/test/fixtures/board';
import type { Board } from '@/lib/board/types';
import { StatusAnnouncer } from './StatusAnnouncer';

// KI-56 (design-system 5.4 item 4): a polite live region for status changes on the wall, so a person who
// cannot see the tiles hears that a service changed. It says each change once, as a sentence, and nothing
// on the first board or when nothing changed; it never says a figure of a board shown as last known.

function boardWith(over: Record<string, Partial<Parameters<typeof entry>[0]>>): Board {
  return { ...BOARD_A, entries: BOARD_A.entries.map((e) => (over[e.serviceId] ? { ...e, ...over[e.serviceId] } : e)) };
}

const region = () => screen.getByRole('status');

describe('StatusAnnouncer', () => {
  it('is a polite, atomic live region, empty on the first board', () => {
    render(<StatusAnnouncer board={BOARD_A} />);
    expect(region()).toHaveAttribute('aria-live', 'polite');
    expect(region()).toHaveAttribute('aria-atomic', 'true');
    expect(region()).toHaveTextContent('');
  });

  it('says a service whose status changed, by name', () => {
    const { rerender } = render(<StatusAnnouncer board={BOARD_A} />);
    rerender(<StatusAnnouncer board={boardWith({ 'svc-ucr-west': { status: 'limited' } })} />);
    expect(region()).toHaveTextContent('UCR West is now Limited.');
  });

  it('says several changes in one sentence each, in the order of the board', () => {
    const { rerender } = render(<StatusAnnouncer board={BOARD_A} />);
    rerender(<StatusAnnouncer board={boardWith({ 'svc-ucr-west': { status: 'not-accepting' }, 'svc-virtual-ward': { status: 'accepting' } })} />);
    expect(region().textContent).toBe('UCR West is now Not accepting. Virtual ward · frailty is now Accepting.');
  });

  it('says nothing when only a figure changed, or when nothing changed', () => {
    const { rerender } = render(<StatusAnnouncer board={BOARD_A} />);
    rerender(<StatusAnnouncer board={boardWith({ 'svc-ucr-west': { effectiveAvailable: 2 } })} />);
    expect(region()).toHaveTextContent('');
    rerender(<StatusAnnouncer board={BOARD_A} />);
    expect(region()).toHaveTextContent('');
  });

  it('does not announce a service that appeared on the board', () => {
    const { rerender } = render(<StatusAnnouncer board={BOARD_A} />);
    rerender(<StatusAnnouncer board={{ ...BOARD_A, entries: [...BOARD_A.entries, entry({ serviceId: 'svc-new', name: 'New service', status: 'limited' })] }} />);
    expect(region()).toHaveTextContent('');
  });

  it('says nothing while the board is shown as last known', () => {
    const { rerender } = render(<StatusAnnouncer board={BOARD_A} />);
    rerender(<StatusAnnouncer board={boardWith({ 'svc-ucr-west': { status: 'limited' } })} lastKnown />);
    expect(region()).toHaveTextContent('');
  });
});
