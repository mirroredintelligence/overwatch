import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { getDone } from '@/lib/learn/progress';
import { LearnLibrary } from './LearnLibrary';
import { LessonView } from './LessonView';

afterEach(() => {
  window.localStorage.clear();
});

describe('LessonView', () => {
  it('shows the role and length, the title and the numbered steps of "Correct a figure"', () => {
    render(<LessonView lessonId="correct-a-figure" />);

    expect(screen.getByRole('heading', { name: 'Correct a figure' })).toBeInTheDocument();
    expect(screen.getByText('Reporter · 2 minutes')).toBeInTheDocument();
    expect(screen.getByText('Open the notification or the app')).toBeInTheDocument();
    expect(screen.getByText('Enter your PIN')).toBeInTheDocument();
    expect(screen.getByText('The new figure replaces the old one')).toBeInTheDocument();
    expect(screen.getByText('Corrections are fine. The board shows the latest figure and its time.')).toBeInTheDocument();
  });

  it('starts at step 1 of 3 and Next step moves the current step on', async () => {
    render(<LessonView lessonId="correct-a-figure" />);

    expect(screen.getByText('Step 1 of 3')).toBeInTheDocument();
    expect(screen.getByText('Open the notification or the app').closest('li')).toHaveAttribute('aria-current', 'step');

    await userEvent.click(screen.getByRole('button', { name: 'Next step' }));

    expect(screen.getByText('Step 2 of 3')).toBeInTheDocument();
    expect(screen.getByText('Send the right number').closest('li')).toHaveAttribute('aria-current', 'step');
    expect(screen.getByText('Open the notification or the app').closest('li')).not.toHaveAttribute('aria-current');
  });

  it('marks the lesson done on the last step, and the library shows it done when it is opened again', async () => {
    const { unmount } = render(<LessonView lessonId="correct-a-figure" />);

    expect(screen.queryByRole('button', { name: 'Mark as done' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Next step' }));
    await userEvent.click(screen.getByRole('button', { name: 'Next step' }));
    expect(screen.getByText('Step 3 of 3')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Mark as done' }));

    expect(getDone().has('correct-a-figure')).toBe(true);
    expect(screen.getByRole('status')).toHaveTextContent('Done');
    unmount();

    render(<LearnLibrary />);
    await waitFor(() => expect(screen.getByRole('link', { name: /Correct a figure.*2 min · done/ })).toBeInTheDocument());
  });

  it('links to the practice mode of the lesson as "Try it, nothing is sent"', () => {
    render(<LessonView lessonId="correct-a-figure" />);

    expect(screen.getByRole('link', { name: 'Try it, nothing is sent' })).toHaveAttribute('href', '/learn/correct-a-figure/practice');
  });

  it('says a draft lesson is a draft, shows its placeholder and still lets it be marked done', async () => {
    render(<LessonView lessonId="cover-when-away" />);

    expect(screen.getByText('Draft')).toBeInTheDocument();
    expect(screen.getByText('This lesson is being written. Ask your champion for the current steps.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Mark as done' }));
    expect(getDone().has('cover-when-away')).toBe(true);
  });

  it('says so when the lesson does not exist', () => {
    render(<LessonView lessonId="nope" />);

    expect(screen.getByRole('alert')).toHaveTextContent('That lesson is not here.');
  });

  it('passes vitest-axe', async () => {
    const { container } = render(<LessonView lessonId="correct-a-figure" />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
