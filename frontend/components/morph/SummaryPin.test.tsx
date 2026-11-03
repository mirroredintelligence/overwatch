import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { SummaryPin, type SummaryItem } from './SummaryPin';

// The left card of a guided flow (boards/lead/AddService.dc.html): what has been entered so far, read only, each
// part with a Change link. It grows from width 0 (the column is the page's; the card fades in), and on a phone
// it is a one-line pill that opens a sheet with the same list.

const ITEMS: SummaryItem[] = [
  { key: 'service', label: 'The service', value: 'Hospital at home · East', detail: 'Counts beds free · 12 established' },
  { key: 'reports', label: 'Who reports', value: 'Duty manager, by text', detail: 'Phone ending 0456' },
];

describe('SummaryPin card', () => {
  it('is a labelled region with a heading and every item as a read-only list', () => {
    render(<SummaryPin items={ITEMS} onChange={() => undefined} />);
    const region = screen.getByRole('region', { name: 'What you have entered' });
    expect(within(region).getByText('So far')).toBeInTheDocument();
    const rows = within(region).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('The service');
    expect(rows[0]).toHaveTextContent('Hospital at home · East');
    expect(rows[0]).toHaveTextContent('Counts beds free · 12 established');
    expect(region.querySelector('input, textarea, select')).toBeNull();
  });

  it('gives each item a Change button that names what it changes, and calls onChange with the key', () => {
    const onChange = vi.fn();
    render(<SummaryPin items={ITEMS} onChange={onChange} />);
    fireEvent.click(screen.getByRole('button', { name: 'Change who reports' }));
    expect(onChange).toHaveBeenCalledWith('reports');
  });

  it('draws Change as a link when the item has an href', () => {
    render(<SummaryPin items={[{ ...ITEMS[0], href: '?step=0' }]} />);
    expect(screen.getByRole('link', { name: 'Change the service' })).toHaveAttribute('href', '?step=0');
  });

  it('shows no Change control for an item that cannot be changed', () => {
    render(<SummaryPin items={ITEMS} />);
    expect(screen.queryByText('Change')).toBeNull();
  });

  it('uses a heading and a region name the page gives', () => {
    render(<SummaryPin items={ITEMS} title="Entered" label="Entries" />);
    expect(screen.getByRole('region', { name: 'Entries' })).toHaveTextContent('Entered');
  });

  it('is inert and hidden from assistive technology while closed, and usable when open', () => {
    const { rerender, container } = render(<SummaryPin items={ITEMS} onChange={() => undefined} open={false} />);
    const card = container.querySelector('[data-pin]') as HTMLElement;
    expect(card).toHaveAttribute('data-open', 'false');
    expect(card.hasAttribute('inert')).toBe(true);
    expect(card).toHaveAttribute('aria-hidden', 'true');
    expect(screen.queryByRole('button', { name: 'Change the service' })).toBeNull();
    rerender(<SummaryPin items={ITEMS} onChange={() => undefined} open />);
    expect(card).toHaveAttribute('data-open', 'true');
    expect(card.hasAttribute('inert')).toBe(false);
    expect(screen.getByRole('button', { name: 'Change the service' })).toBeInTheDocument();
  });

  it('is open by default', () => {
    const { container } = render(<SummaryPin items={ITEMS} />);
    expect(container.querySelector('[data-pin]')).toHaveAttribute('data-open', 'true');
  });

  it('has no axe violations', async () => {
    const { container } = render(<SummaryPin items={ITEMS} onChange={() => undefined} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('SummaryPin pill (phone)', () => {
  it('is one button naming the count, closed at first, with the list not on screen', () => {
    render(<SummaryPin items={ITEMS} onChange={() => undefined} variant="pill" />);
    const pill = screen.getByRole('button', { name: /So far, 2 answers/ });
    expect(pill).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.queryByText('Hospital at home · East')).toBeNull();
  });

  it('shows the latest answer in the pill line', () => {
    render(<SummaryPin items={ITEMS} variant="pill" />);
    expect(screen.getByRole('button', { name: /So far/ })).toHaveTextContent('Duty manager, by text');
  });

  it('opens a sheet with the same list, and closes it again', () => {
    render(<SummaryPin items={ITEMS} onChange={() => undefined} variant="pill" />);
    fireEvent.click(screen.getByRole('button', { name: /So far/ }));
    const sheet = screen.getByRole('dialog', { name: 'What you have entered' });
    expect(within(sheet).getAllByRole('listitem')).toHaveLength(2);
    expect(screen.getByRole('button', { name: /So far/ })).toHaveAttribute('aria-expanded', 'true');
    fireEvent.click(within(sheet).getByRole('button', { name: 'Close' }));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('closes the sheet on Escape', () => {
    render(<SummaryPin items={ITEMS} variant="pill" />);
    fireEvent.click(screen.getByRole('button', { name: /So far/ }));
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('calls onChange from the sheet and closes it', () => {
    const onChange = vi.fn();
    render(<SummaryPin items={ITEMS} onChange={onChange} variant="pill" />);
    fireEvent.click(screen.getByRole('button', { name: /So far/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Change the service' }));
    expect(onChange).toHaveBeenCalledWith('service');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('draws nothing while there is nothing entered', () => {
    const { container } = render(<SummaryPin items={[]} variant="pill" />);
    expect(container).toBeEmptyDOMElement();
  });
});
