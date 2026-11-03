import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { StateBanner, type StateBannerTone } from './StateBanner';

// The shared states (artboard St): bad signal, something went wrong, success. A bold lead, then what was kept.

describe('StateBanner', () => {
  it('shows the bold lead and what was kept', async () => {
    const { container } = render(
      <StateBanner tone="offline" lead="No signal. Not sent yet.">
        Nothing has been lost. Your number is still here.
      </StateBanner>,
    );
    const banner = screen.getByRole('alert');
    expect(banner).toHaveTextContent('No signal. Not sent yet.');
    expect(banner).toHaveTextContent('Nothing has been lost. Your number is still here.');
    expect(banner.querySelector('strong')).toHaveTextContent('No signal. Not sent yet.');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it.each<[StateBannerTone, string]>([
    ['offline', 'alert'],
    ['error', 'alert'],
    ['warning', 'status'],
    ['info', 'status'],
  ])('announces the %s tone as a %s', (tone, role) => {
    render(<StateBanner tone={tone} lead="Lead." />);
    expect(screen.getByRole(role)).toHaveAttribute('data-tone', tone);
  });

  it('draws a different shape for each tone, so none is told apart by colour alone', () => {
    const shapes = (['offline', 'error', 'warning', 'info'] as const).map((tone) => {
      const { container, unmount } = render(<StateBanner tone={tone} lead="Lead." />);
      const html = container.querySelector('svg')?.innerHTML;
      unmount();
      return html;
    });
    expect(new Set(shapes).size).toBe(4);
  });

  it('hides the picture from a screen reader', () => {
    const { container } = render(<StateBanner tone="error" lead="We could not send that." />);
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
  });

  it('works with a lead alone', () => {
    render(<StateBanner tone="info" lead="Recorded at 10:12.">Next update due 12:00.</StateBanner>);
    expect(screen.getByRole('status')).toHaveTextContent('Recorded at 10:12. Next update due 12:00.');
  });
});
