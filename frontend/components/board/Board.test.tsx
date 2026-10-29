import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { BOARD_A, MAIN_ENTRIES } from '@/test/fixtures/board';
import { Board } from './Board';

function tiles(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>('[data-el="WALL-TILE"]'));
}

describe('Board header', () => {
  it('shows the organisation heading, the line, the London time and the date', () => {
    render(<Board board={BOARD_A} />);

    expect(screen.getByRole('heading', { level: 1, name: 'Dorset urgent care capacity' })).toBeInTheDocument();
    expect(screen.getByText('Single point of access')).toBeInTheDocument();
    expect(screen.getByText('14:12')).toBeInTheDocument();
    expect(screen.getByText('Friday 23 October')).toBeInTheDocument();
  });

  it('takes the organisation name from the board it was given, never from a constant', () => {
    render(<Board board={{ ...BOARD_A, organisation: 'Another area' }} />);

    expect(screen.getByRole('heading', { level: 1, name: 'Another area urgent care capacity' })).toBeInTheDocument();
    expect(screen.queryByText(/Dorset/)).toBeNull();
  });

  it('has a plain heading when the back end sends no organisation name', () => {
    render(<Board board={{ ...BOARD_A, organisation: null }} />);

    expect(screen.getByRole('heading', { level: 1, name: 'Urgent care capacity' })).toBeInTheDocument();
  });

  it('marks the time as a machine-readable instant', () => {
    const { container } = render(<Board board={BOARD_A} />);

    expect(container.querySelector('time')).toHaveAttribute('datetime', '2026-10-23T13:12:00Z');
  });
});

describe('Board body', () => {
  it('shows one tile for each service, in the order the back end sent them', () => {
    const { container } = render(<Board board={BOARD_A} />);

    expect(tiles(container).map((t) => t.getAttribute('data-service-id'))).toEqual(
      MAIN_ENTRIES.map((e) => e.serviceId),
    );
  });

  it('does not re-sort: a reversed board stays reversed', () => {
    const reversed = { ...BOARD_A, entries: [...MAIN_ENTRIES].reverse() };
    const { container } = render(<Board board={reversed} />);

    expect(tiles(container).map((t) => t.getAttribute('data-service-id'))).toEqual(
      reversed.entries.map((e) => e.serviceId),
    );
  });

  it('puts the tiles in a list', () => {
    render(<Board board={BOARD_A} />);

    expect(within(screen.getByRole('list', { name: 'Services' })).getAllByRole('listitem')).toHaveLength(9);
  });

  it('renders the legend and the footer text', () => {
    render(<Board board={BOARD_A} />);
    const legend = within(screen.getByRole('list', { name: 'Status key' }));

    expect(legend.getByText('Accepting')).toBeInTheDocument();
    expect(legend.getByText('Limited: phone to confirm')).toBeInTheDocument();
    expect(legend.getByText('Not accepting')).toBeInTheDocument();
    expect(legend.getByText('Over capacity')).toBeInTheDocument();
    expect(legend.getByText('Not updated: treat as unknown, phone')).toBeInTheDocument();
    expect(screen.getByText('No patient information on this screen')).toBeInTheDocument();
  });

  it('measures every age from the back end clock, not from the browser clock', () => {
    const later = { ...BOARD_A, generatedAt: '2026-10-23T13:22:00Z' };
    render(<Board board={later} />);

    expect(screen.getByText('Updated 19 min ago · next due 14:30')).toBeInTheDocument();
    expect(screen.getByText('14:22')).toBeInTheDocument();
  });

  it('says so, and tells people what to do, when the board lists no services', () => {
    render(<Board board={{ ...BOARD_A, entries: [] }} />);

    expect(screen.getByRole('status')).toHaveTextContent(
      'No services are listed. Use the whiteboard and phone process.',
    );
  });
});

describe('Board privacy and accessibility', () => {
  it('shows no back-end id except data-service-id, and nothing shaped like a postcode or an NHS number', () => {
    const { container } = render(<Board board={BOARD_A} />);
    const html = container.innerHTML.replace(/data-service-id="[^"]*"/g, '');

    expect(tiles(container)).toHaveLength(9);
    for (const e of MAIN_ENTRIES) expect(html).not.toContain(e.serviceId);
    expect(container.textContent).not.toMatch(/\b[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}\b/);
    expect(container.textContent).not.toMatch(/\b\d{3} ?\d{3} ?\d{4}\b/);
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<Board board={BOARD_A} />);

    expect(tiles(container)).toHaveLength(9);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
