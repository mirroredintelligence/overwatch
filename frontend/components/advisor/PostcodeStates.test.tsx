import { render, screen, within } from '@testing-library/react';
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

// The district chips (W50, W9H DEC-1045, DEC-1046): when the postcode was not found, or no service covers
// its area, the advisor can choose one of the districts the services do cover and run the options again.
// A chip is a button that says what it does; a choice that cannot be saved is said, and the call is never
// ended here.

describe('district chips (W50)', () => {
  const chips = ['DT1', 'DT3', 'BH21'];

  it('offers each district as a button, with the way the options will change, in the state of a postcode not found', () => {
    render(<PostcodeNotFound caseId="4821" onAskClinical={vi.fn()} districts={chips} onChooseDistrict={vi.fn()} />);

    const group = screen.getByRole('group', { name: 'Choose the district' });
    expect(within(group).getAllByRole('button').map((b) => b.textContent)).toEqual(chips);
    expect(screen.getByText('Options will use the district, with a wider travel range.')).toBeInTheDocument();
    expect(screen.getByText('Check it with the caller, or choose the district.')).toBeInTheDocument();
  });

  it('offers them in the state of an area no service covers, with the same note', () => {
    render(<OutOfArea caseId="4821" postcode="DT9" onAskClinical={vi.fn()} districts={['DT1']} onChooseDistrict={vi.fn()} />);

    expect(within(screen.getByRole('group', { name: 'Choose the district' })).getByRole('button', { name: 'DT1' })).toBeInTheDocument();
    expect(screen.getByText('Options will use the district, with a wider travel range.')).toBeInTheDocument();
  });

  it('chooses the district pressed, once, and says it is being used while it is saved', async () => {
    const user = userEvent.setup();
    let finish: (value: boolean) => void = () => undefined;
    const choose = vi.fn(() => new Promise<boolean>((resolve) => (finish = resolve)));
    render(<PostcodeNotFound caseId="4821" onAskClinical={vi.fn()} districts={chips} onChooseDistrict={choose} />);

    await user.click(screen.getByRole('button', { name: 'DT3' }));
    await user.click(screen.getByRole('button', { name: 'DT3' }));

    expect(choose).toHaveBeenCalledTimes(1);
    expect(choose).toHaveBeenCalledWith('DT3');
    expect(await screen.findByText('Using DT3.')).toBeInTheDocument();
    for (const chip of within(screen.getByRole('group', { name: 'Choose the district' })).getAllByRole('button')) expect(chip).toBeDisabled();
    finish(true);
  });

  it('says so, and lets the advisor try again or pick another, when the choice could not be saved', async () => {
    const user = userEvent.setup();
    const choose = vi.fn(async () => false);
    render(<OutOfArea caseId="4821" postcode="DT9" onAskClinical={vi.fn()} districts={chips} onChooseDistrict={choose} />);

    await user.click(screen.getByRole('button', { name: 'DT1' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('We could not use that district. Try again, or choose another.');
    for (const chip of within(screen.getByRole('group', { name: 'Choose the district' })).getAllByRole('button')) expect(chip).toBeEnabled();
    await user.click(screen.getByRole('button', { name: 'BH21' }));
    expect(choose).toHaveBeenLastCalledWith('BH21');
  });

  it('offers no chips, and does not say to choose one, when there are none to choose from', () => {
    render(<PostcodeNotFound caseId="4821" onAskClinical={vi.fn()} districts={[]} onChooseDistrict={vi.fn()} />);

    expect(screen.queryByRole('group', { name: 'Choose the district' })).not.toBeInTheDocument();
    expect(screen.getByText('Check it with the caller.')).toBeInTheDocument();
  });

  it('keeps the other ways on: ask a clinical advisor, other routes, change the postcode', () => {
    render(<OutOfArea caseId="4821" postcode="DT9" onAskClinical={vi.fn()} districts={chips} onChooseDistrict={vi.fn()} />);

    expect(byEl('ADV-NOFIT-CLINICAL-BTN')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Other routes under local protocol' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Change the postcode' })).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <main>
        <PostcodeNotFound caseId="4821" onAskClinical={vi.fn()} districts={chips} onChooseDistrict={vi.fn()} />
        <OutOfArea caseId="4821" postcode="DT9" onAskClinical={vi.fn()} districts={chips} onChooseDistrict={vi.fn()} />
      </main>,
    );
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
