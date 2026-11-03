import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { GENERATED_AT, MAIN_ENTRIES } from '@/test/fixtures/board';
import { runAxe } from '@/test/a11y';
import { ServiceList } from './ServiceList';

const names = () =>
  within(screen.getByRole('list', { name: 'All services' }))
    .getAllByRole('listitem')
    .map((item) => item.querySelector('[data-el="SERVICE-ROW-NAME"]')?.textContent);

describe('ServiceList', () => {
  it('lists every service with its status word and a link to its page', () => {
    render(<ServiceList entries={MAIN_ENTRIES.slice(0, 3)} now={GENERATED_AT} />);
    const list = screen.getByRole('list', { name: 'All services' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(3);
    expect(within(list).getByRole('link', { name: /UCR West/ })).toHaveAttribute('href', '/planning/services/svc-ucr-west');
    expect(within(list).getAllByText('Accepting').length).toBeGreaterThan(0);
  });

  it('sorts what needs attention first, then by name, and says so', () => {
    render(<ServiceList entries={MAIN_ENTRIES} now={GENERATED_AT} />);
    expect(names()).toEqual([
      'Hospital at home',
      'SDEC · Site 2',
      'Virtual ward · frailty',
      'Community hospital · Ward A',
      'UCR East',
      'Community hospital · Ward B',
      'Reablement',
      'SDEC · Site 1',
      'UCR West',
    ]);
    expect(screen.getByText(/Sorted by what needs attention first, then by name\. Not ranked\. No patient information on this screen\./)).toBeInTheDocument();
  });

  it('shows the figure of each row, and a question mark where the figure is last known', () => {
    render(<ServiceList entries={MAIN_ENTRIES} now={GENERATED_AT} />);
    const row = (name: string) => screen.getByText(name, { selector: '[data-el="SERVICE-ROW-NAME"]' }).closest('li')!;
    expect(within(row('Hospital at home')).getByText('+2')).toBeInTheDocument();
    expect(within(row('SDEC · Site 2')).getByText('0')).toBeInTheDocument();
    expect(within(row('Virtual ward · frailty')).getByText('?')).toBeInTheDocument();
    expect(within(row('Virtual ward · frailty')).getByText(/Last known\. Not updated for 4 hrs 10 min\./)).toBeInTheDocument();
    expect(within(row('UCR West')).getByText('4')).toBeInTheDocument();
    expect(within(row('UCR West')).getByText(/updated 9 min ago/)).toBeInTheDocument();
  });

  it('offers the filter chips with their counts, All pressed at first', () => {
    render(<ServiceList entries={MAIN_ENTRIES} now={GENERATED_AT} />);
    const group = screen.getByRole('group', { name: 'Filter the services' });
    expect(within(group).getByRole('button', { name: /^All 9$/ })).toHaveAttribute('aria-pressed', 'true');
    expect(within(group).getByRole('button', { name: /^Needs attention 3$/ })).toHaveAttribute('aria-pressed', 'false');
    expect(within(group).getByRole('button', { name: /Accepting 4$/ })).toHaveAttribute('aria-pressed', 'false');
    expect(within(group).getByRole('button', { name: /Limited 2$/ })).toHaveAttribute('aria-pressed', 'false');
  });

  it('filters in place when a chip is pressed, and says which one is pressed', async () => {
    render(<ServiceList entries={MAIN_ENTRIES} now={GENERATED_AT} />);
    await userEvent.click(screen.getByRole('button', { name: /^Needs attention 3$/ }));
    expect(names()).toEqual(['Hospital at home', 'SDEC · Site 2', 'Virtual ward · frailty']);
    expect(screen.getByRole('button', { name: /^Needs attention 3$/ })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /^All 9$/ })).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(screen.getByRole('button', { name: /Limited 2$/ }));
    expect(names()).toEqual(['Community hospital · Ward A', 'UCR East']);
    await userEvent.click(screen.getByRole('button', { name: /Accepting 4$/ }));
    expect(names()).toHaveLength(4);
    await userEvent.click(screen.getByRole('button', { name: /^All 9$/ }));
    expect(names()).toHaveLength(9);
  });

  it('finds a service by part of its name, whatever the case', async () => {
    render(<ServiceList entries={MAIN_ENTRIES} now={GENERATED_AT} />);
    await userEvent.type(screen.getByRole('searchbox', { name: 'Find a service' }), 'sdec');
    expect(names()).toEqual(['SDEC · Site 2', 'SDEC · Site 1']);
  });

  it('says so, and how to get the list back, when nothing matches', async () => {
    render(<ServiceList entries={MAIN_ENTRIES} now={GENERATED_AT} />);
    await userEvent.type(screen.getByRole('searchbox', { name: 'Find a service' }), 'zzz');
    expect(screen.queryByRole('list', { name: 'All services' })).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('No service matches. Clear the search or choose All.');
    await userEvent.click(screen.getByRole('button', { name: 'Clear the search' }));
    expect(names()).toHaveLength(9);
  });

  it('says there are no services when the board holds none', () => {
    render(<ServiceList entries={[]} now={GENERATED_AT} />);
    expect(screen.getByText('There are no services on the board yet.')).toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<ServiceList entries={MAIN_ENTRIES} now={GENERATED_AT} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
