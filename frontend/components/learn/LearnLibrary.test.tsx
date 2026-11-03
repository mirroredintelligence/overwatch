import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { LESSONS } from '@/lib/learn/content';
import { markDone } from '@/lib/learn/progress';
import { LearnLibrary } from './LearnLibrary';

afterEach(() => {
  window.localStorage.clear();
});

describe('LearnLibrary', () => {
  it('has the page heading and counts the lessons done out of all of them', () => {
    markDone('reply-to-a-prompt');
    render(<LearnLibrary />);

    expect(screen.getByRole('heading', { level: 1, name: '2-minute lessons' })).toBeInTheDocument();
    expect(screen.getByText(`1 of ${LESSONS.length} done`)).toBeInTheDocument();
  });

  it('shows "2 min · done" for a lesson that is done, "up next" for the first not done, and "Draft" for a draft', () => {
    markDone('reply-to-a-prompt');
    render(<LearnLibrary />);

    const list = screen.getByRole('list', { name: 'Reporter lessons' });
    expect(within(list).getByRole('link', { name: /Reply to a prompt.*2 min · done/ })).toBeInTheDocument();
    expect(within(list).getByRole('link', { name: /Correct a figure.*2 min · up next/ })).toBeInTheDocument();
    expect(within(list).getByRole('link', { name: /Cover when you are away.*2 min · Draft/ })).toBeInTheDocument();
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

  it('changes role with the tabs, and with the arrow keys', async () => {
    render(<LearnLibrary />);

    await userEvent.click(screen.getByRole('tab', { name: 'Advisor' }));
    expect(screen.getByRole('tab', { name: 'Advisor' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('list', { name: 'Advisor lessons' })).toBeInTheDocument();

    await userEvent.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Shift lead' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Shift lead' })).toHaveFocus();
  });

  it('shows the open lesson beside the list and marks it as the current one', () => {
    render(
      <LearnLibrary initialRole="reporter" activeId="correct-a-figure">
        <p>The open lesson</p>
      </LearnLibrary>,
    );

    expect(screen.getByText('The open lesson')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Correct a figure/ })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: /Reply to a prompt/ })).not.toHaveAttribute('aria-current');
  });

  it('has a way back and the bottom bar of Home, Learn and Help', () => {
    render(<LearnLibrary />);

    expect(screen.getByRole('link', { name: 'Back' })).toHaveAttribute('href', '/');
    const bar = screen.getByRole('navigation', { name: 'Sections' });
    expect(within(bar).getByRole('link', { name: 'Home' })).toHaveAttribute('href', '/');
    expect(within(bar).getByRole('link', { name: 'Learn' })).toHaveAttribute('aria-current', 'page');
    expect(within(bar).getByRole('link', { name: 'Help' })).toHaveAttribute('href', '/help');
  });

  it('goes back to the list from an open lesson', () => {
    render(
      <LearnLibrary activeId="correct-a-figure">
        <p>The open lesson</p>
      </LearnLibrary>,
    );

    expect(screen.getByRole('link', { name: 'Back' })).toHaveAttribute('href', '/learn');
  });

  it('passes vitest-axe', async () => {
    const { container } = render(<LearnLibrary />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
