import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { resetLeadPosts, seenLeadPosts } from '@/test/msw/handlers/lead';
import { SERVICE_UCR_EAST } from '@/test/fixtures/lead';
import { MoveServiceForm } from './MoveServiceForm';

// Move a service to another phone (W43). The right panel always shows the three steps. Nothing moves until step 3,
// and the old phone keeps its other services.

beforeEach(() => {
  resetLeadPosts();
  document.cookie = 'overwatch_csrf=test-csrf-token';
});

function steps(): HTMLElement {
  return screen.getByRole('list', { name: 'Three steps, in this order' });
}

describe('MoveServiceForm', () => {
  it('shows the three steps in the right panel before anything is sent, and that nothing moves until step 3', () => {
    render(<MoveServiceForm />);
    const list = steps();
    expect(within(list).getAllByRole('listitem')).toHaveLength(3);
    expect(within(list).getByText(/We text the new phone a code/)).toBeInTheDocument();
    expect(within(list).getByText(/You phone the service/)).toBeInTheDocument();
    expect(within(list).getByText(/Use the number from the register/)).toBeInTheDocument();
    expect(within(list).getByText(/The service goes to the new phone/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing moves until step 3\./)).toBeInTheDocument();
    expect(screen.getByText(/The old phone keeps its other services\./)).toBeInTheDocument();
    expect(within(list).getAllByRole('listitem')[0]).toHaveAttribute('data-state', 'open');
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('has one heading that names the act, and Start the move and Cancel', () => {
    render(<MoveServiceForm />);
    expect(screen.getByRole('heading', { level: 1, name: 'Move a service to another phone' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start the move' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Cancel' })).toHaveAttribute('href', '/lead/phones');
  });

  it('says the services could not be loaded', async () => {
    server.use(http.get('/api/bff/lead/services', () => HttpResponse.json({ code: 'unavailable' }, { status: 503 })));
    render(<MoveServiceForm />);
    expect(await screen.findByText('The services could not be loaded.')).toBeInTheDocument();
  });

  it('asks for a date when the cover is for a while, and does not post without one', async () => {
    const user = userEvent.setup();
    render(<MoveServiceForm serviceId={SERVICE_UCR_EAST} />);
    await user.type(await screen.findByLabelText('To which phone?'), '07700 900123');
    await user.click(screen.getByRole('radio', { name: 'For a while' }));
    await user.click(screen.getByRole('button', { name: 'Start the move' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose the date the cover ends');
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('posts a move for good, with the phone as typed and the CSRF token', async () => {
    const user = userEvent.setup();
    render(<MoveServiceForm serviceId={SERVICE_UCR_EAST} />);
    await user.type(await screen.findByLabelText('To which phone?'), '07700 900123');
    await user.click(screen.getByRole('radio', { name: 'For good' }));
    await user.click(screen.getByRole('button', { name: 'Start the move' }));
    expect(await screen.findByRole('status')).toHaveTextContent('The move has started.');
    expect(seenLeadPosts[0]).toMatchObject({
      path: `/api/bff/lead/services/${SERVICE_UCR_EAST}/move`,
      csrf: 'test-csrf-token',
      body: { toPhone: '07700 900123', until: 'changed' },
    });
  });

  it('posts a move for a while, with the date the cover ends', async () => {
    const user = userEvent.setup();
    render(<MoveServiceForm serviceId={SERVICE_UCR_EAST} />);
    await user.type(await screen.findByLabelText('To which phone?'), '07700 900123');
    await user.click(screen.getByRole('radio', { name: 'For a while' }));
    await user.type(screen.getByLabelText('Cover ends on'), '2026-12-31');
    await user.click(screen.getByRole('button', { name: 'Start the move' }));
    await screen.findByRole('status');
    expect(seenLeadPosts[0].body).toMatchObject({ toPhone: '07700 900123', until: 'date', date: '2026-12-31' });
  });

  it('marks step 1 as done once the move has started, and no later step', async () => {
    const user = userEvent.setup();
    render(<MoveServiceForm serviceId={SERVICE_UCR_EAST} />);
    await user.type(await screen.findByLabelText('To which phone?'), '07700 900123');
    await user.click(screen.getByRole('radio', { name: 'For good' }));
    await user.click(screen.getByRole('button', { name: 'Start the move' }));
    await screen.findByRole('status');
    const items = within(steps()).getAllByRole('listitem');
    expect(items[0]).toHaveAttribute('data-state', 'done');
    expect(items[1]).toHaveAttribute('data-state', 'open');
    expect(items[2]).toHaveAttribute('data-state', 'open');
  });

  it('refuses a number that is not a UK mobile, with the example', async () => {
    const user = userEvent.setup();
    render(<MoveServiceForm serviceId={SERVICE_UCR_EAST} />);
    await user.type(await screen.findByLabelText('To which phone?'), '0123');
    await user.click(screen.getByRole('radio', { name: 'For good' }));
    await user.click(screen.getByRole('button', { name: 'Start the move' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Enter a UK mobile number, like 07700 900123');
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('has no axe violations', async () => {
    const { container } = render(<MoveServiceForm serviceId={SERVICE_UCR_EAST} />);
    await screen.findByLabelText('To which phone?');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
