import { render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { markDone } from '@/lib/learn/progress';
import { LearnLibrary } from './LearnLibrary';

afterEach(() => {
  window.localStorage.clear();
});

describe('LearnLibrary', () => {
  it('shows "2 min · done" for a lesson that is done, and "2 min" for one that is not', () => {
    markDone('reply-to-a-prompt');
    render(<LearnLibrary />);

    const list = screen.getByRole('list', { name: 'Reporter lessons' });
    expect(within(list).getByRole('link', { name: /Reply to a prompt.*2 min · done/ })).toBeInTheDocument();
    expect(within(list).getByRole('link', { name: /Correct a figure.*2 min$/ })).toBeInTheDocument();
  });

  it('"Start the next lesson" opens the first lesson that is not done', () => {
    markDone('reply-to-a-prompt');
    render(<LearnLibrary />);

    expect(screen.getByRole('link', { name: 'Start the next lesson' })).toHaveAttribute('href', '/learn/correct-a-figure');
  });

  it('labels a draft lesson as Draft', async () => {
    render(<LearnLibrary initialRole="advisor" />);

    expect(screen.getByRole('link', { name: /Start a call.*Draft/ })).toBeInTheDocument();
  });

  it('passes vitest-axe', async () => {
    const { container } = render(<LearnLibrary />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
