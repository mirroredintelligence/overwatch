import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetLeadPosts, seenLeadPosts } from '@/test/msw/handlers/lead';
import { server } from '@/test/msw/server';
import { RemovePersonForm } from './RemovePersonForm';

// Remove a person's access (W42). The effects are shown before the lead submits. Submitting asks for a
// confirmation (an alertdialog naming the person and the reason); only its destructive button sends.

beforeEach(() => {
  resetLeadPosts();
  document.cookie = 'overwatch_csrf=test-csrf-token';
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

  it('titles the page as the board does, with the what-happens panel named', () => {
    render(<RemovePersonForm />);
    expect(screen.getByRole('heading', { level: 1, name: "Remove someone's access" })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'What happens' })).toBeInTheDocument();
  });

  it('shows placeholders while the people load', () => {
    render(<RemovePersonForm />);
    expect(screen.getByText('Loading the people.')).toBeInTheDocument();
  });

  it('lists each reporter post by its service, role and last four digits, and never a whole number', async () => {
    render(<RemovePersonForm />);
    expect(await screen.findByRole('option', { name: 'UCR East, Duty manager, ending 4821' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Reablement, Duty manager, ending 0377' })).toBeInTheDocument();
    expect(document.body.textContent ?? '').not.toMatch(/07700\s?900/);
  });

  it('says the people could not be loaded, keeps the reasons, and offers Try again', async () => {
    server.use(http.get('/api/bff/lead/reporters', () => HttpResponse.json({ code: 'exception' }, { status: 500 })));
    render(<RemovePersonForm />);
    expect(await screen.findByRole('alert')).toHaveTextContent('The people could not be loaded.');
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Lost phone' })).toBeInTheDocument();
  });

  it('loads the people again when Try again is pressed', async () => {
    const user = userEvent.setup();
    let calls = 0;
    server.use(
      http.get('/api/bff/lead/reporters', () => {
        calls += 1;
        return calls === 1
          ? HttpResponse.json({ code: 'exception' }, { status: 500 })
          : HttpResponse.json({ reporters: [] }, { headers: { 'Cache-Control': 'no-store' } });
      }),
    );
    render(<RemovePersonForm />);
    await user.click(await screen.findByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument());
    expect(calls).toBe(2);
  });

  it('asks to confirm, naming the person and the reason, before anything is sent', async () => {
    const user = userEvent.setup();
    render(<RemovePersonForm />);
    await screen.findByRole('option', { name: 'Reablement, Duty manager, ending 0377' });
    await user.selectOptions(screen.getByLabelText('Person (role or phone ending)'), 'role-reablement');
    await user.click(screen.getByRole('radio', { name: 'Lost phone' }));
    await user.click(screen.getByRole('button', { name: 'Remove access' }));
    const dialog = await screen.findByRole('alertdialog', { name: 'Remove access for ···0377?' });
    expect(dialog).toHaveTextContent('Reason: lost phone.');
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('puts focus on the safe choice in the confirmation, and the destructive button names the person', async () => {
    const user = userEvent.setup();
    render(<RemovePersonForm />);
    await screen.findByRole('option', { name: 'UCR East, Duty manager, ending 4821' });
    await user.selectOptions(screen.getByLabelText('Person (role or phone ending)'), 'role-ucr-east');
    await user.click(screen.getByRole('radio', { name: 'Lost phone' }));
    await user.click(screen.getByRole('button', { name: 'Remove access' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Keep access' })).toHaveFocus());
    expect(screen.getByRole('button', { name: 'Remove access for ···4821' })).toBeInTheDocument();
  });

  it('posts the chosen post and the reason only after confirmation, and says the access was removed', async () => {
    const user = userEvent.setup();
    render(<RemovePersonForm />);
    await screen.findByRole('option', { name: 'UCR East, Duty manager, ending 4821' });
    await user.selectOptions(screen.getByLabelText('Person (role or phone ending)'), 'role-ucr-east');
    await user.click(screen.getByRole('radio', { name: 'Lost phone' }));
    await user.click(screen.getByRole('button', { name: 'Remove access' }));
    await user.click(await screen.findByRole('button', { name: 'Remove access for ···4821' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Access removed.');
    expect(seenLeadPosts[0]).toMatchObject({
      path: '/api/bff/lead/people/remove',
      body: { person: 'role-ucr-east', reason: 'lost-phone' },
    });
  });

  it('closes the confirmation from Keep access and sends nothing', async () => {
    const user = userEvent.setup();
    render(<RemovePersonForm />);
    await screen.findByRole('option', { name: 'UCR East, Duty manager, ending 4821' });
    await user.selectOptions(screen.getByLabelText('Person (role or phone ending)'), 'role-ucr-east');
    await user.click(screen.getByRole('radio', { name: 'Lost phone' }));
    await user.click(screen.getByRole('button', { name: 'Remove access' }));
    await user.click(await screen.findByRole('button', { name: 'Keep access' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('shows a failed removal in words inside the confirmation', async () => {
    const user = userEvent.setup();
    server.use(http.post('/api/bff/lead/people/remove', () => HttpResponse.json({ code: 'exception' }, { status: 500 })));
    render(<RemovePersonForm />);
    await screen.findByRole('option', { name: 'UCR East, Duty manager, ending 4821' });
    await user.selectOptions(screen.getByLabelText('Person (role or phone ending)'), 'role-ucr-east');
    await user.click(screen.getByRole('radio', { name: 'Lost phone' }));
    await user.click(screen.getByRole('button', { name: 'Remove access' }));
    await user.click(await screen.findByRole('button', { name: 'Remove access for ···4821' }));
    const dialog = screen.getByRole('alertdialog', { name: 'Remove access for ···4821?' });
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('The access could not be removed. Try again.');
  });

  it('Cancel clears the choices and sends nothing', async () => {
    const user = userEvent.setup();
    render(<RemovePersonForm />);
    await screen.findByRole('option', { name: 'UCR East, Duty manager, ending 4821' });
    await user.selectOptions(screen.getByLabelText('Person (role or phone ending)'), 'role-ucr-east');
    await user.click(screen.getByRole('radio', { name: 'Lost phone' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByLabelText('Person (role or phone ending)')).toHaveValue('');
    expect(screen.getByRole('radio', { name: 'Lost phone' })).not.toBeChecked();
    expect(seenLeadPosts).toHaveLength(0);
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
