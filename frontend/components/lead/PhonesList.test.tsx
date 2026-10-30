import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { PhonesList } from './PhonesList';

// The phones and the services they report for (W43). Only the last three digits of a phone are shown.

describe('PhonesList', () => {
  it('shows a phone as its last three digits, with the flag when it holds more than three services', async () => {
    render(<PhonesList />);
    const row = (await screen.findByText('…777')).closest('tr') as HTMLElement;
    expect(within(row).getByText('Holds 4 services')).toBeInTheDocument();
    expect(within(row).getByText('Duty manager')).toBeInTheDocument();
    expect(document.body.textContent ?? '').not.toMatch(/07700\s?\d{6}/);
  });

  it('does not flag a phone with three services or fewer', async () => {
    render(<PhonesList />);
    const row = (await screen.findByText('…456')).closest('tr') as HTMLElement;
    expect(within(row).queryByText(/Holds \d services/)).not.toBeInTheDocument();
  });

  it('has a caption and header cells, and the note on slow replies', async () => {
    render(<PhonesList />);
    const table = await screen.findByRole('table', { name: 'Phones and the services they report for' });
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual([
      'Phone',
      'Role',
      'Services',
      'Channel',
      'Last seen',
      'Flag',
    ]);
    expect(screen.getByText('More than 3 services on one phone slows replies.')).toBeInTheDocument();
  });

  it('links to moving a service and adding a service to a phone', async () => {
    render(<PhonesList />);
    await screen.findByText('…777');
    expect(screen.getByRole('link', { name: 'Move a service' })).toHaveAttribute('href', '/lead/phones/move');
    expect(screen.getByRole('link', { name: 'Add a service to a phone' })).toHaveAttribute('href', '/lead/services/new');
  });

  it('says the phones could not be loaded, and never shows an empty table for a failed read', async () => {
    server.use(http.get('/api/bff/lead/phones', () => HttpResponse.json({ code: 'unavailable' }, { status: 503 })));
    render(<PhonesList />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the phones.');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(<PhonesList />);
    await screen.findByText('…777');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
