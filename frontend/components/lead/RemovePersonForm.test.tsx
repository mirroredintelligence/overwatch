import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetLeadPosts, seenLeadPosts } from '@/test/msw/handlers/lead';
import { RemovePersonForm } from './RemovePersonForm';

// Remove a person's access (W42). The effects are shown before the lead submits.

beforeEach(() => {
  resetLeadPosts();
  document.cookie = 'diucs_csrf=test-csrf-token';
});

describe('RemovePersonForm', () => {
  it('shows what removing access does before it is submitted', () => {
    render(<RemovePersonForm />);
    expect(screen.getByText('The phone is signed out everywhere.')).toBeInTheDocument();
    expect(screen.getByText('Notifications stop.')).toBeInTheDocument();
    expect(screen.getByText('Prompts go to the cover number, or to you.')).toBeInTheDocument();
    expect(screen.getByText('Past reports stay in the record.')).toBeInTheDocument();
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('posts the person and the reason, and says the access was removed', async () => {
    const user = userEvent.setup();
    render(<RemovePersonForm />);
    await user.type(screen.getByLabelText('Person (role or phone ending)'), 'role-42');
    await user.click(screen.getByRole('radio', { name: 'Lost phone' }));
    await user.click(screen.getByRole('button', { name: 'Remove access' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Access removed.');
    expect(seenLeadPosts[0]).toMatchObject({
      path: '/api/bff/lead/people/remove',
      body: { person: 'role-42', reason: 'lost-phone' },
    });
  });

  it('asks for the person and the reason before it submits', async () => {
    const user = userEvent.setup();
    render(<RemovePersonForm />);
    await user.click(screen.getByRole('button', { name: 'Remove access' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose who to remove');
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('has no axe violations', async () => {
    const { container } = render(<RemovePersonForm />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
