import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { CriteriaValues } from '@/lib/criteria/types';
import { CriteriaPreview } from './CriteriaPreview';

const VALUES: CriteriaValues = {
  accepts: ['fall-no-injury', 'frailty', 'dementia'],
  excludes: ['suspected-fracture', 'head-injury-anticoagulants'],
  ageMin: 16,
  ageMax: null,
  districts: ['DT1', 'DT2', 'DT3', 'DT4'],
};

describe('CriteriaPreview', () => {
  it('shows what advisors will see, and what changed', () => {
    render(<CriteriaPreview serviceName="UCR West" values={VALUES} changes={['Youngest age 18 to 16']} />);
    expect(screen.getByRole('heading', { name: 'What advisors will see' })).toBeInTheDocument();
    expect(screen.getByText('UCR West')).toBeInTheDocument();
    expect(screen.getByText('Accepts: Fall, no injury, Frailty, Dementia, age 16+')).toBeInTheDocument();
    expect(screen.getByText('Does not accept: Suspected fracture, Head injury on anticoagulants')).toBeInTheDocument();
    expect(screen.getByText('Youngest age 18 to 16')).toBeInTheDocument();
  });
});
