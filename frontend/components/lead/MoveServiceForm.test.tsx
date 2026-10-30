import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetLeadPosts, seenLeadPosts } from '@/test/msw/handlers/lead';
import { SERVICE_UCR_EAST } from '@/test/fixtures/lead';
import { MoveServiceForm } from './MoveServiceForm';

// Move a service to another phone (W43). The old phone keeps its other services.

beforeEach(() => {
  resetLeadPosts();
  document.cookie = 'diucs_csrf=test-csrf-token';
});

describe('MoveServiceForm', () => {
  it('shows the three steps before it is submitted, and what stays on the old phone', () => {
    render(<MoveServiceForm />);
    expect(screen.getByText('We text the new phone a code')).toBeInTheDocument();
    expect(screen.getByText('You phone the service on the number from the register')).toBeInTheDocument();
    expect(screen.getByText('The service goes to the new phone')).toBeInTheDocument();
    expect(screen.getByText('The old phone keeps its other services.')).toBeInTheDocument();
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('asks for a date when the cover is until a date, and does not post without one', async () => {
    const user = userEvent.setup();
    render(<MoveServiceForm serviceId={SERVICE_UCR_EAST} />);
    await user.type(await screen.findByLabelText('To mobile number'), '07700 900123');
    await user.click(screen.getByRole('radio', { name: 'Cover until a date' }));
    await user.click(screen.getByRole('button', { name: 'Start the move' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose the date the cover ends');
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('posts a move until changed, with the phone as typed and the CSRF token', async () => {
    const user = userEvent.setup();
    render(<MoveServiceForm serviceId={SERVICE_UCR_EAST} />);
    await user.type(await screen.findByLabelText('To mobile number'), '07700 900123');
    await user.click(screen.getByRole('radio', { name: 'Until I change it' }));
    await user.click(screen.getByRole('button', { name: 'Start the move' }));
    expect(await screen.findByRole('status')).toHaveTextContent('The move has started.');
    expect(seenLeadPosts[0]).toMatchObject({
      path: `/api/bff/lead/services/${SERVICE_UCR_EAST}/move`,
      csrf: 'test-csrf-token',
      body: { toPhone: '07700 900123', until: 'changed' },
    });
  });

  it('posts a move until a date, with the date', async () => {
    const user = userEvent.setup();
    render(<MoveServiceForm serviceId={SERVICE_UCR_EAST} />);
    await user.type(await screen.findByLabelText('To mobile number'), '07700 900123');
    await user.click(screen.getByRole('radio', { name: 'Cover until a date' }));
    await user.type(screen.getByLabelText('Cover ends on'), '2026-12-31');
    await user.click(screen.getByRole('button', { name: 'Start the move' }));
    await screen.findByRole('status');
    expect(seenLeadPosts[0].body).toMatchObject({ toPhone: '07700 900123', until: 'date', date: '2026-12-31' });
  });

  it('refuses a number that is not a UK mobile, with the example', async () => {
    const user = userEvent.setup();
    render(<MoveServiceForm serviceId={SERVICE_UCR_EAST} />);
    await user.type(await screen.findByLabelText('To mobile number'), '0123');
    await user.click(screen.getByRole('radio', { name: 'Until I change it' }));
    await user.click(screen.getByRole('button', { name: 'Start the move' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Enter a UK mobile number, like 07700 900123');
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('has no axe violations', async () => {
    const { container } = render(<MoveServiceForm serviceId={SERVICE_UCR_EAST} />);
    await screen.findByLabelText('To mobile number');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
