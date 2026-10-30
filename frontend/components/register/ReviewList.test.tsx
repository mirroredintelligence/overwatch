import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetStepSaves, reviewState, seenSubmits } from '@/test/msw/handlers/registration';
import { server } from '@/test/msw/server';
import { ReviewList } from './ReviewList';

// Registration step 5, the review (W26, artboard RegisterFlow3 panel 9). Submit goes only when every
// section is complete; otherwise the summary lists the sections that need attention, and nothing is sent.

const push = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const ID = 'REG-SAMPLE-1';

async function open() {
  const view = render(<ReviewList registrationId={ID} />);
  await screen.findByRole('heading', { level: 1, name: 'Check your details' });
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

beforeEach(() => {
  push.mockClear();
  resetStepSaves();
});

describe('ReviewList', () => {
  it('lists the five sections with their status words, summaries and Change links', async () => {
    await open();
    expect(screen.getByText('Step 5 of 5 · Review')).toBeInTheDocument();
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
    }
    expect(
      screen.getByText('UCR West · Urgent community response · refer by phone and SystmOne'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('The SPOA shift lead checks your details and sends a test text. You will not appear on the board until approved.'),
    ).toBeInTheDocument();
  });

  it('shows "Needs attention" as a word on its row', async () => {
    withSection('service', 'needs-attention', 'UCR West · criteria review date missing');
    await open();
    const row = screen.getByRole('listitem', { name: /^Service/ });
    expect(within(row).getByText('Needs attention')).toBeInTheDocument();
    expect(within(row).getByText('UCR West · criteria review date missing')).toBeInTheDocument();
  });

  it('Submit with a section that needs attention shows the summary listing it, and does not post', async () => {
    withSection('service', 'needs-attention', 'UCR West · criteria review date missing');
    await open();
    await userEvent.click(screen.getByRole('button', { name: 'Submit for approval' }));
    const heading = await screen.findByRole('heading', { name: 'There is a problem' });
    expect(heading.closest('[role="alert"]')).toHaveFocus();
    expect(screen.getByRole('link', { name: 'Service needs attention' })).toHaveAttribute('href', '#section-service');
    expect(seenSubmits).toHaveLength(0);
  });

  it('Submit with every section complete posts with the CSRF header and lands on the submitted page', async () => {
    await open();
    await userEvent.click(screen.getByRole('button', { name: 'Submit for approval' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith(`/register/${ID}/submitted`));
    expect(seenSubmits).toEqual([{ id: ID, csrf: 'csrf-sample-token' }]);
  });

  it('Back goes to the reporting step, and the review has no axe violations', async () => {
    const { container } = await open();
    expect(screen.getByRole('link', { name: 'Back' })).toHaveAttribute('href', `/register/${ID}/reporting`);
    expect((await runAxe(container)).violations).toEqual([]);
  });

  it('shows the load failure when the review cannot be read', async () => {
    server.use(http.get(`/api/bff/registrations/${ID}/review`, (() => HttpResponse.json({ code: 'not-built' }, { status: 503 })) as HttpResponseResolver));
    render(<ReviewList registrationId={ID} />);
    expect(await screen.findByText('We could not load your registration. Try again later.')).toBeInTheDocument();
  });
});
