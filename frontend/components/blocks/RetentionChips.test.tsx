import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { RetentionChips } from './RetentionChips';

const ITEMS = [
  { id: 'a', text: 'Case audit: 7 years, then deleted' },
  { id: 'b', text: 'Audit chain: kept, no time limit', kept: true },
];

describe('RetentionChips', () => {
  it('lists one item per rule, in a labelled list', () => {
    render(<RetentionChips label="Retention rules" items={ITEMS} />);
    const list = screen.getByRole('list', { name: 'Retention rules' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    expect(screen.getByText('Case audit: 7 years, then deleted')).toBeInTheDocument();
  });

  it('marks a kept rule by data attribute and keeps the word in the text', () => {
    render(<RetentionChips label="Rules" items={ITEMS} />);
    expect(screen.getByText('Audit chain: kept, no time limit').closest('li')).toHaveAttribute('data-kept', 'true');
    expect(screen.getByText('Case audit: 7 years, then deleted').closest('li')).not.toHaveAttribute('data-kept');
  });

  it('renders nothing for an empty list', () => {
    const { container } = render(<RetentionChips label="Rules" items={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('has no axe violations', async () => {
    const { container } = render(<RetentionChips label="Rules" items={ITEMS} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
