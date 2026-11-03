import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { StepHelp } from './StepHelp';

describe('StepHelp', () => {
  it('shows a short "Why we ask" for each of the first four steps', () => {
    const seen = new Set<string>();
    for (const step of [1, 2, 3, 4]) {
      const { container, unmount } = render(<StepHelp step={step} />);
      expect(screen.getByText('Why we ask')).toBeInTheDocument();
      const text = container.textContent ?? '';
      expect(text.length).toBeGreaterThan(40);
      seen.add(text);
      unmount();
    }
    expect(seen.size).toBe(4);
  });

  it('says why the ODS code and a contact are asked on step 1', () => {
    render(<StepHelp step={1} />);
    expect(screen.getByText(/ODS code lets us check your organisation/)).toBeInTheDocument();
  });

  it('draws nothing for the review step or one that does not exist', () => {
    expect(render(<StepHelp step={5} />).container).toBeEmptyDOMElement();
    expect(render(<StepHelp step={0} />).container).toBeEmptyDOMElement();
  });

  it('is a disclosure on a phone: closed, then open on request', () => {
    render(<StepHelp step={2} variant="disclosure" />);
    const button = screen.getByRole('button', { name: /Why we ask/ });
    expect(button).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText(/The address gives us the position on the map/)).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(<StepHelp step={3} />);
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
