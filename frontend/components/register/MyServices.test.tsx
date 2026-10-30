import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { MyServices } from './MyServices';

// My services (W26): one row per service, its status as a word, and an Edit link to its status page.

describe('MyServices', () => {
  it('renders the three sample rows with their status words and details, and the invitation note', async () => {
    render(<MyServices />);
    expect(await screen.findByRole('heading', { level: 1, name: 'My services' })).toBeInTheDocument();
    const rows = await screen.findAllByRole('listitem');
    expect(rows).toHaveLength(3);
    expect(within(rows[0]!).getByText('UCR West')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('Active')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('Reporting every 2 hrs by text')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('Pending approval')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('Submitted 23 Oct')).toBeInTheDocument();
    expect(within(rows[2]!).getByText('Review due')).toBeInTheDocument();
    expect(within(rows[2]!).getByText('Criteria review due 30 Oct')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Edit UCR West' })).toHaveAttribute('href', '/register/REG-SAMPLE-1/status');
    expect(screen.getByText('To add a service, ask the SPOA shift lead. New services are added by invitation and checked.')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(<MyServices />);
    await screen.findAllByRole('listitem');
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
