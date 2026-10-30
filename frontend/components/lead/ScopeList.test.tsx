import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetRegistrationRequests, seenRegistrationRequests } from '@/test/msw/handlers/registrations';
import { ScopeList } from './ScopeList';

beforeEach(() => resetRegistrationRequests());

const posts = () => seenRegistrationRequests.filter((request) => request.method === 'POST');


// The user-event tests here run slowly when the whole suite shares the machine; the budget is per file.
vi.setConfig({ testTimeout: 15_000 });

describe('ScopeList', () => {
  it('shows the three sample services, and an Invite link only on the in-pilot service not yet invited', async () => {
    const { container } = render(<ScopeList />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Services in scope' })).toBeInTheDocument();
    expect(screen.getByText('You can only invite services on this list.')).toBeInTheDocument();

    const rows = await screen.findAllByRole('listitem');
    expect(rows).toHaveLength(3);
    expect(within(rows[0]!).getByText('UCR West')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('Live')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('In review')).toBeInTheDocument();
    expect(within(rows[2]!).getByText('Not invited')).toBeInTheDocument();
    expect(within(rows[2]!).getByText('In pilot')).toBeInTheDocument();

    const invites = screen.getAllByRole('link', { name: 'Invite' });
    expect(invites).toHaveLength(1);
    expect(invites[0]).toHaveAttribute('href', '/lead/reporters/invite?service=s3');
    expect(invites[0]).toHaveAttribute('data-el', 'LEAD-SCOPE-INVITE-LINK');

    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('refuses a reason-less "Out of scope" entry with "Enter a reason" and sends nothing, then adds the row', async () => {
    const user = userEvent.setup();
    render(<ScopeList />);
    await screen.findAllByRole('listitem');

    await user.click(screen.getByRole('button', { name: 'Add a service to the scope list' }));
    await user.type(screen.getByLabelText('Service name'), 'Reablement team');
    await user.selectOptions(screen.getByLabelText('Category'), 'reablement');
    await user.click(screen.getByRole('radio', { name: 'Out of scope' }));
    await user.click(screen.getByRole('button', { name: 'Add service' }));

    expect(await screen.findByText('Enter a reason')).toBeInTheDocument();
    expect(posts()).toHaveLength(0);

    await user.type(screen.getByLabelText('Reason'), 'Not on the Dorset pathway');
    await user.click(screen.getByRole('button', { name: 'Add service' }));

    expect(await screen.findByText('Reablement team')).toBeInTheDocument();
    expect(posts()).toHaveLength(1);
    expect(posts()[0]?.body).toEqual({
      name: 'Reablement team',
      category: 'reablement',
      flag: 'out-of-scope',
      reason: 'Not on the Dorset pathway',
    });
    expect(posts()[0]?.idempotencyKey).toBeTruthy();
    expect(posts()[0]?.csrf).toBe('csrf-sample-staff');
  });
});
