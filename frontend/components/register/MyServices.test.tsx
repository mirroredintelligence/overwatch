import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { MyServices } from './MyServices';
import { withApplicantHandlers } from '@/test/msw/applicant';

withApplicantHandlers();

// My services (W26): one card with a row per service, its state as a shape and a word, and one action to its
// status page. A new service comes by invitation from the shift lead: there is no button to register another.

describe('MyServices', () => {
  it('renders the three sample rows with their state words, details and actions', async () => {
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
  });

  it('names each action for what it does: Edit an active service, Open one being approved, Review one that is due', async () => {
    render(<MyServices />);
    await screen.findAllByRole('listitem');
    expect(screen.getByRole('link', { name: 'Edit UCR West' })).toHaveAttribute('href', '/register/REG-SAMPLE-1/status');
    expect(screen.getByRole('link', { name: 'Open UCR East' })).toHaveAttribute('href', '/register/REG-SAMPLE-2/status');
    expect(screen.getByRole('link', { name: 'Review Ward 4' })).toHaveAttribute('href', '/register/REG-SAMPLE-3/status');
  });

  it('draws the state as a shape beside the word, and the review-due row as the one that needs attention', async () => {
    render(<MyServices />);
    const rows = await screen.findAllByRole('listitem');
    expect(rows[0]!.querySelector('[data-variant="live"] svg')).not.toBeNull();
    expect(rows[1]!.querySelector('[data-variant="waiting"] svg')).not.toBeNull();
    expect(rows[2]!.querySelector('[data-variant="due"] svg')).not.toBeNull();
    expect(rows[2]!).toHaveAttribute('data-attention', 'true');
    expect(rows[0]!).not.toHaveAttribute('data-attention');
  });

  it('says a new service comes by invitation from the shift lead, and offers no way to register another', async () => {
    render(<MyServices />);
    await screen.findAllByRole('listitem');
    expect(screen.getByText('A new service comes by invitation from your shift lead.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /register another/i })).toBeNull();
    expect(screen.queryByRole('link', { name: /register another/i })).toBeNull();
  });

  it('says what is loading in words while the services are read', () => {
    render(<MyServices />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading your services.');
  });

  it('says the services could not be loaded, with no rows', async () => {
    server.use(http.get('/api/bff/registrations/mine', () => HttpResponse.json({}, { status: 503 })));
    render(<MyServices />);
    expect(await screen.findByText('We could not load your registration. Try again later.')).toBeInTheDocument();
    expect(screen.queryAllByRole('listitem')).toHaveLength(0);
  });

  it('asks the person to sign in again when the session has ended', async () => {
    server.use(http.get('/api/bff/registrations/mine', () => HttpResponse.json({}, { status: 401 })));
    render(<MyServices />);
    expect(await screen.findByText('Please sign in again.')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(<MyServices />);
    await screen.findAllByRole('listitem');
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
