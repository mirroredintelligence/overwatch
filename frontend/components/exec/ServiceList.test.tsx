import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MAIN_ENTRIES } from '@/test/fixtures/board';
import { runAxe } from '@/test/a11y';
import { ServiceList } from './ServiceList';

describe('ServiceList', () => {
  it('lists every service with its status word and a link to its page', () => {
    render(<ServiceList entries={MAIN_ENTRIES.slice(0, 3)} />);
    const list = screen.getByRole('list', { name: 'All services' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(3);
    expect(within(list).getByRole('link', { name: /UCR West/ })).toHaveAttribute('href', '/planning/services/svc-ucr-west');
    expect(within(list).getAllByText('Accepting').length).toBeGreaterThan(0);
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<ServiceList entries={MAIN_ENTRIES.slice(0, 3)} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
