import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { PracticeView } from './PracticeView';

describe('PracticeView', () => {
  it('says nothing is sent and makes no network call', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    render(<PracticeView lessonId="correct-a-figure" />);

    expect(screen.getByText('Practice. Nothing is sent.')).toBeInTheDocument();
    expect(screen.getByText('Sample data')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Yes, still 3' }));

    expect(screen.getByText('Practice done')).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it('leaves practice back to the lesson', () => {
    render(<PracticeView lessonId="correct-a-figure" />);

    expect(screen.getByRole('link', { name: 'Leave practice' })).toHaveAttribute('href', '/learn/correct-a-figure');
  });

  it('passes vitest-axe', async () => {
    const { container } = render(<PracticeView lessonId="correct-a-figure" />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
