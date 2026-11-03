import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetStepSaves, reviewState, seenSubmits } from '@/test/msw/handlers/registration';
import { server } from '@/test/msw/server';
import { ReviewList } from './ReviewList';
import { withApplicantHandlers } from '@/test/msw/applicant';

withApplicantHandlers();

// Registration step 5, the review (Reg board stage 5, RP3 board on a phone). Five sections, each with its state
// word, a summary and Change; a section that needs attention has Fix this instead. Submit is a real disabled
// button until every section is complete, and says how many need attention.

const push = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const ID = 'REG-SAMPLE-1';

async function open() {
  const view = render(<ReviewList registrationId={ID} />);
  // The header renders while the review loads; wait for the first section's Change link.
  await screen.findByRole('link', { name: 'Change Organisation' });
  return view;
}

async function openWithAttention() {
  const view = render(<ReviewList registrationId={ID} />);
  await screen.findByRole('link', { name: 'Fix this: Service' });
  return view;
}

function withSection(key: string, status: 'complete' | 'needs-attention', summary: string) {
  reviewState.reply = {
    status: 200,
    body: {
      sections: (reviewState.reply.body as { sections: { key: string; status: string; summary: string }[] }).sections.map((section) =>
        section.key === key ? { ...section, status, summary } : section,
      ),
    },
  };
}

function phone(matches: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockImplementation((query: string) => ({
      matches,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    })),
  );
}

beforeEach(() => {
  push.mockClear();
  resetStepSaves();
});

afterEach(() => vi.unstubAllGlobals());

describe('ReviewList', () => {
  it('lists the five sections with their status words, summaries and Change links', async () => {
    await open();
    expect(screen.getByText('Step 5 of 5')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Check your details' })).toBeInTheDocument();
    for (const [title, href] of [
      ['Organisation', `/register/${ID}/organisation`],
      ['Location', `/register/${ID}/location`],
      ['Service', `/register/${ID}/service`],
      ['Capacity reporting', `/register/${ID}/reporting`],
      ['API', `/register/${ID}/reporting`],
    ] as const) {
      const row = screen.getByRole('listitem', { name: new RegExp(`^${title}`) });
      expect(within(row).getByText('Complete')).toBeInTheDocument();
      expect(within(row).getByRole('link', { name: `Change ${title}` })).toHaveAttribute('href', href);
      expect(within(row).queryByRole('link', { name: /^Fix this/ })).not.toBeInTheDocument();
    }
    expect(
      screen.getByText('UCR West · Urgent community response · refer by phone and SystmOne'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Your shift lead checks your details and sends a test text. You will not appear on the board until approved.'),
    ).toBeInTheDocument();
  });

  it('sits in the register frame: the checklist with Review as the current step, and Save and come back later', async () => {
    await open();
    const nav = screen.getByRole('navigation', { name: 'Your registration' });
    expect(within(nav).getByRole('link', { name: /^Review/ })).toHaveAttribute('aria-current', 'step');
    expect(screen.getByRole('link', { name: 'Save and come back later' })).toHaveAttribute('href', '/register?saved=1');
  });

  it('shows "Needs attention" as a word on its row, with Fix this to the step instead of Change', async () => {
    withSection('service', 'needs-attention', 'UCR West · criteria review date missing');
    await openWithAttention();
    const row = screen.getByRole('listitem', { name: /^Service/ });
    expect(within(row).getByText('Needs attention')).toBeInTheDocument();
    expect(within(row).getByText('UCR West · criteria review date missing')).toBeInTheDocument();
    expect(within(row).getByRole('link', { name: 'Fix this: Service' })).toHaveAttribute('href', `/register/${ID}/service`);
    expect(within(row).queryByRole('link', { name: 'Change Service' })).not.toBeInTheDocument();
    // The other rows keep Change and have no Fix this.
    expect(screen.getAllByRole('link', { name: /^Fix this/ })).toHaveLength(1);
    expect(screen.getByRole('link', { name: 'Change Location' })).toBeInTheDocument();
  });

  it('marks the section on the checklist as needing attention', async () => {
    withSection('service', 'needs-attention', 'UCR West · criteria review date missing');
    await openWithAttention();
    const nav = screen.getByRole('navigation', { name: 'Your registration' });
    expect(within(nav).getByRole('link', { name: /^Service/ })).toHaveTextContent('Needs attention');
    expect(within(nav).getByRole('link', { name: /^Organisation/ })).toHaveTextContent('Complete');
  });

  it('Submit is a disabled button saying how many sections need attention, and posts nothing', async () => {
    withSection('service', 'needs-attention', 'UCR West · criteria review date missing');
    await openWithAttention();
    const submit = screen.getByRole('button', { name: 'Submit for approval' });
    expect(submit).toBeDisabled();
    expect(screen.getByText('1 section needs attention first')).toBeInTheDocument();
    await userEvent.click(submit);
    expect(seenSubmits).toHaveLength(0);
    expect(push).not.toHaveBeenCalled();
  });

  it('counts two sections in the plural', async () => {
    withSection('service', 'needs-attention', 'UCR West · criteria review date missing');
    withSection('location', 'needs-attention', 'No site address yet');
    await openWithAttention();
    expect(screen.getByRole('button', { name: 'Submit for approval' })).toBeDisabled();
    expect(screen.getByText('2 sections need attention first')).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /^Fix this/ })).toHaveLength(2);
  });

  it('Submit with every section complete is enabled, says nothing about attention, posts with the CSRF header and lands on the submitted page', async () => {
    await open();
    expect(screen.queryByText(/need.* attention first/)).not.toBeInTheDocument();
    const submit = screen.getByRole('button', { name: 'Submit for approval' });
    expect(submit).toBeEnabled();
    await userEvent.click(submit);
    await waitFor(() => expect(push).toHaveBeenCalledWith(`/register/${ID}/submitted`));
    expect(seenSubmits).toEqual([{ id: ID, csrf: 'csrf-sample-token' }]);
  });

  it('shows the problems the back end finds on submit, in the summary', async () => {
    server.use(
      http.post(`/api/bff/registrations/${ID}/submit`, (() =>
        HttpResponse.json({ code: 'invalid', errors: [{ field: 'section-service', message: 'Service is not complete' }] }, { status: 422 })) as HttpResponseResolver),
    );
    await open();
    await userEvent.click(screen.getByRole('button', { name: 'Submit for approval' }));
    expect(await screen.findByRole('heading', { name: 'There is a problem' })).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it('shows a loading state while the review is read', () => {
    render(<ReviewList registrationId={ID} />);
    expect(screen.getByText('Loading your registration.').closest('[role="status"]')).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('heading', { level: 1, name: 'Check your details' })).toBeInTheDocument();
  });

  it('Back goes to the reporting step, and the review has no axe violations', async () => {
    const { container } = await open();
    expect(screen.getByRole('link', { name: 'Back' })).toHaveAttribute('href', `/register/${ID}/reporting`);
    expect((await runAxe(container)).violations).toEqual([]);
  });

  it('has no axe violations with a section that needs attention', async () => {
    withSection('service', 'needs-attention', 'UCR West · criteria review date missing');
    const { container } = await openWithAttention();
    expect((await runAxe(container)).violations).toEqual([]);
  });

  it('on a phone the sticky Submit is the disabled primary action and the count stays visible', async () => {
    phone(true);
    withSection('service', 'needs-attention', 'UCR West · criteria review date missing');
    await openWithAttention();
    expect(screen.queryByRole('navigation', { name: 'Your registration' })).not.toBeInTheDocument();
    const buttons = screen.getAllByRole('button', { name: 'Submit for approval' });
    for (const button of buttons) expect(button).toBeDisabled();
    expect(screen.getAllByText('1 section needs attention first').length).toBeGreaterThan(0);
    expect(screen.getByRole('link', { name: 'Save and come back later' })).toHaveAttribute('href', '/register?saved=1');
  });

  it('shows the load failure when the review cannot be read', async () => {
    server.use(http.get(`/api/bff/registrations/${ID}/review`, (() => HttpResponse.json({ code: 'not-built' }, { status: 503 })) as HttpResponseResolver));
    render(<ReviewList registrationId={ID} />);
    expect(await screen.findByText('We could not load your registration. Try again later.')).toBeInTheDocument();
  });
});
