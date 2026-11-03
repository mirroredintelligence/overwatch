import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { CriteriaHistory } from './CriteriaHistory';

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

// The user-event tests here run slowly when the whole suite shares the machine; the budget is per file.
vi.setConfig({ testTimeout: 15_000 });

// The history fixture (test/fixtures/criteria.ts): version 4 waiting, version 3 live, versions 2 and 1 replaced.
// The back end gives no sender, approver or changed fields, so the page shows version, state and review-by only.

describe('CriteriaHistory', () => {
  it('shows the versions as a timeline, newest first, with a heading', async () => {
    render(<CriteriaHistory serviceId="s1" />);
    expect(await screen.findByRole('heading', { level: 1, name: 'History' })).toBeInTheDocument();
    const list = screen.getByRole('list', { name: 'Versions' });
    const items = within(list).getAllByRole('listitem');
    expect(items).toHaveLength(4);
    expect(items[0]).toHaveTextContent('Version 4');
    expect(items[1]).toHaveTextContent('Version 3');
    expect(items[2]).toHaveTextContent('Version 2');
    expect(items[3]).toHaveTextContent('Version 1');
  });

  it('says each version state in words, and marks the live version as current', async () => {
    render(<CriteriaHistory serviceId="s1" />);
    const items = within(await screen.findByRole('list', { name: 'Versions' })).getAllByRole('listitem');
    expect(within(items[0]!).getByText('Waiting for approval')).toBeInTheDocument();
    expect(within(items[1]!).getByText('Live now')).toBeInTheDocument();
    expect(within(items[2]!).getByText('Replaced')).toBeInTheDocument();
    expect(within(items[3]!).getByText('At registration')).toBeInTheDocument();
    expect(items[0]).toHaveAttribute('data-state', 'waiting');
    expect(items[1]).toHaveAttribute('aria-current', 'true');
    expect(items[2]).not.toHaveAttribute('aria-current');
  });

  it('shows the review-by date of each version that has one', async () => {
    render(<CriteriaHistory serviceId="s1" />);
    expect(await screen.findByText('Review by 12 Dec')).toBeInTheDocument();
    expect(screen.getByText('Review by 12 Sep')).toBeInTheDocument();
  });

  it('says which version replaced each earlier one', async () => {
    render(<CriteriaHistory serviceId="s1" />);
    expect(await screen.findByText('Replaced by version 3')).toBeInTheDocument();
    expect(screen.getByText('Replaced by version 2')).toBeInTheDocument();
  });

  it('does not show who sent or approved a version, or what changed, because the history does not have them', async () => {
    render(<CriteriaHistory serviceId="s1" />);
    await screen.findByRole('list', { name: 'Versions' });
    expect(screen.queryByText('Approved')).not.toBeInTheDocument();
    expect(screen.queryByText(/What changed from version/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Sent /)).not.toBeInTheDocument();
  });

  it('offers a new draft from the live version and says a second person sees it first', async () => {
    render(<CriteriaHistory serviceId="s1" />);
    expect(
      await screen.findByText('You can start a new draft from the live version. It goes to a second person before advisors see it.'),
    ).toBeInTheDocument();
    const draft = screen.getByRole('button', { name: 'Start a new draft from version 3' });
    expect(draft).toHaveAttribute('data-el', 'OWN-HISTORY-NEWDRAFT-BTN');
    await userEvent.setup().click(draft);
    expect(push).toHaveBeenCalledWith('/criteria/s1?step=edit');
  });

  it('says the record keeps every version and nothing is deleted', async () => {
    render(<CriteriaHistory serviceId="s1" />);
    expect(
      await screen.findByText('Every version stays in the audit record, with who sent it and who approved it. Nothing is ever deleted.'),
    ).toBeInTheDocument();
  });

  it('says in words that the history is loading until it arrives', () => {
    render(<CriteriaHistory serviceId="s1" />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading the history.');
  });

  it('shows a warning when the history cannot be loaded', async () => {
    server.use(http.get('/api/bff/criteria/:serviceId/history', () => HttpResponse.json({}, { status: 500 })));
    render(<CriteriaHistory serviceId="s1" />);
    expect(await screen.findByText('The history could not be loaded. Try again shortly.')).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Versions' })).not.toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<CriteriaHistory serviceId="s1" />);
    await screen.findByRole('list', { name: 'Versions' });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
