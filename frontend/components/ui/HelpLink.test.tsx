import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { HelpLink } from './HelpLink';

describe('HelpLink', () => {
  it('is a link labelled Help that goes to the help page', () => {
    render(<HelpLink />);
    expect(screen.getByRole('link', { name: 'Help' })).toHaveAttribute('href', '/help');
  });
});
