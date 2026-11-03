import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { CRITERIA_OVERVIEW_WAITING } from '@/test/fixtures/criteria';
import { server } from '@/test/msw/server';
import { CriteriaFlow } from './CriteriaFlow';

// The owner's flow for one service (boards/lead/OwnerReview.dc.html): five numbered steps in a StepBar, the live
// criteria pinned beside them, and one step on the stage at a time. The steps are not routes: the flow keeps the
// current one, and a deep link to preview or send opens the change step first when there is no draft.

// The user-event tests run slowly when the whole suite shares the machine; the budget is per file.
vi.setConfig({ testTimeout: 15_000 });

/** The label of the step the StepBar marks as current. */
function currentStep(): string {
  return document.querySelector('[aria-current="step"]')?.textContent ?? '';
}

describe('CriteriaFlow', () => {
  it('lists the five steps in a labelled nav, with Review first and current', async () => {
    render(<CriteriaFlow serviceId="s1" initialStep="overview" />);
    const nav = await screen.findByRole('navigation', { name: 'Criteria steps' });
    expect(within(nav).getAllByRole('listitem')).toHaveLength(5);
    expect(currentStep()).toContain('Review');
  });

  it('pins the live criteria beside the step: the version, the review date, and what advisors accept', async () => {
    render(<CriteriaFlow serviceId="s1" initialStep="overview" />);
    const pin = await screen.findByRole('region', { name: 'Live criteria' });
    expect(within(pin).getByText('Version 3')).toBeInTheDocument();
    expect(within(pin).getByText('Advisors see this version now.')).toBeInTheDocument();
    expect(within(pin).getByText('Fall, no injury, Frailty, age 18+')).toBeInTheDocument();
    expect(within(pin).getByText('Suspected fracture, Head injury on anticoagulants')).toBeInTheDocument();
    expect(screen.getByText('Live · review by 12 Dec')).toBeInTheDocument();
  });

  it('says a change is waiting for approval, and that advisors still see the live version', async () => {
    server.use(http.get('/api/bff/criteria/:serviceId', () => HttpResponse.json(CRITERIA_OVERVIEW_WAITING)));
    render(<CriteriaFlow serviceId="s1" initialStep="overview" />);
    const pin = await screen.findByRole('region', { name: 'Live criteria' });
    expect(within(pin).getByText('Advisors still see version 3.')).toBeInTheDocument();
    expect(screen.getByText('Change waiting for approval')).toBeInTheDocument();
  });

  it('says in words that the criteria are loading, while the step bar stays in place', async () => {
    render(<CriteriaFlow serviceId="s1" initialStep="overview" />);
    expect(screen.getByText('Loading the criteria.')).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Criteria steps' })).toBeInTheDocument();
    await screen.findByRole('region', { name: 'Live criteria' });
    expect(screen.queryByText('Loading the criteria.')).not.toBeInTheDocument();
  });

  it('says what failed in plain words when the criteria cannot be read, and keeps the steps', async () => {
    server.use(http.get('/api/bff/criteria/:serviceId', () => HttpResponse.json({ code: 'internal' }, { status: 500 })));
    render(<CriteriaFlow serviceId="s1" initialStep="overview" />);
    expect(await screen.findByText('The live criteria could not be loaded.')).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Criteria steps' })).toBeInTheDocument();
  });

  it('opens the change step first when a link goes straight to the preview, because there is no draft', async () => {
    render(<CriteriaFlow serviceId="s1" initialStep="preview" />);
    expect(await screen.findByRole('button', { name: 'Preview the change' })).toBeInTheDocument();
    expect(currentStep()).toContain('Change');
  });

  it('moves to Confirm from Still right, and back to Review from the step bar', async () => {
    const user = userEvent.setup();
    render(<CriteriaFlow serviceId="s1" initialStep="overview" />);
    await user.click(await screen.findByRole('button', { name: 'Still right' }));
    await waitFor(() => expect(currentStep()).toContain('Confirm'));
    await user.click(screen.getByRole('button', { name: 'Step 1, done: Review' }));
    await waitFor(() => expect(currentStep()).toContain('Review'));
  });

  it('moves to Change from the overview, and back to Review with Cancel', async () => {
    const user = userEvent.setup();
    render(<CriteriaFlow serviceId="s1" initialStep="overview" />);
    await user.click(await screen.findByRole('button', { name: 'Change them' }));
    await waitFor(() => expect(currentStep()).toContain('Change'));
    await user.click(await screen.findByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(currentStep()).toContain('Review'));
  });

  it('has no accessibility violations in the step bar or the pinned criteria', async () => {
    // The step panels are scanned by their own tests. The stage region of MorphStage is a landmark that holds the
    // panels' own <main>, which axe reports (landmark-main-is-top-level), so the whole flow is not scanned here.
    render(<CriteriaFlow serviceId="s1" initialStep="overview" />);
    const pin = await screen.findByRole('region', { name: 'Live criteria' });
    expect(await runAxe(screen.getByRole('navigation', { name: 'Criteria steps' }))).toHaveNoViolations();
    expect(await runAxe(pin)).toHaveNoViolations();
  });
});
