import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { HelpPanel } from './HelpPanel';

describe('HelpPanel', () => {
  it('offers the four ways to get help, and the coordination team number as selectable text', () => {
    render(<HelpPanel spoaPhone="01305 000000" champion="Sam" />);

    expect(screen.getByRole('link', { name: 'Read the one-page guide' })).toBeInTheDocument();
    expect(screen.getByText('Ask your champion, Sam')).toBeInTheDocument();
    expect(screen.getByText('01305 000000')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Report a problem' })).toHaveAttribute('href', '/help/problem');
  });

  it('does not invent a number when the service has none set', () => {
    render(<HelpPanel spoaPhone={null} />);

    expect(screen.getByText('The number is not set for your service yet. Ask your shift lead.')).toBeInTheDocument();
  });

  it('passes vitest-axe', async () => {
    const { container } = render(<HelpPanel spoaPhone="01305 000000" />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
