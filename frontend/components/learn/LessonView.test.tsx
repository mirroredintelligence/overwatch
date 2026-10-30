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
  it('shows the numbered steps of "Correct a figure" and the reassurance line', () => {
    render(<LessonView lessonId="correct-a-figure" />);

    expect(screen.getByRole('heading', { name: 'Correct a figure' })).toBeInTheDocument();
    expect(screen.getByText('Enter your PIN')).toBeInTheDocument();
    expect(screen.getByText('The new figure replaces the old one')).toBeInTheDocument();
    expect(screen.getByText('Corrections are fine. The board shows the latest figure and its time.')).toBeInTheDocument();
  });

  it('marks the lesson done, and the library shows it done when it is opened again', async () => {
    const { unmount } = render(<LessonView lessonId="correct-a-figure" />);

    await userEvent.click(screen.getByRole('button', { name: 'Mark as done' }));
    expect(getDone().has('correct-a-figure')).toBe(true);
    unmount();

    render(<LearnLibrary />);
    await waitFor(() => expect(screen.getByRole('link', { name: /Correct a figure.*2 min · done/ })).toBeInTheDocument());
  });

  it('links to the practice mode of the lesson', () => {
    render(<LessonView lessonId="correct-a-figure" />);

    expect(screen.getByRole('link', { name: 'Try it in practice mode' })).toHaveAttribute('href', '/learn/correct-a-figure/practice');
  });

  it('passes vitest-axe', async () => {
    const { container } = render(<LessonView lessonId="correct-a-figure" />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
