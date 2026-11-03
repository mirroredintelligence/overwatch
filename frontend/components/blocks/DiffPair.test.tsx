import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { DiffPair } from './DiffPair';

describe('DiffPair', () => {
  it('shows Was and Now, each with its chips', () => {
    render(<DiffPair was={['service-closed', 'system-pressure']} now={['service-closed', 'system-pressure', 'not-updated']} />);
    const was = within(screen.getByRole('group', { name: 'Was' })).getByRole('list');
    const now = within(screen.getByRole('group', { name: 'Now' })).getByRole('list');
    expect(within(was).getAllByRole('listitem').map((i) => i.textContent)).toEqual(['service-closed', 'system-pressure']);
    expect(within(now).getAllByRole('listitem')).toHaveLength(3);
  });

  it('marks an addition with "+" and in words, and leaves a kept chip unmarked', () => {
    render(<DiffPair was={['a']} now={['a', 'b', 'c']} />);
    const now = within(screen.getByRole('group', { name: 'Now' })).getByRole('list');
    const items = within(now).getAllByRole('listitem');
    expect(items[0]).toHaveAttribute('data-added', 'false');
    expect(items[0]).not.toHaveTextContent('+');
    expect(items[1]).toHaveAttribute('data-added', 'true');
    expect(items[1]).toHaveTextContent('+ b');
    expect(within(items[1]).getByText('Added')).toBeInTheDocument();
    expect(items[2]).toHaveTextContent('+ c');
  });

  it('says none for an empty side', () => {
    render(<DiffPair was={[]} now={['a']} />);
    expect(within(screen.getByRole('group', { name: 'Was' })).getByText('none')).toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<DiffPair was={['a']} now={['a', 'b']} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
