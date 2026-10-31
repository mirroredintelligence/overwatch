import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { BOARD_A, GENERATED_AT } from '@/test/fixtures/board';
import { Board } from './Board';
import { LiveBoard } from './LiveBoard';

// TEN-069 (KI-545, KI-559): the wall board says which board it is, in words, on the screen itself (a
// wall has no address bar), and its heading is the tenant's own word for its system when it has one.

vi.mock('next/navigation', () => ({ useRouter: () => ({ replace: vi.fn() }) }));

describe('the wall board’s scope header', () => {
  it('says "Showing: Our organisation" in a landmark, with no switch', () => {
    render(<Board board={BOARD_A} />);
    expect(screen.getByRole('region', { name: 'Which board you are viewing' })).toHaveTextContent('Showing: Our organisation');
    expect(screen.queryByRole('navigation')).toBeNull();
  });

  it('keeps saying it when the board is last known', () => {
    render(<Board board={BOARD_A} lastKnown={{ mode: 'last-known', reason: 'offline', since: GENERATED_AT, asOf: GENERATED_AT, now: GENERATED_AT, ageMs: 0 }} />);
    expect(screen.getByText('Showing: Our organisation')).toBeInTheDocument();
  });
});

describe('the heading', () => {
  it('is the tenant’s own heading when the page gives one', () => {
    render(<Board board={BOARD_A} heading="Dorset Capacity A" />);
    expect(screen.getByRole('heading', { level: 1, name: 'Dorset Capacity A' })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/urgent care capacity/i);
  });

  it('is the old words when it gives none (a tenant with no wording)', () => {
    render(<Board board={BOARD_A} heading={null} />);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('urgent care capacity');
  });

  it('is passed on by the live board', () => {
    render(<LiveBoard initialBoard={BOARD_A} serverTime={Date.parse(GENERATED_AT)} heading="Dorset Capacity A" createEventSource={() => null} />);
    expect(screen.getByRole('heading', { level: 1, name: 'Dorset Capacity A' })).toBeInTheDocument();
  });
});
