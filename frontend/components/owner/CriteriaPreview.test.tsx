import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import type { CriteriaValues } from '@/lib/criteria/types';
import { CriteriaPreview } from './CriteriaPreview';

const VALUES: CriteriaValues = {
  accepts: ['fall-no-injury', 'frailty', 'dementia'],
  excludes: ['suspected-fracture', 'head-injury-anticoagulants'],
  ageMin: 16,
  ageMax: null,
  districts: ['DT1', 'DT2', 'DT3', 'DT4'],
};

const panel = (name: string) => screen.getByRole('region', { name });

describe('CriteriaPreview', () => {
  it('is headed Preview, with a panel for what advisors will see and a panel for what changed', () => {
    render(<CriteriaPreview serviceName="UCR West" values={VALUES} changes={['Youngest age 18 to 16']} />);
    expect(screen.getByRole('heading', { level: 1, name: 'Preview' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'What advisors will see' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'What changed' })).toBeInTheDocument();
    expect(panel('What advisors will see')).toBeInTheDocument();
    expect(panel('What changed')).toBeInTheDocument();
  });

  it('shows the service, and what it accepts and does not accept, in the advisor words', () => {
    render(<CriteriaPreview serviceName="UCR West" values={VALUES} changes={[]} />);
    const seen = within(panel('What advisors will see'));
    expect(seen.getByText('UCR West')).toBeInTheDocument();
    expect(seen.getByText('Accepts')).toBeInTheDocument();
    expect(seen.getByText('Fall, no injury, Frailty, Dementia, age 16+')).toBeInTheDocument();
    expect(seen.getByText('Does not accept')).toBeInTheDocument();
    expect(seen.getByText('Suspected fracture, Head injury on anticoagulants')).toBeInTheDocument();
  });

  it('shows a changed age as the field, what it was and what it is now, and counts the change', () => {
    render(<CriteriaPreview serviceName="UCR West" values={VALUES} changes={['Youngest age 18 to 16']} />);
    const changed = within(panel('What changed'));
    expect(changed.getByText('Youngest age')).toBeInTheDocument();
    expect(changed.getByText('18')).toBeInTheDocument();
    expect(changed.getByText('16')).toBeInTheDocument();
    expect(changed.getByText('1 change. Everything else is as it is now.')).toBeInTheDocument();
  });

  it('reads "No limit" as one value', () => {
    render(<CriteriaPreview serviceName="UCR West" values={VALUES} changes={['Oldest age No limit to 80']} />);
    const changed = within(panel('What changed'));
    expect(changed.getByText('Oldest age')).toBeInTheDocument();
    expect(changed.getByText('No limit')).toBeInTheDocument();
    expect(changed.getByText('80')).toBeInTheDocument();
  });

  it('shows a list change in the words the diff gives, and counts every change', () => {
    render(
      <CriteriaPreview serviceName="UCR West" values={VALUES} changes={['Youngest age 18 to 16', 'Accepts: added Dementia']} />,
    );
    const changed = within(panel('What changed'));
    expect(changed.getByText('Accepts: added Dementia')).toBeInTheDocument();
    expect(changed.getByText('2 changes. Everything else is as it is now.')).toBeInTheDocument();
  });

  it('says nothing changed when there is no change', () => {
    render(<CriteriaPreview serviceName="UCR West" values={VALUES} changes={[]} />);
    expect(within(panel('What changed')).getByText('Nothing changed.')).toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <CriteriaPreview serviceName="UCR West" values={VALUES} changes={['Youngest age 18 to 16']} />,
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
