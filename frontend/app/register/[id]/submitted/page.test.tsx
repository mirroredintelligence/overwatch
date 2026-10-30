import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import SubmittedPage from './page';

describe('submitted page', () => {
  it('says the registration is submitted, what happens next, and links back to My services', async () => {
    const { container } = render(await SubmittedPage({ params: Promise.resolve({ id: 'REG-SAMPLE-1' }) }));
    expect(screen.getByRole('heading', { level: 1, name: 'Submitted for approval' })).toBeInTheDocument();
    expect(
      screen.getByText(/The SPOA shift lead will check your details and send a test text to the number you gave\./),
    ).toBeInTheDocument();
    expect(screen.getByText('You will get an email when it is approved, or if something needs changing.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to my services' })).toHaveAttribute('href', '/register/services');
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
