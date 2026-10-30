import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { OutOfArea, PostcodeNotFound } from './PostcodeStates';

describe('PostcodeNotFound (W50)', () => {
  it('says the postcode was not found, and what to do', () => {
    render(<PostcodeNotFound caseId="4821" onAskClinical={vi.fn()} />);

    expect(screen.getByRole('heading', { name: 'We could not find that postcode' })).toBeInTheDocument();
    expect(screen.getByText('Check it with the caller, or choose the district.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Change the postcode' })).toHaveAttribute('href', '/advisor/case/4821');
  });

  it('asks a clinical advisor and never ends the call', async () => {
    const user = userEvent.setup();
    const onAskClinical = vi.fn();
    render(<PostcodeNotFound caseId="4821" onAskClinical={onAskClinical} />);

    await user.click(byEl('ADV-NOFIT-CLINICAL-BTN'));
    expect(onAskClinical).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('link', { name: 'Other routes under local protocol' })).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <main>
        <PostcodeNotFound caseId="4821" onAskClinical={vi.fn()} />
      </main>,
    );
    expect((await runAxe(container)).violations).toEqual([]);
  });
});

describe('OutOfArea (W50)', () => {
  it('says no service covers the area, names the postcode, and offers a next step', () => {
    render(<OutOfArea caseId="4821" postcode="DT4 8XX" onAskClinical={vi.fn()} />);

    expect(screen.getByRole('heading', { name: 'No service covers this area' })).toBeInTheDocument();
    expect(
      screen.getByText('DT4 8XX is outside the areas the services here cover. Do not leave the caller without a next step.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Other routes under local protocol' })).toHaveAttribute(
      'href',
      '/advisor/case/4821/finish?outcome=out-of-area',
    );
    expect(screen.getByRole('link', { name: 'Change the postcode' })).toBeInTheDocument();
    expect(
      screen.getByText('Out-of-area referrals are recorded as an outcome so the coverage can be reviewed.'),
    ).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <main>
        <OutOfArea caseId="4821" postcode="DT4 8XX" onAskClinical={vi.fn()} />
      </main>,
    );
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
